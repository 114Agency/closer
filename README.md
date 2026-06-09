# Agent 3: The Closer Agent

Le Closer Agent est le bras armé du système pour l'engagement client multicanal. Il est responsable de la communication active avec le prospect une fois que ce dernier a été qualifié et classé.

Contrairement au CRM Keeper, le Closer Agent est "stateless" (sans état). Il exécute des tâches de communication complexes et s'appuie sur le CRM Keeper pour lire le contexte du lead et enregistrer l'historique des interactions. Il combine des séquences automatisées déterministes (emails) avec une intelligence artificielle générative (WhatsApp) pour traiter les objections en temps réel.

---

# Responsibilities

- Exécuter des séquences d'emails automatisées via l'API Brevo : "Nurture" pour les MQL (5 emails sur 21 jours) et "Follow-up" pour les SQL (3 emails sur 5 jours).
- Envoyer des messages WhatsApp sortants à l'aide de l'API 360dialog (modèles et messages libres).
- Gérer les réponses entrantes sur WhatsApp (`incoming replies`) via un Webhook.
- Utiliser un LLM (Gemma via LangChain) pour analyser les intentions des prospects (Objection de prix, demande de rendez-vous, refus) et générer des contre-arguments persuasifs en temps réel.
- Gérer la prise de rendez-vous en écoutant les Webhooks de Cal.com et en notifiant le prospect et le CRM Keeper.
- Exécuter un CRON job quotidien ("7-day re-engagement job") pour relancer une ultime fois les prospects silencieux depuis 7 jours.
- Tracer toutes les interactions, les sélections de templates et les raisonnements de l'IA dans Langfuse pour l'observabilité.

---

# What this agent does NOT do

- Ne stocke aucune donnée de manière permanente : toute mise à jour de statut, de compteur de messages ou d'historique est déléguée au CRM Keeper.
- Ne qualifie pas les leads : il part du principe que le Qualifier Agent a déjà fait son travail et attribué un score/secteur.
- N'orchestre pas l'ensemble du système : c'est le Commander qui dicte au Closer quand déclencher la première étape d'une séquence.

---

# Setup

## Utiliser UV pour la gestion des dépendances.

## Installer les dépendances :

```bash
uv add fastapi uvicorn pydantic python-dotenv httpx langchain-openai apscheduler langfuse
```

## Créer le fichier `.env` à partir de `.env.example`.

---

# Environment Variables

| Variable Name | Description | Required | Example Value |
|---|---|---|---|
| CRM_KEEPER_URL | URL interne du microservice CRM Keeper | Yes | http://localhost:8000 |
| BREVO_API_KEY | Token de l'API Brevo pour l'envoi d'emails | Yes | xkeysib-1234... |
| SENDER_EMAIL | L'adresse email d'expédition (Brevo) | Yes | contact@monentreprise.com |
| D360_API_KEY | Token de l'API WhatsApp 360dialog | Yes | 170S58NXD... |
| D360_BASE_URL | URL de l'API 360dialog (Sandbox ou Prod) | Yes | https://waba-sandbox.360dialog.io/v1/messages |
| LLM_API_KEY | Clé API pour le modèle NLP (Gemma) | Yes | sk-... |
| LLM_BASE_URL | URL de base de l'API LLM | Yes | https://api.exemple.com/v1 |
| LLM_MODEL_NAME | Nom exact du modèle à instancier | Yes | google/gemma-4-26B-A4B-it |
| LANGFUSE_PUBLIC_KEY | Clé publique pour le tracing Langfuse | Yes | pk-lf-123456... |
| LANGFUSE_SECRET_KEY | Clé secrète pour le tracing Langfuse | Yes | sk-lf-123456... |

---

# Running the Agent

## Development mode (Local avec Ngrok)

```bash
uv run uvicorn api:app --port 8002 --reload
```

Note : Le Webhook WhatsApp doit pointer vers `https://<ngrok-url>/whatsapp/incoming`

## Production mode (VPS)

```bash
uv run uvicorn api:app --host 0.0.0.0 --port 8002 --workers 4
```

Note : Le Webhook WhatsApp doit pointer vers `http://<vps-ip>:8002/whatsapp/incoming`

---

# Current Phase: Phase B (Full sequences and booking)

## Objectif

Engager activement les leads classifiés via des canaux multiples (Email & WhatsApp), traiter les objections en langage naturel, et amener le prospect à booker un appel sur le calendrier.

## Fonctionnalités activées

- Architecture Asynchrone (FastAPI + BackgroundTasks).
- Job planifié quotidien (APScheduler) pour le balayage des séquences MQL/SQL.
- Intégration WhatsApp bidirectionnelle (Webhooks Meta / 360dialog).
- Traitement cognitif des objections via LangChain et PydanticOutputParser.
- Synchronisation Cal.com pour clôturer la boucle de conversion.
- Observabilité complète via Langfuse (Tracing des templates et du raisonnement LLM).

---

# Phase B Validation Checklist

- [x] L'agent lit l'état actuel du prospect via le CRM Keeper et envoie le bon template (MQL ou SQL).
- [x] Les séquences se mettent en pause automatiquement si le prospect répond sur un autre canal.
- [x] Le Webhook WhatsApp capte les réponses en temps réel sans timeout (Traitement asynchrone).
- [x] Le LLM classe correctement les intentions ("PRENDRE_RDV", "OBJECTION_PRIX", etc.) et génère une réponse contextuelle.
- [x] Le "7-day re-engagement job" filtre correctement les MQL inactifs depuis 7 jours et envoie un message unique.
- [x] L'événement Cal.com (BOOKING_CREATED) synchronise le lead en meeting_booked dans le CRM.
- [x] Toutes les actions sortantes (Template + IA) sont taguées et tracées sur le tableau de bord Langfuse.

---

# Inputs and Outputs (Exemples Phase B)

## Input Example (POST /api/v1/closer/trigger)

```json
{
  "lead_id": "783778261194",
  "first_name": "Maria",
  "classification": "sql",
  "problem_statement": "Besoin d'automatiser l'acquisition pour réduire le CAC.",
  "industry_segment": "e_commerce",
  "current_step": 1,
  "phone": "+33612345678"
}
```

## Webhook WhatsApp Input Example (POST /whatsapp/incoming)

```json
{
  "entry": [
    {
      "changes": [
        {
          "value": {
            "messages": [
              {
                "from": "+33612345678",
                "text": {
                  "body": "Votre outil a l'air intéressant, mais je crains que l'intégration soit trop complexe pour notre équipe actuelle."
                }
              }
            ]
          }
        }
      ]
    }
  ]
}
```
