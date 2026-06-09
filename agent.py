import os
import json
import re
from typing import Dict, Any
from dotenv import load_dotenv

# Connecteur pour l'architecture LLM compatible OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from tools.whatsapp_tool import send_whatsapp_message
from tools.crm_tool import update_crm_after_message

# Chargement des variables d'environnement (.env)
load_dotenv()

class CloserAgent:
    def __init__(self):
        """
        Initialise l'Agent Closer avec sa logique de séquences de relance
        et son moteur cognitif NLP (Gemma).
        """
        print("🧠 [CLOSER] Initialisation de l'Agent Closer...")

        # 1. Définition des séquences de messages
        self.sequences = {
            "mql": {
                1: "Bonjour {name}, j'ai bien reçu votre demande concernant notre solution. Seriez-vous disponible pour un court échange cette semaine ?",
                2: "Bonjour {name}, je me permets de vous relancer suite à mon message d'hier. Avez-vous pu y jeter un œil ?",
                3: "Hello {name}, sans retour de votre part, je suppose que le moment est mal choisi. Je classe votre dossier pour l'instant."
            },
            "sql": {
                1: "Bonjour {name}, suite à votre demande, je vous propose d'en discuter de vive voix. Quel serait le meilleur moment ?",
                2: "Bonjour {name}, les places pour nos sessions se remplissent vite. Souhaitez-vous bloquer un créneau ?"
            }
        }

        # 2. Configuration du Cerveau LLM distant
        print(f"🤖 [CLOSER] Connexion au modèle {os.getenv('LLM_MODEL_NAME', 'Gemma')}...")
        self.llm = ChatOpenAI(
            base_url=os.getenv("LLM_BASE_URL"),
            api_key=os.getenv("LLM_API_KEY"),
            model=os.getenv("LLM_MODEL_NAME"),
            temperature=0.3,
            max_tokens=250
        )
        
        self.parser = JsonOutputParser()
        # 3. Prompt de qualification des réponses clients
        self.objection_prompt = PromptTemplate(
            input_variables=["name", "industry", "message"],
            partial_variables={"format_instructions": self.parser.get_format_instructions()},
            template="""Tu es un Agent Closer expert en automatisation B2B.
            Ton prospect {name} (travaillant dans le secteur : {industry}) a répondu à ton message :
            "{message}"

            Tâche 1 : Analyse l'intention exacte du prospect. Choisis STRICTEMENT parmi ces étiquettes :
            - "PRENDRE_RDV" (Le prospect est très chaud, valide l'offre ou demande à s'appeler)
            - "INTERESSE" (Le prospect veut juste plus d'informations ou pose une question)
            - "OBJECTION_PRIX" 
            - "OBJECTION_TEMPS"
            - "REFUS"

            Tâche 2 : Rédige une réponse courte (1 à 2 phrases maximum), professionnelle, humaine et persuasive pour traiter cette situation. 
            
            🚨 DIRECTIVES ABSOLUES :
            - Si l'intention est "PRENDRE_RDV", tu DOIS obligatoirement amener la prise d'appel et inclure ce lien exact dans ta réponse : https://cal.com/hamza-bouazza-g3drhd/
            - Si c'est un "REFUS", reste extrêmement poli, remercie-le et clos proprement la discussion.
            - N'invente JAMAIS de faux liens.

            {format_instructions}
            Assure-toi que les clés du JSON de sortie soient exactement "intention" et "reponse_generee". Ne génère aucun autre texte.
            """
        )
        print("👁️ [OBSERVABILITÉ] Démarrage du traceur Langfuse...")
        self.langfuse_client = Langfuse()
        self.langfuse_handler = CallbackHandler()

    async def process_and_send_message(self, lead_data: Dict[str, Any], current_step: int, classification: str) -> Dict[str, Any]:
        """
        Logique Sortante : Sélectionne le message, l'envoie via WhatsApp et met à jour le CRM.
        """
        lead_id = lead_data.get("lead_id", "unknown")
        name = lead_data.get("first_name", "Client")
        numero_client = lead_data.get("phone", "+212600000000")
        
        template_id = f"{classification.lower()}_step_{current_step}"
        channel = "whatsapp"
        
        print(f"\n[CLOSER] Traitement du lead {name} | Statut: {classification.upper()} | Étape: {current_step}")

        # 🟢 CRÉATION DE LA TRACE LANGFUSE
        trace = self.langfuse_client.trace(
            name="outbound_sequence_message",
            user_id=lead_id,
            session_id=lead_id,
            # 🎯 Les tags exacts demandés dans le cahier des charges :
            tags=[lead_id, template_id, channel, classification]
        )

        # 1. Récupération du template
        sequence_steps = self.sequences.get(classification.lower())
        if not sequence_steps or current_step not in sequence_steps:
            print(f"❌ [CLOSER] Pas de message trouvé...")
            trace.update(level="ERROR", status_message="Template not found") # On trace l'erreur
            return {"status": "error", "reason": "sequence_step_not_found"}

        # 2. Personnalisation du texte
        message_text = sequence_steps[current_step].format(name=name)
        
        # 🟢 ON ENREGISTRE L'ÉVÉNEMENT DU TEMPLATE
        trace.event(
            name="template_selected", 
            input={"step": current_step, "classification": classification}, 
            output={"final_message": message_text}
        )

        payload_interne = {
            "lead_id": lead_id,
            "classification": classification,
            "step": current_step,
            "message_content": message_text
        }
        
        # ... (la suite de ta fonction avec send_whatsapp_message et update_crm_after_message reste identique) ...

        # 3. Expédition WhatsApp
        resultat_envoi = await send_whatsapp_message(numero_client, message_text)
        payload_interne["delivery_status"] = resultat_envoi
        
        # 4. Synchronisation CRM
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
        Logique Entrante : Analyse les réponses des clients avec Gemma.
        """
        name = lead_data.get("first_name", "Client")
        industry = lead_data.get("industry_segment", "Secteur Inconnu")
        numero_client = lead_data.get("phone", "+212600000000")

        print(f"\n🤖 [NLP] Analyse cognitive de la réponse de {name} via Gemma...")

        try:
            chain = self.objection_prompt | self.llm
            
           # 👇 MODIFICATION DE L'APPEL AINVOKE 👇
            raw_response = await chain.ainvoke(
                {
                    "name": name,
                    "industry": industry,
                    "message": message_text
                },
                config={
                    "callbacks": [self.langfuse_handler],
                    "metadata": {
                        "langfuse_session_id": lead_data.get("lead_id"),
                        "langfuse_user_id": lead_data.get("lead_id"),
                        # 🎯 Les tags pour le traitement des réponses :
                        "langfuse_tags": [
                            lead_data.get("lead_id", "unknown"), 
                            "dynamic_objection_handler", 
                            "whatsapp", 
                            "inbound_reply"
                        ]
                    }
                }
            )
            # 👆 FIN DE LA MODIFICATION 👆

            content = raw_response.content
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            
            if json_match:
                llm_data = json.loads(json_match.group(0))
            else:
                llm_data = {
                    "intention": "INCONNUE", 
                    "reponse_generee": f"Merci pour votre retour {name}. Je prends note de votre message et je reviens vers vous rapidement."
                }

            intention = llm_data.get("intention", "INCONNUE")
            texte_a_envoyer = llm_data.get("reponse_generee")

            print(f"🎯 [NLP] Intention qualifiée : {intention}")
            print(f"💬 [NLP] Contre-argument généré : '{texte_a_envoyer}'")

            envoi_result = await send_whatsapp_message(numero_client, texte_a_envoyer)
            lead_id = lead_data.get("lead_id")
            if lead_id:
                print(f"💾 [CLOSER] Notification du CRM Keeper pour la mise à jour des propriétés...")
                
                # On appelle l'outil CRM pour déclencher la route POST /crm/update
                await update_crm_after_message(
                    lead_id=lead_id,
                    step_sent=99, # 99 indique que c'est une réponse de l'IA (hors séquence)
                    classification=f"reponse_ia"
                )
            else:
                print("⚠️ [CLOSER] Pas de lead_id trouvé, mise à jour CRM ignorée.")
            # 👆-------------------------------------------👆

            return {
                "intention": intention,
                "reponse_envoyee": texte_a_envoyer,
                "delivery": envoi_result
            }

        except Exception as e:
            print(f"❌ [NLP] Erreur critique lors de l'appel à l'API Gemma : {e}")
            return {"intention": "ERREUR", "reponse_envoyee": None, "error": str(e)}