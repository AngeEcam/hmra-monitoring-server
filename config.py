# ─────────────────────────────────────────────
#  CONFIG — HMRA Monitor
# ─────────────────────────────────────────────

import os
from dotenv import load_dotenv

load_dotenv()  # Charge .env s'il existe

PORT    = 8080
HOST    = "0.0.0.0"
DB_PATH = "hmra_monitor.db"

OFFLINE_THRESHOLD_S = 180

# ─────────────────────────────────────────────
#  SÉCURITÉ — JWT
# ─────────────────────────────────────────────

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY manquante ! Créez un fichier .env basé sur .env.example"
    )

SUPERADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD", "admin")
TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))

# ─────────────────────────────────────────────
#  UNITÉS — Types d'équipements surveillés
# ─────────────────────────────────────────────

UNIT_TYPES = [
    "Réfrigérateur",
    "Congélateur",
    "Incubateur",
    "Four",
    "Local technique",
    "Salle blanche",
    "Autre",
]

# ─────────────────────────────────────────────
#  SERVICES — Listes déroulantes dashboard
# ─────────────────────────────────────────────

SERVICES_UTILISATION = [
    "Pharmacie",
    "Burn Unit",
    "Laboratoire",
    "Stérilisation (STERAP)",
    "Médecine du travail (AMT)",
    "Travel Clinic",
    "Centre de santé mentale",
    "Service vétérinaire",
    "Service technique biomédical",
    "Autre",
]

SERVICES_RESPONSABLE = [
    "Service technique biomédical",
    "Pharmacie",
    "Laboratoire",
    "Direction médicale",
    "Stérilisation (STERAP)",
    "Autre",
]

# Liste unifiée pour l'assignation d'un utilisateur à un service
ALL_SERVICES = sorted(set(SERVICES_UTILISATION + SERVICES_RESPONSABLE))