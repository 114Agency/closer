import asyncio
from agent import CloserAgent

async def main():
    print("🚀 Démarrage du test de la Phase C...")
    
    # 1. On instancie ton agent
    agent = CloserAgent()
    
    # 2. On crée un faux prospect
    mock_lead = {
        "lead_id": "test_phase_c_999",
        "first_name": "Karim",
        "phone": "+212611223344"
    }
    
    # --- SCÉNARIO 1 : La question inattendue mais cordiale ---
    msg_technique = "Bonjour, est-ce que votre solution d'agent IA peut s'intégrer avec un vieil ERP propriétaire de 2014 ? Et quel serait le coût pour 50 licences ?"
    
    print(f"\n=====================================")
    print(f"📩 TEST 1 : Question complexe de {mock_lead['first_name']}")
    print(f"Message : '{msg_technique}'")
    print(f"=====================================")
    
    resultat_1 = await agent.handle_out_of_template_reply(mock_lead, msg_technique)
    print(f"\n✅ Résultat final renvoyé par l'Agent :")
    print(resultat_1)
    
    # --- SCÉNARIO 2 : La frustration (Test de l'escalade) ---
    msg_frustre = "C'est n'importe quoi ! Ça fait trois fois que je vous demande un devis et je ne reçois que des messages automatiques. Je suis extrêmement déçu de votre service."
    
    print(f"\n=====================================")
    print(f"😡 TEST 2 : Message de frustration de {mock_lead['first_name']}")
    print(f"Message : '{msg_frustre}'")
    print(f"=====================================")
    
    resultat_2 = await agent.handle_out_of_template_reply(mock_lead, msg_frustre)
    print(f"\n✅ Résultat final renvoyé par l'Agent :")
    print(resultat_2)

if __name__ == "__main__":
    # Exécution de la boucle asynchrone
    asyncio.run(main())