# api.py
import os
from fastapi import FastAPI, HTTPException, BackgroundTasks
import httpx
from pydantic import BaseModel
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from tools.sequence_runner import execute_pull_sequences
from tools.crm_tool import update_crm_after_message # 🟢 Ajoute cet import en haut du fichier si ce n'est pas fait !
from tools.crm_tool import get_lead_by_phone
from fastapi import Request # À vérifier tout en haut du fichier
# On importe ton agent Closer mis à jour
from agent import CloserAgent

app = FastAPI(
    title="Closer Agent API - Phase B",
    description="Microservice gérant l'automatisation des séquences d'engagement et l'envoi de messages via WhatsApp."
)

closer_agent = CloserAgent()
# ==========================================
# 0. PLANIFICATEUR DE TÂCHES (CRON)
# ==========================================

scheduler = BackgroundScheduler()

@app.on_event("startup")
def start_scheduler():
    print("\n⏰ [AUTO] Démarrage du planificateur de séquences...")
    # On ajoute la tâche pour qu'elle s'exécute tous les jours à 08h00
    scheduler.add_job(execute_pull_sequences, 'cron', hour=8, minute=0)
    scheduler.start()
    print("✅ [AUTO] Planificateur activé. Le balayage aura lieu tous les jours à 08h00.")

    # --- LA LIGNE DE TEST (S'exécute toutes les minutes) ---
    # scheduler.add_job(execute_pull_sequences, 'interval', minutes=1)
    
    # scheduler.start()
    # print("✅ [AUTO] Planificateur activé en MODE TEST (Toutes les minutes).")

@app.on_event("shutdown")
def stop_scheduler():
    print("🛑 [AUTO] Arrêt du planificateur...")
    scheduler.shutdown()

# ==========================================
# 1. CONTRATS DE DONNÉES (Pydantic)
# ==========================================

class LeadPayload(BaseModel):
    lead_id: str
    first_name: str
    classification: str          # 'sql', 'mql', ou 'disqualified'
    problem_statement: str       # Le problème identifié par le Qualifier
    industry_segment: str        # 'e_commerce', 'real_estate', etc.
    current_step: int = 1        # L'étape actuelle dans la séquence (ex: 1, 2, 3)
    phone: str = "+212600000000" # Numéro WhatsApp du prospect

class WhatsAppReply(BaseModel):
    lead_id: str
    message_text: str

# ==========================================
# 2. ROUTES HTTP (Endpoints)
# ==========================================

@app.post("/api/v1/closer/trigger")
async def trigger_sequence_step(lead: LeadPayload):
    """
    Route principale appelée par le Commander (ou par une tâche planifiée).
    Prend le lead, génère le bon message de séquence et déclenche l'envoi WhatsApp.
    """
    try:
       # Conversion du modèle Pydantic en dictionnaire Python (Méthode moderne)
        lead_data_dict = lead.model_dump()

        # CORRECTION : On utilise le dictionnaire propre et les attributs
        result = await closer_agent.process_and_send_message(
            lead_data=lead_data_dict,       # 👈 On utilise la variable créée au-dessus !
            current_step=lead.current_step,
            classification=lead.classification
        )
        
        return {"status": "success", "result": result}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# Si ce n'est pas déjà fait en haut de ton fichier api.py, 
# assure-toi d'avoir importé et initialisé ton agent :
# from agent import CloserAgent
# closer_agent = CloserAgent()

async def process_whatsapp_logic(phone_number: str, message_text: str):
    """Fonction exécutée en tâche de fond pour ne pas faire attendre Meta."""
    print(f"⚙️ [BACKGROUND] Début du traitement pour {phone_number}")
    
    # 🔍 RECHERCHE DYNAMIQUE VIA LE CRM KEEPER
    lead_trouve = await get_lead_by_phone(phone_number)
    
    if lead_trouve:
        lead_data = {
            "lead_id": lead_trouve.get("lead_id"),
            "first_name": lead_trouve.get("first_name", "Client"),
            "industry_segment": lead_trouve.get("industry_segment", "Inconnu"),
            "phone": phone_number
        }
    else:
        lead_data = {
            "lead_id": f"inconnu_{phone_number}",
            "first_name": "Client",
            "industry_segment": "Inconnu",
            "phone": phone_number
        }
    
    # 🧠 DÉCLENCHEMENT DE L'IA GEMMA ET ENVOI WHATSAPP
    try:
        await closer_agent.analyze_and_reply(
            lead_data=lead_data,
            message_text=message_text
        )
        print("✅ [BACKGROUND] Traitement terminé avec succès.")
    except Exception as e:
        print(f"❌ [BACKGROUND] Erreur lors du traitement IA : {e}")

@app.post("/whatsapp/incoming")
async def incoming_whatsapp(request: Request, background_tasks: BackgroundTasks):
    """Webhook officiel pour recevoir les messages de 360dialog/Meta."""
    try:
        payload = await request.json()
        
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        
        if "messages" in value:
            message_data = value["messages"][0]
            phone_number = message_data.get("from") 
            message_text = message_data.get("text", {}).get("body", "") 
            
            print(f"📩 [WEBHOOK] Message de {phone_number} reçu. Délégation à l'Agent IA...")
            
            # 🟢 LA MAGIE EST ICI : On envoie le travail lent en arrière-plan
            background_tasks.add_task(process_whatsapp_logic, phone_number, message_text)
            
            # 🟢 On répond TOUT DE SUITE à Meta pour couper son chronomètre !
            return {"status": "success", "message": "Traitement en cours"}
            
        else:
            return {"status": "ignored", "reason": "Accusé de réception"}

    except Exception as e:
        print(f"❌ [WEBHOOK] Erreur de lecture : {e}")
        return {"status": "error", "message": str(e)}
@app.post("/webhook/cal")
async def calcom_webhook(request: Request):
    """
    Écoute les événements envoyés par Cal.com (ex: nouvelle réservation)
    """
    try:
        # On récupère le colis JSON brut envoyé par Cal.com
        payload = await request.json()
        
        # Cal.com envoie différents types d'événements, on filtre pour ne garder que les créations
        trigger_event = payload.get("triggerEvent")
        
        if trigger_event == "BOOKING_CREATED":
            # Extraction des données de réservation
            booking_data = payload.get("payload", {})
            attendee = booking_data.get("attendees", [{}])[0]
            
            # ... (suite du code sous if trigger_event == "BOOKING_CREATED":)
            nom_client = attendee.get("name", "Client")
            email_client = attendee.get("email", "")
            reponses = booking_data.get("responses", {})
            
            date_rdv = booking_data.get("startTime")
            
            # 🟢 Extraction et nettoyage du numéro
            phone_raw = reponses.get("attendeePhoneNumber", {}).get("value", "")
            phone_clean = phone_raw.replace("+", "").replace(" ", "")
            
            print(f"\n🎉 [WEBHOOK CAL.COM] Nouveau RDV pris par {nom_client} !")
            print(f"📅 Date : {date_rdv}")
            print(f"📧 Email : {email_client}")
            print(f"📱 Téléphone propre : {phone_clean}")
            
            # =======================================================
            # 🚀 ACTION CRM : Synchronisation automatique avec HubSpot
            # =======================================================
            crm_search_url = f"http://localhost:8000/crm/search/{phone_clean}"
            crm_update_url = "http://localhost:8000/crm/update"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    # Étape A : Interroger le CRM Keeper pour obtenir le vrai ID numérique HubSpot
                    print(f"🔍 [CRM ACTION] Recherche de l'ID HubSpot pour le numéro {phone_clean}...")
                    search_response = await client.get(crm_search_url)
                    
                    if search_response.status_code == 200:
                        lead_info = search_response.json()
                        vrai_lead_id = lead_info.get("lead_id")
                        print(f"✅ [CRM ACTION] Contact identifié ! ID HubSpot : {vrai_lead_id}")
                    else:
                        vrai_lead_id = phone_clean
                        print(f"⚠️ [CRM ACTION] Contact inconnu dans la base. Utilisation de l'identifiant temporaire : {vrai_lead_id}")
                    
                    # Étape B : Préparer le colis de mise à jour strict conforme à ton schéma Pydantic (LeadUpdate)
                    crm_payload = {
                        "lead_id": vrai_lead_id,
                        "updates": {
                            "lead_stage": "meeting_booked",
                            "meeting_datetime": date_rdv,
                            "last_action": f"📅 RDV programmé via Cal.com"
                        }
                    }
                    
                    # Étape C : Propulser la mise à jour vers le CRM Keeper
                    print(f"📦 [CRM ACTION] Envoi du changement d'étape vers le CRM Keeper...")
                    update_response = await client.post(crm_update_url, json=crm_payload)
                    
                    if update_response.status_code == 200:
                        print("🎯 [CRM ACTION] Alignement HubSpot réussi : Le contact est passé en 'RDV Planifié' (meeting_booked) !")
                    else:
                        print(f"❌ [CRM ACTION] Rejet du colis par le CRM Keeper : {update_response.text}")
                        
                except Exception as net_error:
                    print(f"❌ [CRM ACTION] Échec de la communication réseau avec le CRM Keeper : {net_error}")
            
           
            # =======================================================
            # 💬 ACTION WHATSAPP : Envoi de la confirmation (via 360dialog)
            # =======================================================
            
            d360_base_url = os.getenv("D360_BASE_URL")
            d360_api_key = os.getenv("D360_API_KEY")
            
            whatsapp_url = d360_base_url
            
            message_texte = f"✅ Parfait {nom_client} ! Ton RDV est bien bloqué dans mon agenda pour le {date_rdv}.\n\nJ'ai hâte d'échanger avec toi pour voir comment on peut exploser tes résultats. À très vite ! 🚀"
            
            whatsapp_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": phone_clean,
                "type": "text",
                "text": {"body": message_texte}
            }
            
            headers = {
                "D360-API-KEY": d360_api_key,
                "Content-Type": "application/json"
            }
            
            # 🟢 NOUVEAU : On ouvre un client HTTP spécifiquement pour WhatsApp
            try:
                print(f"💬 [WHATSAPP ACTION] Envoi de la confirmation à {phone_clean}...")
                
                async with httpx.AsyncClient(timeout=10.0) as wa_client:
                    wa_response = await wa_client.post(whatsapp_url, json=whatsapp_payload, headers=headers)
                    
                    if wa_response.status_code in [200, 201, 202]:
                        print("✅ [WHATSAPP ACTION] Message de confirmation distribué au prospect avec succès !")
                    else:
                        print(f"❌ [WHATSAPP ACTION] L'API 360dialog a refusé l'envoi : {wa_response.text}")
                        
            except Exception as e:
                print(f"❌ [WHATSAPP ACTION] Erreur réseau lors de la connexion à 360dialog : {e}")
            return {"status": "success", "message": "Réservation traitée et synchronisée avec le CRM"}
        else:
            print(f"ℹ️ [WEBHOOK CAL.COM] Événement ignoré : {trigger_event}")
            return {"status": "ignored"}

    except Exception as e:
        print(f"❌ [WEBHOOK CAL.COM] Erreur de lecture : {e}")
        return {"status": "error", "message": str(e)}
@app.post("/webhooks/hubspot")
async def hubspot_echo(request: Request):
    """
    Route de courtoisie pour réceptionner les notifications de mise à jour de HubSpot
    et éviter les erreurs 404 dans le terminal.
    """
    try:
        # On lit le colis juste pour vider la mémoire
        payload = await request.json()
        print("🤫 [HUBSPOT WEBHOOK] Écho de mise à jour reçu et ignoré poliment.")
        
        # On répond 200 OK pour que HubSpot arrête d'insister
        return {"status": "success", "message": "Écho reçu"}
    except Exception:
        return {"status": "ok"}
if __name__ == "__main__":
    # Lancement du microservice Closer sur le port dédié 8002
    uvicorn.run("api:app", host="0.0.0.0", port=8002, reload=True)