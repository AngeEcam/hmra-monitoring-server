# ─────────────────────────────────────────────
#  CONFIG — HMRA Monitor
# ─────────────────────────────────────────────

PORT    = 8080
HOST    = "0.0.0.0"
DB_PATH = "hmra_monitor.db"

OFFLINE_THRESHOLD_S = 180

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