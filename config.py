import os
from dotenv import load_dotenv
from dynaconf import Dynaconf

# 1. On force le chargement du fichier .env manuellement
# Cela injecte les clés directement dans l'environnement (os.environ)
load_dotenv() 

# 2. On initialise Dynaconf qui pourra maintenant lire l'environnement
settings = Dynaconf(
    envvar_prefix="CLOSER",
    settings_files=['settings.toml'],
)