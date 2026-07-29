# tools/whatsapp_tool.py
import httpx
from typing import Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential

# 🎯 Configuration centralisée
from config import settings

# 🛡️ Sous-fonction réseau protégée par Tenacity
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def _post_whatsapp_with_retry(url: str, headers: dict, payload: dict):
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response


async def send_whatsapp_message(phone_number: str, message_text: str) -> Dict[str, Any]:
    """
    Envoie un message RÉEL via WhatsApp Business API (fournisseur 360dialog).
    """
    # 1. Utilisation de Dynaconf (Sécurisé)
    api_key = settings.api_keys.get("d360", "")
    base_url = settings.urls.get("whatsapp_base", "https://waba.360dialog.io/v1/messages")
    print(f"🕵️ DEBUG API KEY : '{api_key}'")
    # 2. Mode simulation conservé
    if not api_key:
        print(f"⚠️ [MODE SIMULATION] Clé 360dialog manquante. Envoi virtuel à {phone_number} : '{message_text}'")
        return {"status": "mocked", "message": "Simulation d'envoi"}

    # 3. Préparation des headers
    headers = {
        "D360-API-KEY": api_key,
        "Content-Type": "application/json"
    }

    # 4. Formatage du payload
    numero_propre = phone_number.replace("+", "") 
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": numero_propre,
        "type": "text",
        "text": {
            "body": message_text
        }
    }

    print(f"🚀 [WHATSAPP 360dialog] Tentative d'envoi RÉEL vers {numero_propre}...")

    try:
        # 5. Envoi avec filet de sécurité Tenacity
        response = await _post_whatsapp_with_retry(base_url, headers, payload)
        print("✅ [WHATSAPP] Message distribué sur le téléphone avec succès via 360dialog !")
        return {"status": "success", "meta_response": response.json()}
            
    except httpx.HTTPStatusError as e:
        erreur_360 = e.response.text
        print(f"❌ [WHATSAPP API] 360dialog a refusé l'envoi (Code {e.response.status_code}) : {erreur_360}")
        return {"status": "error", "details": erreur_360}
    except Exception as e:
        print(f"❌ [WHATSAPP] Erreur réseau inattendue avec 360dialog après relances : {e}")
        return {"status": "error", "details": str(e)}