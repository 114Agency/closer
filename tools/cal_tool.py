import httpx
from datetime import datetime, timedelta, timezone
from config import settings


# Récupération dynamique depuis settings.toml
CAL_API_KEY = settings.api_keys.get("cal_com") 
EVENT_TYPE_ID = settings.cal_com.get("event_type_id")
CAL_API_URL = settings.cal_com.get("api_url_slots", "https://api.cal.com/v2/slots/available") # Avec valeur par défaut de sécurité


async def get_available_slots(days_ahead: int = 3) -> str:
    # ... la suite du code reste exactement identique ...
    
    # Au lieu d'utiliser une URL en dur, tu utilises la variable :
    url = CAL_API_URL 
    
    # ...
     # Utilisation du fuseau horaire UTC pour l'API
    start_date = datetime.now(timezone.utc)
    end_date = start_date + timedelta(days=days_ahead)
    
    
    # Format ISO 8601 strict exigé par la V2
    params = {
        "eventTypeId": EVENT_TYPE_ID,
        "startTime": start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endTime": end_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    
    # L'authentification se fait désormais dans les Headers (Bearer Token)
    headers = {
        "Authorization": f"Bearer {CAL_API_KEY}",
        "Content-Type": "application/json"
    }

    print(f"🗓️ [CAL TOOL] Recherche via API V2 du {start_date.strftime('%d/%m')} au {end_date.strftime('%d/%m')}...")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # ---- PARSING INTELLIGENT (Anti-changement d'API) ----
            # Cal.com modifie parfois la structure de ses réponses.
            # Cette fonction récursive extrait les heures où qu'elles soient cachées.
            available_slots = {}
            
            def find_times(obj):
                if isinstance(obj, dict):
                    # Si on trouve une clé "time" typique de Cal.com
                    if "time" in obj and isinstance(obj["time"], str):
                        time_str = obj["time"]
                        if "T" in time_str:
                            date_part = time_str.split("T")[0]
                            hour_part = time_str.split("T")[1][:5]
                            if date_part not in available_slots:
                                available_slots[date_part] = set()
                            available_slots[date_part].add(hour_part)
                    
                    # On continue de fouiller l'objet
                    for v in obj.values():
                        find_times(v)
                elif isinstance(obj, list):
                    for item in obj:
                        find_times(item)

            # Lancement de la fouille dans le JSON
            find_times(data)
            
            if not available_slots:
                return "Aucun créneau disponible pour les prochains jours."

            # Formatage pour l'IA
            formatted_slots = []
            for date in sorted(available_slots.keys()):
                times = sorted(list(available_slots[date]))
                formatted_slots.append(f"- Le {date} : {', '.join(times)}")
            
            result_string = "Voici les disponibilités récupérées :\n" + "\n".join(formatted_slots)
            print("✅ [CAL TOOL] Créneaux récupérés avec succès.")
            return result_string

        except Exception as e:
            print(f"❌ [CAL TOOL] Erreur lors de l'appel à l'API Cal.com : {e}")
            return "Le calendrier est momentanément inaccessible."

# --- BLOC DE TEST ---
if __name__ == "__main__":
    import asyncio
    async def tester_radar():
        print("🚀 Lancement du test du Radar Cal.com (Version Sécurisée)...")
        resultat = await get_available_slots(3)
        print("\n--- RÉSULTAT POUR L'IA ---")
        print(resultat)
        print("--------------------------")
    asyncio.run(tester_radar())