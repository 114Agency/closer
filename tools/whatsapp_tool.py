import os
import httpx
from typing import Dict, Any
from dotenv import load_dotenv

# Charge les variables d'environnement
load_dotenv()

async def send_whatsapp_message(phone_number: str, message_text: str) -> Dict[str, Any]:
    """
    Envoie un message RÉEL via WhatsApp Business API (fournisseur 360dialog).
    """
    # 1. On récupère tes identifiants 360dialog
    api_key = os.getenv("D360_API_KEY")
    # L'URL peut varier légèrement selon ton espace (ex: sandbox), on permet de la surcharger
    base_url = os.getenv("D360_BASE_URL", "https://waba.360dialog.io/v1/messages")

    # 2. Sécurité : Si tu n'as pas mis la clé, on reste en mode simulation
    if not api_key:
        print(f"⚠️ [MODE SIMULATION] Clé 360dialog manquante. Envoi virtuel à {phone_number} : '{message_text}'")
        return {"status": "mocked", "message": "Simulation d'envoi"}

    # 3. Préparation des headers (Spécifique à 360dialog)
    headers = {
        "D360-API-KEY": api_key,
        "Content-Type": "application/json"
    }

    # 4. Format exigé par WhatsApp via 360dialog
    numero_propre = phone_number.replace("+", "") # On nettoie le numéro
    
    payload = {
        "messaging_product": "whatsapp",  # 👈 LA LIGNE MAGIQUE EST ICI
        "recipient_type": "individual",
        "to": numero_propre,
        "type": "text",
        "text": {
            "body": message_text
        }
    }

    print(f"🚀 [WHATSAPP 360dialog] Tentative d'envoi RÉEL vers {numero_propre}...")

    try:
        # 5. Envoi de la requête
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(base_url, headers=headers, json=payload)
            
            # Si 360dialog refuse (ex: numéro invalide, template non approuvé)
            if response.status_code not in [200, 201]:
                erreur_360 = response.text
                print(f"❌ [WHATSAPP API] 360dialog a refusé l'envoi : {erreur_360}")
                return {"status": "error", "details": erreur_360}
                
            print("✅ [WHATSAPP] Message distribué sur le téléphone avec succès via 360dialog !")
            return {"status": "success", "meta_response": response.json()}
            
    except Exception as e:
        print(f"❌ [WHATSAPP] Erreur réseau inattendue avec 360dialog : {e}")
        return {"status": "error", "details": str(e)}