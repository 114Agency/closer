import os
import json
from typing import Dict, Any
from dotenv import load_dotenv

from config import settings
import litellm
import instructor
from pydantic import BaseModel, Field
import guardrails as gd
from langfuse import Langfuse, observe, propagate_attributes

from tools.whatsapp_tool import send_whatsapp_message
from tools.crm_tool import update_crm_after_message
from tools.cal_tool import get_available_slots

load_dotenv()

# Initialisation du client Langfuse central
langfuse_client = Langfuse()

# Modèles Pydantic pour Instructor
class SentimentAnalysis(BaseModel):
    score: float = Field(..., description="Score de sentiment de 0.0 (très négatif/frustré) à 1.0 (très positif).")
    is_escalation_needed: bool = Field(..., description="True si le prospect est frustré, en colère ou négatif.")
    intention: str = Field(..., description="L'intention du prospect (ex: DEMANDE_RDV, QUESTION_TECHNIQUE, DEMANDE_PRIX, REFUS, INFO).")

class ObjectionAnalysis(BaseModel):
    intention: str = Field(..., description="L'intention exacte : PRENDRE_RDV, INTERESSE, OBJECTION_PRIX, OBJECTION_TEMPS, REFUS")
    reponse_generee: str = Field(..., description="Réponse courte de 1 à 2 phrases maximum.")

class CloserAgent:
    def __init__(self):
        print("🧠 [CLOSER] Initialisation de l'Agent Closer (Phase C)...")
        
        # 🎯 NOUVEAU : Mapping strict des modèles Dev OpenRouter
        self.model_workhorse = settings.models.workhorse     # DeepSeek V4 Flash
        self.model_quality = settings.models.quality         # DeepSeek V4 Pro
        
        self.client = instructor.from_litellm(litellm.acompletion)

        # 🛡️ Initialisation d'un Guardrail basique (sans le Hub externe pour l'instant)
        self.reply_guard = gd.Guard()

    @observe(name="[Closer : Sortant] Handle Out-of-Template Reply")
    async def handle_out_of_template_reply(self, lead_data: Dict[str, Any], message_text: str) -> Dict[str, Any]:
        """
        Gère les réponses libres avec analyse de sentiment (Flash) et génération (Pro).
        """
        lead_id = lead_data.get("lead_id", "unknown")
        name = lead_data.get("first_name", "Client")
        numero_client = lead_data.get("phone", "+212600000000")

        # Création de la session Langfuse pour l'audit complet
        with propagate_attributes(
            user_id=lead_id,
            session_id=lead_id,
            tags=[lead_id, "phase_c", "out_of_template"]
        ):
            # ==========================================
            # ÉTAPE 1 : DÉTECTION DE SENTIMENT (DeepSeek V4 Flash)
            # ==========================================
            # messages_pour_sentiment = [
            #     {"role": "system", "content": "Analyse le sentiment de ce message client. Si c'est de la frustration, de la colère ou une plainte, is_escalation_needed doit être True."},
            #     {"role": "user", "content": message_text}
              # ]

            # 1. Télécharger le prompt dynamique depuis Langfuse
            prompt_sentiment = langfuse_client.get_prompt("closer_sentiment_analysis")
            system_instruction_sentiment = prompt_sentiment.compile()
            messages_pour_sentiment = [
                {"role": "system", "content": system_instruction_sentiment},
                {"role": "user", "content": message_text}
            ]

            with langfuse_client.start_as_current_observation(
                as_type="generation",
                name="sentiment-detection",
                model=self.model_workhorse, 
                prompt=prompt_sentiment,
                input=messages_pour_sentiment
            ) as sentiment_trace:
                
                sentiment_result = await self.client.messages.create_with_completion(
                    model=self.model_workhorse,
                    messages=messages_pour_sentiment,
                    response_model=SentimentAnalysis,
                )
                
                sentiment_data = sentiment_result[0]
                raw_response = sentiment_result[1]
                # 🎯 CORRECTION : Création de la variable usage_data manquante
                usage_data = getattr(raw_response, 'usage', None)
                usage_details = {}
                if usage_data:
                    # Gestion de la structure (dict ou objet) selon la version d'Instructor/LiteLLM
                    if isinstance(usage_data, dict):
                        usage_details = {
                            "input": usage_data.get("prompt_tokens", 0),
                            "output": usage_data.get("completion_tokens", 0),
                            "total": usage_data.get("total_tokens", 0)
                        }
                    else:
                        usage_details = {
                            "input": getattr(usage_data, "prompt_tokens", 0),
                            "output": getattr(usage_data, "completion_tokens", 0),
                            "total": getattr(usage_data, "total_tokens", 0)
                        }
                sentiment_trace.update(
                    output=sentiment_data.model_dump(),
                    usage_details=usage_details,
                    tags=["sentiment_score"]
                )

            # Règle Métier : Escalade immédiate si négatif
            if sentiment_data.is_escalation_needed:
                print(f"🚨 [ESCALADE] Sentiment négatif détecté (Score: {sentiment_data.score}). Arrêt de l'IA.")
                return {"status": "escalated", "reason": "negative_sentiment", "score": sentiment_data.score}

           
            # ==========================================
            # ÉTAPE 2 : GÉNÉRATION DE LA RÉPONSE (DeepSeek V4 Pro)
            # ==========================================
            print("💬 [NLP] Sentiment positif/neutre. Génération de la réponse sur-mesure...")
            
            # 1. Récupération des créneaux
            disponibilites_cal = await get_available_slots(3)

            prompt_template = langfuse_client.get_prompt("closer_free_form_guidelines")
            
            # 2. Injection des disponibilités
            system_prompt = prompt_template.compile(
                name=name,
                disponibilites=disponibilites_cal
            )
            messages_pour_llm = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text}
            ]

            with langfuse_client.start_as_current_observation(
                as_type="generation",
                name="free-form-reply-generation",
                model=self.model_quality, 
                prompt=prompt_template,
                input=messages_pour_llm  # <-- Ajout ici
            ) as generation_trace:
                
                response = await litellm.acompletion(
                    model=self.model_quality,
                    messages=messages_pour_llm
                )
                
                raw_generated_text = response.choices[0].message.content
                # 🎯 CORRECTION 2 : Extraction et formatage des tokens
                usage_data = getattr(response, 'usage', None)
                usage_details = {}
                if usage_data:
                    usage_details = {
                        "input": getattr(usage_data, "prompt_tokens", 0),
                        "output": getattr(usage_data, "completion_tokens", 0),
                        "total": getattr(usage_data, "total_tokens", 0)
                    }

               
               # ==========================================
                # ÉTAPE 3 : SÉCURISATION VIA GUARDRAILS AI
                # ==========================================
                try:
                    # Guardrails renvoie un objet ValidationOutcome
                    outcome = self.reply_guard.parse(raw_generated_text)
                    
                    # 🎯 CORRECTION : On extrait le vrai texte de l'objet
                    validated_text = outcome.validated_output
                    
                    generation_trace.update(
                        output={"generated_reply": validated_text, "guardrail_passed": True},
                        usage_details=usage_details, # <-- Ajout ici
                        metadata={"sentiment_score": sentiment_data.score}
                    )
                    
                    return {
                        "status": "success", 
                        "reply": validated_text, 
                        "intention": sentiment_data.intention  # <-- Ajout ici
                    }

                except Exception as e:
                    print(f"❌ [GUARDRAIL] La réponse générée a été bloquée : {e}")
                    generation_trace.update(level="WARNING", status_message="Blocked by Guardrails AI")
                    return {"status": "escalated", "reason": "guardrail_failure"}
    
    @observe(name="[Closer : Sortant] Process and Send Message")
    async def process_and_send_message(self, lead_data: Dict[str, Any], current_step: int, classification: str) -> Dict[str, Any]:
        """
        Logique Sortante : Télécharge le template depuis Langfuse, l'envoie via WhatsApp et met à jour le CRM.
        """
        lead_id = lead_data.get("lead_id", "unknown")
        name = lead_data.get("first_name", "Client")
        numero_client = lead_data.get("phone", "+212600000000")
        
        template_id = f"{classification.lower()}_step_{current_step}"
        
        print(f"\n[CLOSER] Traitement du lead {name} | Statut: {classification.upper()} | Étape: {current_step}")

        with propagate_attributes(
            tags=[lead_id, template_id, "whatsapp", classification, self.model_workhorse, f"step_{current_step}"],
            session_id=lead_id
        ):
            try:
                prompt_template = langfuse_client.get_prompt(template_id)
                message_text = prompt_template.compile(name=name)
            except Exception as e:
                print(f"❌ [CLOSER] Template WhatsApp '{template_id}' introuvable dans Langfuse : {e}")
                return {"status": "error", "reason": "template_not_found"}

            payload_interne = {
                "lead_id": lead_id,
                "classification": classification,
                "step": current_step,
                "message_content": message_text
            }
            
            resultat_envoi = await send_whatsapp_message(numero_client, message_text)
            payload_interne["delivery_status"] = resultat_envoi
            
            if resultat_envoi.get("status") in ["success", "mocked"]:
                crm_result = await update_crm_after_message(
                    lead_id=lead_id,
                    step_sent=current_step,
                    classification=classification
                )
                payload_interne["crm_update_status"] = crm_result
            else:
                print("⚠️ [CLOSER] Échec de l'envoi WhatsApp. Mise à jour du CRM annulée.")
                payload_interne["crm_update_status"] = {"status": "skipped", "reason": "WhatsApp failure"}
            
            return payload_interne
        
    async def analyze_and_reply(self, lead_data: Dict[str, Any], message_text: str) -> Dict[str, Any]:
        """
        Logique Entrante : Analyse les réponses des clients de manière approfondie avec Langfuse SDK.
        """
        name = lead_data.get("first_name", "Client")
        industry = lead_data.get("industry_segment", "Secteur Inconnu")
        numero_client = lead_data.get("phone", "+212600000000")
        lead_id = lead_data.get("lead_id", "unknown")

        print(f"\n🤖 [NLP] Analyse cognitive approfondie de la réponse de {name} via Langfuse SDK...")

        try:
            disponibilites_cal = await get_available_slots(3)

            prompt_template = langfuse_client.get_prompt("closer_objection_handler")
            
            # 2. On injecte la variable 'disponibilites' dans la compilation du prompt
            system_instruction = prompt_template.compile(
                name=name,
                industry=industry,
                message=message_text,
                disponibilites=disponibilites_cal
            )

            user_message = f"Analyse ce message de mon prospect et réponds en respectant les consignes : '{message_text}'"
            with propagate_attributes(
                user_id=lead_id,
                session_id=lead_id,
                tags=[lead_id, "dynamic_objection_handler", "whatsapp", "inbound_reply", self.model_workhorse]
            ):
                with langfuse_client.start_as_current_observation(
                    as_type="generation",
                    name="closer-objection-analysis",
                    model=self.model_workhorse,
                    input=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_message}
                    ],
                    prompt=prompt_template,
                ) as generation:
                    
                    evaluation, raw_response = await self.client.messages.create_with_completion(
                        model=self.model_workhorse,
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": user_message}
                        ],
                        response_model=ObjectionAnalysis,
                        temperature=0.3,
                        max_tokens=250,
                    )

                    usage_data = getattr(raw_response, 'usage', None)
                    input_tokens, output_tokens, total_tokens = 0, 0, 0

                    if usage_data:
                        if isinstance(usage_data, dict):
                            input_tokens = usage_data.get("prompt_tokens", 0)
                            output_tokens = usage_data.get("completion_tokens", 0)
                            total_tokens = usage_data.get("total_tokens", 0)
                        else:
                            input_tokens = getattr(usage_data, "prompt_tokens", 0)
                            output_tokens = getattr(usage_data, "completion_tokens", 0)
                            total_tokens = getattr(usage_data, "total_tokens", 0)

                    update_payload = {"output": evaluation.model_dump()}
                    if total_tokens > 0:
                        update_payload["usage_details"] = {
                            "input": input_tokens,
                            "output": output_tokens,
                            "total": total_tokens
                        }

                    generation.update(**update_payload)

            intention = evaluation.intention
            texte_a_envoyer = evaluation.reponse_generee

            print(f"🎯 [NLP] Intention qualifiée : {intention}")
            print(f"💬 [NLP] Contre-argument généré : '{texte_a_envoyer}'")

            envoi_result = await send_whatsapp_message(numero_client, texte_a_envoyer)
            
            if lead_id != "unknown":
                print(f"💾 [CLOSER] Notification du CRM Keeper...")
                await update_crm_after_message(
                    lead_id=lead_id,
                    step_sent=99,
                    classification="reponse_ia"
                )

            return {
                "intention": intention,
                "reponse_envoyee": texte_a_envoyer,
                "delivery": envoi_result
            }

        except Exception as e:
            print(f"❌ [NLP] Erreur critique lors de l'appel LLM approfondi : {e}")
            return {"intention": "ERREUR", "reponse_envoyee": None, "error": str(e)}