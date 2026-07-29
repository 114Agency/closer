import requests
from config import settings # Import de l'objet Dynaconf

# Dynaconf te renvoie directement la valeur secrète lue dans le .env !
api_key = settings.api_keys.d360
url_api = settings.urls.d360_webhook_setup
webhook_url = settings.webhook.closer_url

headers = {
    "D360-API-KEY": api_key,
    "Content-Type": "application/json"
}

payload = {
    "url": webhook_url
}

print(f"📡 Configuration du Webhook en cours...")
response = requests.post(url_api, headers=headers, json=payload)
print(f"Code HTTP : {response.status_code}")