# tools/crm_tool.py
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

# 🎯 Configuration centralisée
from config import settings

# 🛡️ Sous-fonctions réseau protégées par Tenacity
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def _post_with_retry(url: str, payload: dict):
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def _get_with_retry(url: str):
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response


async def update_crm_after_message(lead_id: str, step_sent: int, classification: str) -> dict:
    """
    Envoie une requête HTTP au microservice CRM Keeper pour mettre à jour l'état du prospect.
    """
    crm_url = f"{settings.urls.crm_keeper}/crm/update"
    
    payload = {
        "lead_id": lead_id,
        "updates": {
            "last_action": f"Message WhatsApp envoyé (Séquence {classification.upper()} - Étape {step_sent})",
            "last_action_at": datetime.now(timezone.utc).isoformat(),
            "messages_sent": step_sent
        }
    }
    
    print(f"💾 [CRM TOOL] Demande de mise à jour envoyée au CRM Keeper pour {lead_id}...")

    try:
        # L'appel utilise la fonction protégée
        response = await _post_with_retry(crm_url, payload)
        print("✅ [CRM TOOL] CRM Keeper a confirmé la mise à jour !")
        return {"status": "success", "crm_response": response.json()}
        
    except httpx.ConnectError:
        print("⚠️ [CRM TOOL] Le serveur CRM Keeper semble éteint (connexion refusée).")
        return {"status": "mocked", "details": "CRM injoignable"}
    except httpx.HTTPStatusError as e:
        print(f"❌ [CRM TOOL] Le CRM Keeper a refusé la requête (Erreur {e.response.status_code}) : {e.response.text}")
        return {"status": "error", "details": e.response.text}
    except Exception as e:
        print(f"❌ [CRM TOOL] Erreur inattendue après relances : {e}")
        return {"status": "error", "details": str(e)}


async def get_lead_by_phone(phone_number: str) -> Optional[dict]:
    """
    Interroge le CRM Keeper pour trouver un lead à partir de son numéro.
    """
    # L'URL de base reste la même
    crm_url = f"{settings.urls.crm_keeper}/crm/search/{phone_number}"
    
    print(f"🔍 [CRM TOOL] Interrogation du CRM Keeper pour le numéro {phone_number}...")
    
    try:
        # 🎯 AJOUT ICI : On passe le paramètre obligatoire exigé par le CRM
        parametres = {"client_id": "client_1"}
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(crm_url, params=parametres)
            response.raise_for_status()
            return response.json() 
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print(f"ℹ️ [CRM TOOL] Aucun lead trouvé pour le numéro {phone_number}.")
            return None
        print(f"❌ [CRM TOOL] Erreur HTTP du CRM Keeper : {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        print(f"❌ [CRM TOOL] Impossible de joindre le CRM Keeper après relances : {e}")
        return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def get_cold_leads(days_inactive: int) -> list:
    """
    Récupère la liste des leads inactifs depuis X jours (via le CRM Keeper).
    """
    # Assure-toi que cette route correspond bien à ce que ton CRM Keeper peut recevoir
    url = f"{settings.urls.crm_keeper}/crm/leads/cold"
    params = {"days": days_inactive}
    
    print(f"🔍 [CRM TOOL] Recherche des leads inactifs depuis {days_inactive} jours...")
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            
            leads_trouves = response.json()
            # Sécurité additionnelle au cas où le CRM renverrait un dictionnaire un jour
            if isinstance(leads_trouves, dict):
                leads_trouves = leads_trouves.get("leads", [])
                
            print(f"✅ [CRM TOOL] {len(leads_trouves)} lead(s) froid(s) trouvé(s) pour la relance.")
            return leads_trouves
            
        except Exception as e:
            print(f"❌ [CRM TOOL] Erreur lors de la récupération des leads froids : {e}")
            return []