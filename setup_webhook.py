import requests

# 1. Remplace par ta vraie clé 360dialog Sandbox
api_key = "170S58NXD1HDE0XHYIWG6GSGWJG3RQV5" 

# 2. Remplace par ton adresse ngrok exacte (sans oublier /whatsapp/incoming à la fin !)
# ngrok_url = "https://outfield-pronounce-handheld.ngrok-free.dev/whatsapp/incoming" 
# 👇 Fini ngrok, on met l'adresse directe du VPS 👇
ngrok_url = "http://vpshosted.ddnsfree.com:8002/whatsapp/incoming"

url = "https://waba-sandbox.360dialog.io/v1/configs/webhook"

headers = {
    "D360-API-KEY": api_key,
    "Content-Type": "application/json"
}

payload = {
    "url": ngrok_url
}

print("Configuration du Webhook en cours...")
response = requests.post(url, headers=headers, json=payload)

print(f"Code HTTP : {response.status_code}")
print(f"Réponse API : {response.text}")