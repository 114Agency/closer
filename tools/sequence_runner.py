import httpx
from datetime import datetime, timezone
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from dotenv import load_dotenv
load_dotenv()

from langfuse import Langfuse
from langfuse import observe, propagate_attributes

# Initialisation du client Langfuse pour les tâches en arrière-plan
langfuse_client = Langfuse()


# ==========================================
# COMMUNICATION AVEC LE CRM KEEPER & BREVO
# ==========================================
@observe(name="[Closer ] Fetch Leads from CRM Keeper")
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def fetch_leads_from_crm_keeper():
    """Demande au CRM Keeper de fournir les leads via la route GET /stage/{stage_name}"""
    leads_trouves = []
    etapes_a_chercher = ["mql", "sql"]
    with propagate_attributes(
        tags=["cron", "sequence_runner", "fetch_leads", "closer"],  
    ):
    
        try:
            with httpx.Client(timeout=10.0) as client:
                for etape in etapes_a_chercher:
                    url = f"{settings.urls.crm_keeper}/crm/leads/stage/{etape}"
                    response = client.get(url)
                    response.raise_for_status()
                    leads_trouves.extend(response.json())
            return leads_trouves
        except Exception as e:
            print(f"❌ Impossible de contacter le CRM Keeper après 3 tentatives : {e}")
            return []

@observe(name="[Closer ] Update Lead via CRM Keeper")
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def update_lead_via_crm_keeper(lead_id: str, new_messages_sent: int, action_text: str):
    """Envoie la demande de mise à jour au CRM Keeper avec un entier (Number)."""

    with propagate_attributes(
        tags=["cron", "sequence_runner", "update_lead", "closer"],
    ):
     url = f"{settings.urls.crm_keeper}/crm/update"
    
    crm_payload = {
        "lead_id": lead_id,
        "updates": {
            "messages_sent": new_messages_sent,
            "last_action": action_text,
            "last_action_at": datetime.now(timezone.utc).isoformat()
        }
    }
    
    with httpx.Client(timeout=10.0) as client:
        response = client.post(url, json=crm_payload)
        response.raise_for_status()
        print(f"✅ CRM Keeper a mis à jour le lead {lead_id} | action: {action_text}")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def send_sequence_email(email: str, subject: str, body: str):
    """Envoie un e-mail professionnel via l'API REST de Brevo."""
    api_key = settings.api_keys.brevo
    sender_email = settings.email.sender
    
    if not api_key:
        print("⚠️ Clé API Brevo introuvable dans settings.toml. Simulation de l'envoi.")
        print(f"📧 [SIMULATION] Envoi à {email} | Objet: {subject}")
        return True

    url = "https://api.brevo.com/v3/smtp/email"
    
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    
    payload = {
        "sender": {"name": "Agent Closer", "email": sender_email},
        "to": [{"email": email}],
        "subject": subject,
        "textContent": body
    }
    
    with httpx.Client(timeout=10.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"✅ VRAI EMAIL EXPÉDIÉ VIA BREVO À : {email} | Objet : {subject}")
        return True

# ==========================================
# UTILITAIRE LANGFUSE POUR LES EMAILS
# ==========================================

def fetch_email_template_from_langfuse(template_name: str, nom_prospect: str) -> dict:
    """Récupère le corps et l'objet de l'e-mail depuis Langfuse."""
    try:
        prompt_obj = langfuse_client.get_prompt(template_name)
        # Compilation du corps du texte (avec la variable {{nom}})
        corps = prompt_obj.compile(nom=nom_prospect)
        
        # Récupération de l'objet (subject) stocké dans la configuration JSON de Langfuse
        sujet = prompt_obj.config.get("subject", "Mise à jour concernant votre dossier")
        
        return {"subject": sujet, "body": corps}
    except Exception as e:
        print(f"❌ [ERREUR LANGFUSE] Template {template_name} manquant ou non promu en production : {e}")
        return None

# ==========================================
# MOTEUR PRINCIPAL D'EXÉCUTION
# ==========================================
@observe(name="[CRON] Email Sequence Runner", as_type="generation")
def execute_pull_sequences():
    print("🚀 Début du balayage des séquences via le CRM Keeper...")
    
    # Création d'un ID de session unique pour cette exécution CRON
    cron_session_id = f"cron_run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    # 1. Propagation des attributs (Tags & Session)
    with propagate_attributes(
        session_id=cron_session_id,
        tags=["cron", "email_automation", "brevo", "sequence_runner"]
    ):
        # 2. Observation Langfuse du script (Type: span)
        with langfuse_client.start_as_current_observation(
            as_type="span",
            name="cron-email-sequence-runner",
        ) as observation:
            
            leads = fetch_leads_from_crm_keeper()
            
            if not leads:
                print("ℹ️ Aucun lead trouvé ou erreur de connexion.")
                observation.update(output={"status": "no_leads_found"})
                return
                
            leads_traites = 0
            emails_envoyes = 0

            for lead in leads:
                leads_traites += 1
                lead_id = lead.get("lead_id")
                nom = lead.get("first_name", "Client")
                email = lead.get("email")
                
                raw_status = str(lead.get("lead_stage")).upper().strip()
                
                if "MQL" in raw_status or "MARKETING" in raw_status:
                    status = "MQL"
                elif "SQL" in raw_status or "SALES" in raw_status:
                    status = "SQL"
                else:
                    status = raw_status
                
                msg_val = lead.get("messages_sent")
                messages_sent = int(msg_val) if msg_val is not None and str(msg_val).strip() != "" else 0
                
                last_action_at_str = lead.get("last_action_at")
                jours_ecoules = 999  
                
                if last_action_at_str and messages_sent < 0:
                    try:
                        last_date = datetime.fromisoformat(last_action_at_str.replace('Z', '+00:00'))
                        maintenant = datetime.now(timezone.utc)
                        jours_ecoules = (maintenant - last_date).days
                    except ValueError:
                        print(f"⚠️ Impossible de lire la date pour {nom}.")

                print(f"👉 Analyse: {nom} | Statut: {status} | Etape: {messages_sent} | Jours écoulés: {jours_ecoules}")

                # --- LOGIQUE MQL ---
                if status == "MQL":
                    if messages_sent > -5:
                        if messages_sent == 0 or jours_ecoules >= 5:
                            etape = abs(messages_sent) + 1
                            nom_template = f"email_mql_step_{etape}"
                            
                            template = fetch_email_template_from_langfuse(nom_template, nom)
                            
                            if template:
                                send_sequence_email(email, template["subject"], template["body"])
                                emails_envoyes += 1
                                nouveau_compteur = messages_sent - 1
                                update_lead_via_crm_keeper(lead_id, nouveau_compteur, f"Email MQL envoyé (Étape {etape}/5)")
                    
                    elif messages_sent == -5:
                        if jours_ecoules >= 7:
                            template = fetch_email_template_from_langfuse("email_mql_reengagement", nom)
                            if template:
                                send_sequence_email(email, template["subject"], template["body"])
                                emails_envoyes += 1
                                update_lead_via_crm_keeper(lead_id, -6, "Email de ré-engagement 7 jours envoyé")

                # --- LOGIQUE SQL ---
                elif status == "SQL":
                    if messages_sent > -3:
                        if messages_sent == 0 or jours_ecoules >= 2:
                            etape = abs(messages_sent) + 1
                            nom_template = f"email_sql_step_{etape}"
                            
                            template = fetch_email_template_from_langfuse(nom_template, nom)
                            
                            if template:
                                send_sequence_email(email, template["subject"], template["body"])
                                emails_envoyes += 1
                                nouveau_compteur = messages_sent - 1
                                update_lead_via_crm_keeper(lead_id, nouveau_compteur, f"Email SQL envoyé (Étape {etape}/3)")

            # 3. Mise à jour de l'observation à la fin du traitement
            observation.update(
                output={
                    "status": "success",
                    "leads_scannes": leads_traites,
                    "emails_expedies": emails_envoyes
                }
            )
            
    # 4. Assurer l'envoi des logs vers le serveur Langfuse
    langfuse_client.flush()
if __name__ == "__main__":
    execute_pull_sequences()