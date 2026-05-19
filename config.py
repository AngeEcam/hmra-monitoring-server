# ─────────────────────────────────────────────
#  CONFIG — HMRA Monitor
# ─────────────────────────────────────────────

PORT    = 8080
HOST    = "0.0.0.0"
DB_PATH = "hmra_monitor.db"

OFFLINE_THRESHOLD_S = 180

THRESHOLDS = {
    1: {"temp_c": (15.0, 30.0), "hum_rh": (30.0, 60.0), "pres_hpa": (950.0, 1050.0)},
    2: {"temp_c": (15.0, 30.0), "hum_rh": (30.0, 60.0)},
    3: {"temp_c": (0.0,  30.0)},
    4: {"temp_c": (-50.0, 30.0)},
    5: {"temp_c": (15.0, 30.0), "hum_rh": (30.0, 60.0)},
}

SENSOR_NAMES = {
    1: "STHP01A",
    2: "XYMD04 RS485",
    3: "PT100 Canal 1",
    4: "PT100 Canal 2",
    5: "XYMD04 RS485 #2",
}

SENSOR_PARAMS = {
    1: ["temp_c", "hum_rh", "pres_hpa"],
    2: ["temp_c", "hum_rh"],
    3: ["temp_c"],
    4: ["temp_c"],
    5: ["temp_c", "hum_rh"],
}

PARAM_LABELS = {
    "temp_c":   "Température (°C)",
    "hum_rh":   "Humidité (%RH)",
    "pres_hpa": "Pression (hPa)",
}

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

# Service qui utilise physiquement l'équipement
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

# Service administrativement responsable de l'équipement
SERVICES_RESPONSABLE = [
    "Service technique biomédical",
    "Pharmacie",
    "Laboratoire",
    "Direction médicale",
    "Stérilisation (STERAP)",
    "Autre",
]