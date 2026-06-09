# tools/crm_tool.py
import httpx
import os
from datetime import datetime
from typing import Dict, Any
import httpx
from datetime import datetime

async def update_crm_after_message(lead_id: str, step_sent: int, classification: str) -> dict:
    """
    Envoie une requête HTTP au microservice CRM Keeper pour mettre à jour l'état du prospect.
    """
    crm_url = "http://localhost:8000/crm/update"
    
    payload = {
        "lead_id": lead_id,
        "updates": {
            "last_action": f"Message WhatsApp envoyé (Séquence {classification.upper()} - Étape {step_sent})",
            "last_action_at": datetime.now().isoformat(),
            "messages_sent": step_sent
        }
    }
    
    print(f"🚀 [DEBUG CLOSER] Le Closer s'apprête à envoyer : {payload}")
    
    print(f"💾 [CRM TOOL] Demande de mise à jour envoyée au CRM Keeper pour {lead_id}...")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(crm_url, json=payload)
            response.raise_for_status()
            print("✅ [CRM TOOL] CRM Keeper a confirmé la mise à jour !")
            return {"status": "success", "crm_response": response.json()}
            
    except httpx.ConnectError:
        print("⚠️ [CRM TOOL] Le serveur CRM Keeper semble éteint (connexion refusée).")
        return {"status": "mocked", "details": "CRM injoignable"}
    except httpx.HTTPStatusError as e:
        print(f"❌ [CRM TOOL] Le CRM Keeper a refusé la requête (Erreur {e.response.status_code}) : {e.response.text}")
        return {"status": "error", "details": e.response.text}
    except Exception as e:
        print(f"❌ [CRM TOOL] Erreur inattendue : {e}")
        return {"status": "error", "details": str(e)}




async def get_lead_by_phone(phone_number: str) -> dict:
    """
    Interroge le CRM Keeper pour trouver un lead à partir de son numéro.
    """
    # L'adresse de ton CRM Keeper (Port 8000)
    crm_url = f"http://localhost:8000/crm/search/{phone_number}"
    
    print(f"🔍 [CRM TOOL] Interrogation du CRM Keeper pour le numéro {phone_number}...")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(crm_url, timeout=5.0)
            
            if response.status_code == 200:
                # Le CRM Keeper a trouvé le lead dans HubSpot !
                return response.json() 
            else:
                # Code 404 (Non trouvé) ou autre
                return None
                
    except Exception as e:
        print(f"❌ [CRM TOOL] Impossible de joindre le CRM Keeper : {e}")
        return None