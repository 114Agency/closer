# api.py
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
import uvicorn
import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from tenacity import retry, stop_after_attempt, wait_exponential
import json
# 🎯 Imports Langfuse déclaratifs
from langfuse import observe
from langfuse import propagate_attributes

# Imports centralisés aux normes
from config import settings
from tools.sequence_runner import execute_pull_sequences
from tools.crm_tool import get_lead_by_phone
from tools.whatsapp_tool import send_whatsapp_message
from tools.crm_tool import get_cold_leads
from agent import CloserAgent

app = FastAPI(
    title="Closer Agent API - Phase C",
    description="Microservice gérant l'automatisation des séquences d'engagement et l'envoi de messages via WhatsApp."
)

closer_agent = CloserAgent()

# ==========================================
# 0. PLANIFICATEUR DE TÂCHES (CRON)
# ==========================================
@app.get("/test/relance")
async def force_test_relance():
    print("🚀 [TEST] Envoi forcé de la relance froide (Bypass CRM)...")
    
    # On force tes données pour le test
    numero_client = "212603107260"
    nom_client = "Ghofrane"
    
    print(f"🎯 [TEST] Cible verrouillée sur {nom_client}. Envoi en cours...")
    
    message_relance = f"Hello {nom_client}, c'est le test de relance automatique ! 👋\n\nTon projet est toujours d'actualité pour ce trimestre ou tu as mis ça en pause ?"
    
    wa_result = await send_whatsapp_message(numero_client, message_relance)
    
    if wa_result.get("status") in ["success", "mocked"]:
        return {"status": "success", "message": f"Test envoyé avec succès à {numero_client} !"}
        
    return {"status": "failed", "message": "Échec de l'envoi WhatsApp."}
scheduler = BackgroundScheduler()

@app.on_event("startup")
def start_scheduler():
    print("\n⏰ [AUTO] Démarrage du planificateur de séquences...")
    scheduler.add_job(execute_pull_sequences, 'cron', hour=8, minute=0)
    # Exécute la relance des leads froids tous les jours à 10h00
    scheduler.add_job(lambda: asyncio.run(process_cold_leads_reengagement()), 'cron', hour=10, minute=0)
    scheduler.start()
    print("✅ [AUTO] Planificateur activé. Le balayage aura lieu tous les jours à 08h00.")

@app.on_event("shutdown")
def stop_scheduler():
    print("🛑 [AUTO] Arrêt du planificateur...")
    scheduler.shutdown()

# ==========================================
# 1. CONTRATS DE DONNÉES (PYDANTIC)
# ==========================================

class LeadPayload(BaseModel):
    lead_id: str
    first_name: str
    classification: str          
    problem_statement: str       
    industry_segment: str        
    current_step: int = 1        
    phone: str = "+212600000000" 

# ==========================================
# 2. ROUTES HTTP & LOGIQUE LANGFUSE
# ==========================================

@app.post("/api/v1/closer/trigger")
@observe(name="[Closer : Sortant] Séquence Trigger")
async def trigger_sequence_step(lead: LeadPayload):
    """Déclenchement d'une étape de séquence."""
    template_id = f"{lead.classification.lower()}_step_{lead.current_step}"
    
    with propagate_attributes(
        tags=[lead.lead_id, template_id, "whatsapp", lead.classification],
        session_id=lead.lead_id
    ):
        try:
            lead_data_dict = lead.model_dump()
            result = await closer_agent.process_and_send_message(
                lead_data=lead_data_dict,
                current_step=lead.current_step,
                classification=lead.classification
            )
            return {"status": "success", "result": result}
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@observe(name="[Closer : Entrant] Analyse Réponse WhatsApp Phase C")
async def process_whatsapp_logic(phone_number: str, message_text: str):
    """Fonction en tâche de fond pour l'analyse IA de la réponse (Phase C)."""
    print(f"⚙️ [BACKGROUND] Début du traitement Phase C pour {phone_number}")
    
    lead_trouve = await get_lead_by_phone(phone_number)
    
    if lead_trouve:
        lead_id = lead_trouve.get("lead_id")
        lead_data = {
            "lead_id": lead_id,
            "first_name": lead_trouve.get("first_name", "Client"),
            "industry_segment": lead_trouve.get("industry_segment", "Inconnu"),
            "phone": phone_number
        }
    else:
        lead_id = f"inconnu_{phone_number}"
        lead_data = {
            "lead_id": lead_id,
            "first_name": "Client",
            "industry_segment": "Inconnu",
            "phone": phone_number
        }
    
    # 🟢 PROPAGATION : Tous les appels LLM hériteront de ces tags
   # 🟢 PROPAGATION : Tous les appels LLM hériteront de ces tags
    with propagate_attributes(
        tags=[lead_id, "phase_c", "out_of_template", "whatsapp", "inbound_reply"],
        session_id=lead_id
    ):
        try:
            # 1. Appel de la nouvelle logique IA (Sentiment + Génération)
            resultat = await closer_agent.handle_out_of_template_reply(lead_data, message_text)
            
            # 2. Routage selon le statut (Succès vs Escalade)
            if resultat.get("status") == "success":
                texte_a_envoyer = resultat.get("reply")
                intention_lead = resultat.get("intention", "Message standard") # On récupère l'intention
                
                print(f"✅ [WHATSAPP] Envoi de la réponse générée : {texte_a_envoyer}")
                await send_whatsapp_message(phone_number, texte_a_envoyer)
                
                # 🎯 NOUVEAU : Synchronisation avec HubSpot avec l'intention exacte
                if not str(lead_id).startswith("inconnu_"):
                    try:
                        action_text = f"🤖 IA (Intention : {intention_lead})"
                        await update_crm_custom_action(lead_id, action_text)
                        print(f"💾 [CRM] Action synchronisée dans HubSpot avec l'intention : {intention_lead}.")
                    except Exception as e:
                        print(f"❌ [CRM] Échec de la synchronisation : {e}")
                
            elif resultat.get("status") == "escalated":
                raison = resultat.get("reason")
                print(f"🚨 [WHATSAPP] Escalade déclenchée (Raison: {raison}). Envoi d'un message de repli.")
                
                texte_escalade = "Je comprends. Je transmets immédiatement votre message à un conseiller qui va vous recontacter d'ici peu."
                await send_whatsapp_message(phone_number, texte_escalade)
                
                # 🎯 NOUVEAU : Tracer l'escalade dans HubSpot
                if not str(lead_id).startswith("inconnu_"):
                    try:
                        await update_crm_custom_action(lead_id, f"🚨 Escalade vers l'humain ({raison})")
                        print("💾 [CRM] Action 'Escalade' synchronisée dans HubSpot.")
                    except Exception as e:
                        pass
                
            else:
                print("❌ [WHATSAPP] Erreur inconnue lors du traitement.")
                
            print("✅ [BACKGROUND] Traitement terminé avec succès.")
            
        except Exception as e:
            print(f"❌ [BACKGROUND] Erreur lors du traitement IA : {e}")

@app.post("/whatsapp/incoming")
async def incoming_whatsapp(request: Request, background_tasks: BackgroundTasks):
    """Webhook officiel 360dialog/Meta."""
    try:
        raw_body = await request.body()
        
        if not raw_body:
            print("⚠️ [WEBHOOK] Requête reçue mais le corps est vide (Ping/Vérification). Ignorée.")
            return {"status": "ignored", "reason": "empty_body"}

        payload = await request.json()
        
        entry = payload.get("entry", [])
        if not entry:
            return {"status": "ignored", "reason": "no_entry_found"}
            
        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "ignored", "reason": "no_changes_found"}
            
        value = changes[0].get("value", {})
        
        if "messages" in value:
            message_data = value["messages"][0]
            phone_number = message_data.get("from") 
            message_text = message_data.get("text", {}).get("body", "") 
            
            print(f"📩 [WEBHOOK] Message de {phone_number} reçu. Délégation à l'Agent IA Phase C...")
            
            background_tasks.add_task(process_whatsapp_logic, phone_number, message_text)
            return {"status": "success", "message": "Traitement en cours"}
            
        elif "statuses" in value:
            status = value["statuses"][0].get("status")
            print(f"ℹ️ [WEBHOOK] Accusé de réception Meta : statut '{status}'")
            return {"status": "ignored", "reason": "status_update"}
            
        else:
            return {"status": "ignored", "reason": "unhandled_webhook_type"}

    except Exception as e:
        print(f"❌ [WEBHOOK] Erreur de lecture : {e}")
        if 'raw_body' in locals():
            print(f"📦 Contenu brut posant problème : {raw_body.decode('utf-8', errors='ignore')}")
        return {"status": "error", "message": str(e)}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def update_crm_meeting_booked(lead_id: str, date_rdv: str):
    url = f"{settings.urls.crm_keeper}/crm/update"
    crm_payload = {
        "lead_id": lead_id,
        "updates": {
            "lead_stage": "meeting_booked",
            "meeting_datetime": date_rdv,
            "last_action": "📅 RDV programmé via Cal.com"
        }
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=crm_payload)
        response.raise_for_status()
        return response.json()
    
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def update_crm_custom_action(lead_id: str, action_text: str):
    """Met à jour le champ last_action dans le CRM Keeper."""
    url = f"{settings.urls.crm_keeper}/crm/update"
    crm_payload = {
        "lead_id": lead_id,
        "updates": {
            "last_action": action_text
        }
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=crm_payload)
        response.raise_for_status()
        return response.json()
    
@app.post("/webhook/cal")
@observe(name="[Closer : Webhook] Événements Cal.com")
async def calcom_webhook(request: Request):
    """Webhook Cal.com avec traçage contextuel (Création + Fin de RDV)."""
    try:
        payload = await request.json()
        trigger_event = payload.get("triggerEvent")
        
        # ==========================================
        # SCÉNARIO 1 : LE LEAD PREND RENDEZ-VOUS
        # ==========================================
        if trigger_event == "BOOKING_CREATED":
            booking_data = payload.get("payload", {})
            attendee = booking_data.get("attendees", [{}])[0]
            
            nom_client = attendee.get("name", "Client")
            date_rdv = booking_data.get("startTime")
            phone_raw = booking_data.get("responses", {}).get("attendeePhoneNumber", {}).get("value", "")
            phone_clean = phone_raw.replace("+", "").replace(" ", "")
            
            lead_trouve = await get_lead_by_phone(phone_clean)
            vrai_lead_id = lead_trouve.get("lead_id") if lead_trouve else phone_clean
            
            try:
                await update_crm_meeting_booked(vrai_lead_id, date_rdv)
            except Exception as net_error:
                print(f"❌ [CRM ACTION] Échec de la communication avec le CRM Keeper : {net_error}")
            
            message_texte = f"✅ Parfait {nom_client} ! Ton RDV est bien bloqué dans mon agenda pour le {date_rdv}.\n\nJ'ai hâte d'échanger avec toi pour voir comment on peut exploser tes résultats. À très vite ! 🚀"
            
            with propagate_attributes(
                tags=[vrai_lead_id, "rdv_confirmation", "whatsapp", "meeting_booked"],
                session_id=vrai_lead_id
            ):
                wa_result = await send_whatsapp_message(phone_clean, message_texte)
                
                if wa_result.get("status") in ["success", "mocked"]:
                    print("✅ [WHATSAPP ACTION] Message de confirmation distribué !")
                
            return {"status": "success", "message": "Réservation traitée et synchronisée avec le CRM"}

       # ==========================================
        # SCÉNARIO 2 : LE RENDEZ-VOUS EST TERMINÉ (PHASE C)
        # ==========================================
        elif trigger_event == "MEETING_ENDED":
            # On lit directement à la racine, pas besoin de chercher un objet "payload"
            attendee = payload.get("attendees", [{}])[0]
            
            # Extraction du nom
            nom_client = attendee.get("name", "Client")
            
            # Extraction du numéro (on le prend dans attendee, ou sinon dans responses)
            phone_raw = attendee.get("phoneNumber")
            if not phone_raw:
                phone_raw = payload.get("responses", {}).get("attendeePhoneNumber", {}).get("value", "")
                
            phone_clean = phone_raw.replace("+", "").replace(" ", "") if phone_raw else ""
            
            lead_trouve = await get_lead_by_phone(phone_clean)
            vrai_lead_id = lead_trouve.get("lead_id") if lead_trouve else phone_clean
            
            print(f"🏁 [WEBHOOK CAL.COM] Réunion terminée avec {nom_client} ({phone_clean}). Déclenchement du suivi post-meeting...")

            if not phone_clean:
                print("❌ [WEBHOOK CAL.COM] Impossible de trouver le numéro de téléphone. Envoi annulé.")
                return {"status": "error", "reason": "missing_phone"}

            # Le message de suivi standard 
            message_suivi = f"Merci pour notre échange {nom_client} ! C'était un plaisir d'en savoir plus sur tes objectifs.\n\nComme convenu, je t'envoie très vite les prochains éléments. Si tu as la moindre question d'ici là, n'hésite pas à m'écrire directement ici. Excellente fin de journée ! 🚀"
            
            with propagate_attributes(
                tags=[vrai_lead_id, "post_meeting_followup", "whatsapp"],
                session_id=vrai_lead_id
            ):
                wa_result = await send_whatsapp_message(phone_clean, message_suivi)
                
                if wa_result.get("status") in ["success", "mocked"]:
                    print("✅ [WHATSAPP ACTION] Message de suivi post-meeting distribué !")
                    
                    try:
                        await update_crm_custom_action(vrai_lead_id, "🤝 Message de suivi post-démonstration envoyé")
                    except Exception as e:
                        print(f"❌ [CRM] Échec de la mise à jour du suivi : {e}")

            return {"status": "success", "message": "Suivi post-meeting envoyé."}
        else:
            # On ignore poliment les autres événements (annulation, report, etc. pour l'instant)
            return {"status": "ignored"}

    except Exception as e:
        print(f"❌ [WEBHOOK CAL.COM] Erreur de lecture : {e}")
        return {"status": "error", "message": str(e)}

# Assure-toi d'importer ta nouvelle fonction tout en haut de api.py


@observe(name="[Audit] System - Relance Automatique Leads Froids")
async def process_cold_leads_reengagement():
    print("⏰ [CRON] Début du balayage pour les leads inactifs (30 et 60 jours)...")
    
    # 1. On récupère les leads inactifs depuis 30 jours
    leads_30_jours = await get_cold_leads(30)
    
    for lead in leads_30_jours:
        lead_id = lead.get("lead_id")
        nom_client = lead.get("first_name", "Client")
        numero_client = lead.get("phone")
        
        if not numero_client:
            continue
            
        print(f"♻️ [RELANCE] Préparation du message pour {nom_client}...")
        
        # Le message de réactivation très naturel
        message_relance = f"Hello {nom_client}, j'espère que tu vas bien depuis notre dernier échange ! 👋\n\nJe faisais un peu de tri dans mes dossiers et je repensais à ton projet. C'est toujours d'actualité pour ce trimestre ou tu as mis ça en pause pour le moment ?"
        
        with propagate_attributes(tags=[lead_id, "reengagement_30d", "whatsapp"], session_id=lead_id):
            wa_result = await send_whatsapp_message(numero_client, message_relance)
            
            if wa_result.get("status") in ["success", "mocked"]:
                print(f"✅ [WHATSAPP] Relance envoyée à {nom_client}.")
                
                # On met à jour le CRM pour réinitialiser le compteur d'inactivité
                try:
                    await update_crm_custom_action(lead_id, "♻️ Lead relancé après 30 jours d'inactivité")
                except Exception as e:
                    print(f"❌ [CRM] Échec de la mise à jour : {e}")    

@app.post("/webhooks/hubspot")
async def hubspot_echo(request: Request):
    """Route de courtoisie pour HubSpot."""
    try:
        await request.json()
        return {"status": "success", "message": "Écho reçu"}
    except Exception:
        return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8002, reload=True)