import requests
import os
from datetime import datetime, timezone
from dotenv import load_dotenv  

load_dotenv()

# ==========================================
# TEMPLATES DE SÉQUENCES (Acquisition B2B / Lead Gen)
# ==========================================

# Séquence Nurture MQL (5 messages). Contenu éducatif axé sur les problèmes du prospect.
MQL_SEQUENCE = {
    0: {
        "subject": "Repensez votre stratégie d'acquisition", 
        "body": "Bonjour {nom},\n\nDans votre secteur, le défi majeur est d'attirer des leads qualifiés sans exploser le budget d'acquisition. Voici comment une approche automatisée redéfinit les standards..."
    },
    -1: {
        "subject": "Comment les leaders de votre industrie génèrent des leads", 
        "body": "Bonjour {nom},\n\nSaviez-vous que les entreprises les plus performantes automatisent leur qualification ? Un agent intelligent filtre les prospects instantanément pour ne garder que les opportunités réelles."
    },
    -2: {
        "subject": "Cas d'usage : 3x plus de rendez-vous qualifiés", 
        "body": "Bonjour {nom},\n\nEn déployant notre système, des entreprises similaires ont divisé par deux leur coût d'acquisition. Souhaitez-vous voir comment cette architecture fonctionne concrètement ?"
    },
    -3: {
        "subject": "Le vrai coût des leads non traités", 
        "body": "Bonjour {nom},\n\nOn sous-estime souvent l'impact des leads qui refroidissent par manque de suivi. Notre système prend le relais 24/7. Ça vous dirait d'en voir un aperçu ?"
    },
    -4: {
        "subject": "Prêt à accélérer votre croissance, {nom} ?", 
        "body": "Bonjour {nom},\n\nSi vous êtes prêt à implémenter une véritable machine d'acquisition, c'est le moment. Voici mon calendrier pour en discuter 15 minutes : [Lien Cal.com]"
    }
}

# Séquence Follow-up SQL (3 messages). Plus courts et directs.
SQL_SEQUENCE = {
    0: {
        "subject": "Suite à notre échange sur vos objectifs", 
        "body": "Bonjour {nom},\n\nVous m'aviez mentionné que la qualité de vos leads actuels freinait vos objectifs de vente. Je suis disponible pour un échange rapide de 10 min pour vous montrer notre solution."
    },
    -1: {
        "subject": "{nom}, une idée rapide pour votre pipeline", 
        "body": "Bonjour {nom},\n\nJuste un petit mot pour faire remonter mon précédent email. Notre système peut vraiment faire la différence pour vos commerciaux. Un petit appel jeudi vous conviendrait-il ?"
    },
    -2: {
        "subject": "Je ferme le dossier ?", 
        "body": "Bonjour {nom},\n\nN'ayant pas de nouvelles, j'en déduis que l'optimisation de vos conversions n'est plus une priorité. Faut-il que je mette notre échange en pause pour ne plus encombrer votre boîte mail ?"
    }
}

# ==========================================
# COMMUNICATION AVEC LE CRM KEEPER (Localhost)
# ==========================================

CRM_KEEPER_URL = "http://127.0.0.1:8000"

def fetch_leads_from_crm_keeper():
    """Demande au CRM Keeper de fournir les leads via la route GET /stage/{stage_name}"""
    leads_trouves = []
    
    # On utilise ta route existante pour 'mql' puis pour 'sql'
    etapes_a_chercher = ["mql", "sql"]
    
    for etape in etapes_a_chercher:
        url = f"{CRM_KEEPER_URL}/crm/leads/stage/{etape}"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                # On ajoute les leads trouvés à notre grande liste
                leads_trouves.extend(response.json())
            else:
                print(f"⚠️ Erreur du CRM Keeper lors de la recherche de l'étape '{etape}' : {response.text}")
        except requests.exceptions.ConnectionError:
            print("❌ Impossible de contacter le CRM Keeper. Est-il bien lancé sur le port 8000 ?")
            return [] # On arrête tout si le serveur est éteint
            
    return leads_trouves

def update_lead_via_crm_keeper(lead_id: str, new_messages_sent: int, action_text: str):
    """Envoie la demande de mise à jour au CRM Keeper avec un entier (Number)."""
    url = f"{CRM_KEEPER_URL}/crm/update"
    
    crm_payload = {
        "lead_id": lead_id,
        "updates": {
            "messages_sent": new_messages_sent,  # Format Int/Number exigé par HubSpot
            "last_action": action_text,
            "last_action_at":datetime.now(timezone.utc).isoformat()
        }
    }
    
    response = requests.post(url, json=crm_payload)
    if response.status_code == 200:
        print(f"✅ CRM Keeper a mis à jour le lead {lead_id} | action: {action_text}")
    else:
        print(f"❌ Rejet par le CRM Keeper pour le lead {lead_id} : {response.text}")



def send_sequence_email(email: str, subject: str, body: str):
    """Envoie un e-mail professionnel via l'API REST de Brevo."""
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("SENDER_EMAIL", "hamzabouazza55@gmail.com")
    
    if not api_key:
        print("⚠️ Clé API Brevo introuvable. Simulation de l'envoi.")
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
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code in [201, 202]:
            print(f"✅ VRAI EMAIL EXPÉDIÉ VIA BREVO À : {email} | Objet : {subject}")
            return True
        else:
            print(f"❌ Rejet par l'API Brevo : {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Échec de la connexion à l'API Brevo : {e}")
        return False

# ==========================================
# MOTEUR PRINCIPAL D'EXÉCUTION
# ==========================================

def execute_pull_sequences():
    print("🚀 Début du balayage des séquences via le CRM Keeper...")
    leads = fetch_leads_from_crm_keeper()
    
    if not leads:
        print("ℹ️ Aucun lead trouvé ou erreur de connexion.")
        return
        
    for lead in leads:
        lead_id = lead.get("lead_id")
        nom = lead.get("first_name", "Client")
        email = lead.get("email")
        
        # 1. Nettoyage du statut brut reçu par HubSpot
        raw_status = str(lead.get("lead_stage")).upper().strip()
        
        # 2. Traduction intelligente du statut
        if "MQL" in raw_status or "MARKETING" in raw_status:
            status = "MQL"
        elif "SQL" in raw_status or "SALES" in raw_status:
            status = "SQL"
        else:
            status = raw_status
        
        # 3. Récupération sécurisée du compteur
        msg_val = lead.get("messages_sent")
        messages_sent = int(msg_val) if msg_val is not None and str(msg_val).strip() != "" else 0
        
        # 4. CALCUL DU DÉLAI DEPUIS LE DERNIER EMAIL
        last_action_at_str = lead.get("last_action_at")
        jours_ecoules = 999  # Par défaut, un grand nombre si c'est le 1er e-mail
        
        if last_action_at_str and messages_sent < 0:
            try:
                # On enlève la répétition datetime.datetime
                last_date = datetime.fromisoformat(last_action_at_str.replace('Z', '+00:00'))
                maintenant = datetime.now(timezone.utc)
                jours_ecoules = (maintenant - last_date).days
            except ValueError:
                print(f"⚠️ Impossible de lire la date pour {nom}. On autorise l'envoi.")

        print(f"👉 Analyse: {nom} | Statut: {status} | Etape: {messages_sent} | Jours écoulés: {jours_ecoules}")

       # --- LOGIQUE MQL (5 messages, 1 tous les 4 jours) ---
        if status == "MQL":
            # 1. LA SÉQUENCE CLASSIQUE (De 0 à -4)
            if messages_sent > -5:
                if messages_sent == 0 or jours_ecoules >= 4:
                    template = MQL_SEQUENCE.get(messages_sent)
                    if template:
                        # Envoi de l'e-mail via Brevo
                        send_sequence_email(email, template["subject"], template["body"].format(nom=nom))
                        # Mise à jour dans le CRM Keeper
                        nouveau_compteur = messages_sent - 1
                        etape = abs(messages_sent) + 1
                        update_lead_via_crm_keeper(lead_id, nouveau_compteur, f"Email MQL envoyé (Étape {etape}/5)")
                else:
                    jours_restants = 4 - jours_ecoules
                    print(f"⏳ {nom} (MQL) est en pause Nurturing. Prochain email dans {jours_restants} jour(s).")
            
            # 👇 2. LE NOUVEAU JOB DE RÉ-ENGAGEMENT (7 JOURS) 👇
            elif messages_sent == -5:
                if jours_ecoules >= 7:
                    print(f"🚨 [RÉANIMATION] 7 jours de silence pour {nom} ! Envoi du message de la dernière chance.")
                    
                    sujet = "Toujours d'actualité, {nom} ?"
                    corps = "Bonjour {nom},\n\nN'ayant pas eu de retour de votre part suite à mes précédents messages, je me permets une dernière relance douce.\n\nEst-ce que l'optimisation de vos processus est toujours un sujet d'actualité pour vous en ce moment ?\n\nAu plaisir d'échanger,"
                    
                    # Envoi du message ultime
                    send_sequence_email(email, sujet, corps.format(nom=nom))
                    
                    # On passe le compteur à -6 pour garantir la règle "once" (une seule fois)
                    update_lead_via_crm_keeper(lead_id, -6, "Email de ré-engagement 7 jours envoyé")
                else:
                    jours_restants = 7 - jours_ecoules
                    print(f"⏳ {nom} (MQL) a fini sa séquence. Attente de {jours_restants} jour(s) pour la tentative de ré-engagement.")
            
            # 3. LE CLASSEMENT DÉFINITIF (À -6 ou moins)
            else:
                print(f"💀 {nom} (MQL) a déjà reçu le ré-engagement et reste silencieux. Dossier définitivement clos.")

        # --- LOGIQUE SQL (3 messages, 1 tous les 2 jours) ---
        elif status == "SQL":
            if messages_sent > -3:
                # Si c'est le 1er e-mail (0) OU que 2 jours minimum sont passés
                if messages_sent == 0 or jours_ecoules >= 2:
                    template = SQL_SEQUENCE.get(messages_sent)
                    if template:
                        # 1. Envoi de l'e-mail via Brevo
                        send_sequence_email(email, template["subject"], template["body"].format(nom=nom))
                        # 2. Mise à jour dans le CRM Keeper
                        nouveau_compteur = messages_sent - 1
                        etape = abs(messages_sent) + 1
                        update_lead_via_crm_keeper(lead_id, nouveau_compteur, f"Email SQL envoyé (Étape {etape}/3)")
                else:
                    jours_restants = 2 - jours_ecoules
                    print(f"⏳ {nom} (SQL) est en pause Follow-up. Prochain email dans {jours_restants} jour(s).")
            else:
                print(f"⏩ {nom} (SQL) a terminé sa séquence de relance (Compteur final: {messages_sent}).")
if __name__ == "__main__":
    execute_pull_sequences()