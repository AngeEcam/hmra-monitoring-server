"""
main.py — HMRA Monitor — Routes FastAPI

Prérequis :
    pip install fastapi uvicorn python-jose[cryptography] bcrypt python-dotenv

Lancement :
    python main.py
"""

import os
import json
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, Query, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
import uvicorn

from config import (
    PORT, HOST, OFFLINE_THRESHOLD_S,
    UNIT_TYPES, SERVICES_UTILISATION, SERVICES_RESPONSABLE, ALL_SERVICES,
    SUPERADMIN_PASSWORD, TOKEN_EXPIRE_MINUTES,
)
from database import (
    init_db, ensure_superadmin,
    # Auth
    get_user_by_username, get_all_users, create_user,
    update_user, delete_user, reset_user_password,
    # Mesures
    insert_measurement, check_and_log_alerts,
    acknowledge_alert, acknowledge_all_alerts,
    query_stats, query_alerts, query_history,
    query_measurements, count_measurements,
    # Capteurs
    get_sensor_config, set_sensor_mode, rename_sensor, delete_sensor,
    # Unités
    get_all_units, get_unit, create_unit, update_unit, delete_unit,
    assign_sensor_to_unit,
    # Seuils
    get_all_thresholds, get_thresholds_for_sensor, set_threshold,
    # Notifications
    get_alert_recipients,
)
from notifier import notify_alerts
from auth import (
    hash_password, verify_password,
    create_access_token, get_current_user, require_superadmin,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="HMRA Monitor")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


# ─────────────────────────────────────────────────────────────────────────────
#  AUTHENTIFICATION
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Endpoint de login standard OAuth2.
    Retourne un Bearer token JWT si les credentials sont corrects.
    """
    user = get_user_by_username(form_data.username)
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")

    token = create_access_token(
        data={
            "sub":     user["username"],
            "role":    user["role"],
            "service": user["service"],
            "user_id": user["id"],
        },
        expires_delta=timedelta(minutes=TOKEN_EXPIRE_MINUTES),
    )
    return {
        "access_token": token,
        "token_type":   "bearer",
        "role":         user["role"],
        "service":      user["service"],
        "username":     user["username"],
    }


@app.get("/auth/me")
async def me(current_user: dict = Depends(get_current_user)):
    """Retourne les infos du token courant (utile côté frontend)."""
    return {
        "username": current_user["sub"],
        "role":     current_user["role"],
        "service":  current_user.get("service"),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  ADMINISTRATION — SUPERADMIN UNIQUEMENT
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/admin/users")
async def admin_list_users(_: dict = Depends(require_superadmin)):
    """Liste tous les utilisateurs (sans leurs mots de passe)."""
    return {"users": get_all_users()}


@app.post("/admin/users")
async def admin_create_user(request: Request, _: dict = Depends(require_superadmin)):
    """
    Crée un utilisateur.
    Body JSON : { username, password, role, service }
    """
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    username     = payload.get("username", "").strip()
    password     = payload.get("password", "").strip()
    role         = payload.get("role", "user")
    service      = payload.get("service", "")
    email        = payload.get("email", "").strip()
    notify_email = payload.get("notify_email", True)

    if not username or not password:
        return {"status": "error", "detail": "username et password sont obligatoires"}
    if role not in ("user", "superadmin"):
        return {"status": "error", "detail": "role invalide (user | superadmin)"}
    if role == "user" and not service:
        return {"status": "error", "detail": "Un utilisateur non-superadmin doit avoir un service"}

    try:
        user = create_user(username, hash_password(password), role, service, email, notify_email)
    except ValueError as e:
        return {"status": "error", "detail": str(e)}

    return {"status": "ok", "user": user}


@app.put("/admin/users/{user_id}")
async def admin_update_user(user_id: int, request: Request,
                            _: dict = Depends(require_superadmin)):
    """
    Met à jour un utilisateur (username, role, service).
    Body JSON : { username?, role?, service? }
    """
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    found = update_user(
        user_id,
        username=payload.get("username"),
        role=payload.get("role"),
        service=payload.get("service"),
        email=payload.get("email"),
        notify_email=payload.get("notify_email"),
    )
    if not found:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return {"status": "ok", "user_id": user_id}


@app.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: int, request: Request,
                               _: dict = Depends(require_superadmin)):
    """
    Réinitialise le mot de passe d'un utilisateur.
    Body JSON : { password }
    """
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    password = payload.get("password", "").strip()
    if not password:
        return {"status": "error", "detail": "Le mot de passe ne peut pas être vide"}

    found = reset_user_password(user_id, hash_password(password))
    if not found:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return {"status": "ok", "user_id": user_id, "message": "Mot de passe réinitialisé"}


@app.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: int, _: dict = Depends(require_superadmin)):
    """Supprime un utilisateur (impossible de supprimer un superadmin)."""
    found = delete_user(user_id)
    if not found:
        raise HTTPException(
            status_code=404,
            detail="Utilisateur introuvable ou impossible à supprimer (superadmin)"
        )
    return {"status": "ok", "user_id": user_id}


@app.get("/admin/services")
async def admin_list_services(_: dict = Depends(require_superadmin)):
    """Retourne la liste des services disponibles pour l'assignation."""
    return {"services": ALL_SERVICES}


# ─────────────────────────────────────────────────────────────────────────────
#  INGEST (pas de auth — appelé par les capteurs/gateway)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/ingest")
async def ingest(request: Request):
    body_str = (await request.body()).decode("utf-8", errors="replace")
    if not body_str.strip():
        return {"status": "error", "detail": "body vide"}
    try:
        data = json.loads(body_str)
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    received_at = datetime.now().isoformat()
    sid = data.get("sid")

    cfg = get_sensor_config().get(sid, {"mode": "active", "deleted": False})

    if cfg["deleted"]:
        set_sensor_mode(sid, "active")

    mode = cfg["mode"]
    if mode == "disabled":
        return {"status": "ignored", "reason": "disabled"}

    insert_measurement(data, received_at)
    alerts = check_and_log_alerts(data, received_at) if mode == "active" else []

    name  = cfg.get("name") or f"Capteur {sid}"

    # Envoi email si nouvelles alertes
    if alerts:
        unit_service = None
        all_units = get_all_units()
        unit_id = cfg.get("unit_id")
        if unit_id:
            unit = next((u for u in all_units if u["unit_id"] == unit_id), None)
            if unit:
                unit_service = unit.get("service_utilisation") or unit.get("service_responsable")
        recipients = get_alert_recipients(service=unit_service)
        notify_alerts(recipients, name, sid, alerts)

    now   = datetime.now().strftime("%H:%M:%S")
    label = {"active": "", "maintenance": " [MAINTENANCE]", "disabled": " [OFF]"}[mode]
    print(f"\n{'─'*45}")
    print(f"  {now}  —  {name}{label}")
    print(f"  Température : {data.get('temp_c', '?')} °C")
    if "hum_rh"   in data: print(f"  Humidité    : {data.get('hum_rh')} %RH")
    if "pres_hpa" in data: print(f"  Pression    : {data.get('pres_hpa')} hPa")
    if alerts:             print(f"  {len(alerts)} alarme(s)")
    print(f"{'─'*45}")

    return {"status": "ok", "alerts": len(alerts)}


# ─────────────────────────────────────────────────────────────────────────────
#  DONNÉES — filtrées selon le service de l'utilisateur connecté
# ─────────────────────────────────────────────────────────────────────────────

def _service_filter(user: dict) -> str | None:
    """Retourne le filtre de service ou None si superadmin (voit tout)."""
    if user.get("role") == "superadmin":
        return None
    return user.get("service")


@app.get("/data")
async def get_data(
    hours: int = Query(None),
    sid:   int = Query(None),
    limit: int = Query(100),
    current_user: dict = Depends(get_current_user),
):
    rows = query_measurements(hours=hours, sid=sid, limit=limit)
    return {"count": len(rows), "data": rows}


@app.get("/stats")
async def get_stats(current_user: dict = Depends(get_current_user)):
    sf   = _service_filter(current_user)
    rows = query_stats(service_filter=sf)
    now  = datetime.now()

    active_alerts = query_alerts(limit=200, only_active=True, service_filter=sf)
    alarm_sids    = {a["sid"] for a in active_alerts}
    sensor_cfg    = get_sensor_config()

    for r in rows:
        sid  = r["sid"]
        cfg  = sensor_cfg.get(sid, {"mode": "active", "deleted": False, "note": None, "unit_id": None})
        mode = cfg["mode"]

        r["sensor_name"] = cfg.get("name") or f"Capteur {sid}"
        r["mode"]    = mode
        r["deleted"] = cfg["deleted"]
        r["note"]    = cfg["note"]

        last = datetime.fromisoformat(r["received_at"])
        age  = int((now - last).total_seconds())
        r["age_seconds"] = age

        if cfg["deleted"] or mode != "active":
            r["offline"]   = False
            r["has_alarm"] = False
        else:
            r["offline"]   = age > OFFLINE_THRESHOLD_S
            r["has_alarm"] = sid in alarm_sids

    return {"sensors": rows, "offline_threshold_s": OFFLINE_THRESHOLD_S}


@app.get("/alerts")
async def get_alerts(
    limit:       int  = Query(50),
    active_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    sf   = _service_filter(current_user)
    rows = query_alerts(limit=limit, only_active=active_only, service_filter=sf)
    sensor_cfg = get_sensor_config()
    for r in rows:
        cfg = sensor_cfg.get(r["sid"], {})
        r["sensor_name"] = cfg.get("name") or f"Capteur {r['sid']}"
    return {"count": len(rows), "alerts": rows}


@app.post("/alerts/{alert_id}/acknowledge")
async def ack_alert(alert_id: int, _: dict = Depends(get_current_user)):
    acknowledge_alert(alert_id)
    return {"status": "ok", "alert_id": alert_id}


@app.post("/alerts/acknowledge-all")
async def ack_all(_: dict = Depends(get_current_user)):
    affected = acknowledge_all_alerts()
    return {"status": "ok", "acknowledged": affected}


@app.get("/history/{sid}")
async def get_history(
    sid: int,
    hours: int = Query(24),
    _: dict = Depends(get_current_user),
):
    rows = query_history(sid=sid, hours=hours)
    return {"sid": sid, "count": len(rows), "data": rows}


# ─────────────────────────────────────────────────────────────────────────────
#  SEUILS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/thresholds")
async def list_thresholds(_: dict = Depends(get_current_user)):
    return {"thresholds": get_all_thresholds()}


@app.get("/thresholds/{sid}")
async def get_sensor_thresholds(sid: int, _: dict = Depends(get_current_user)):
    data = get_thresholds_for_sensor(sid)
    if not data:
        raise HTTPException(status_code=404, detail=f"Aucun seuil pour sid={sid}")
    return {"sid": sid, "thresholds": data}


@app.put("/thresholds/{sid}/{param}")
async def update_threshold(
    sid: int, param: str, request: Request,
    _: dict = Depends(get_current_user),
):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    vmin, vmax = payload.get("vmin"), payload.get("vmax")
    if vmin is None or vmax is None:
        return {"status": "error", "detail": "vmin et vmax sont obligatoires"}
    if vmin >= vmax:
        return {"status": "error", "detail": "vmin doit être < vmax"}

    set_threshold(sid, param, float(vmin), float(vmax))
    return {"status": "ok", "sid": sid, "param": param, "vmin": vmin, "vmax": vmax}


# ─────────────────────────────────────────────────────────────────────────────
#  CAPTEURS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/sensors/config")
async def sensors_config(_: dict = Depends(get_current_user)):
    cfg        = get_sensor_config()
    thresholds = get_all_thresholds()
    return [
        {
            "sid":        sid,
            "name":       e.get("name") or f"Capteur {sid}",
            "mode":       e["mode"],
            "deleted":    e["deleted"],
            "note":       e["note"],
            "unit_id":    e["unit_id"],
            "thresholds": thresholds.get(sid, {}),
        }
        for sid, e in cfg.items()
    ]


@app.post("/sensors/{sid}/mode")
async def set_sensor_mode_endpoint(
    sid: int, request: Request,
    _: dict = Depends(require_superadmin),
):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    mode = payload.get("mode", "active")
    note = payload.get("note")
    if mode not in ["active", "maintenance", "disabled"]:
        return {"status": "error", "detail": "mode invalide"}

    set_sensor_mode(sid, mode, note)
    return {"status": "ok", "sid": sid, "mode": mode}


@app.put("/sensors/{sid}/name")
async def rename_sensor_endpoint(
    sid: int, request: Request,
    _: dict = Depends(require_superadmin),
):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    name = payload.get("name", "").strip()
    if not name:
        return {"status": "error", "detail": "Le nom ne peut pas être vide"}
    rename_sensor(sid, name)
    return {"status": "ok", "sid": sid, "name": name}


@app.delete("/sensors/{sid}")
async def remove_sensor(sid: int, _: dict = Depends(require_superadmin)):
    delete_sensor(sid)
    return {"status": "ok", "sid": sid}


@app.post("/sensors/{sid}/assign-unit")
async def assign_unit(
    sid: int, request: Request,
    current_user: dict = Depends(get_current_user),
):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    unit_id = payload.get("unit_id")

    # Un user ne peut assigner qu'à une unité de son service
    if current_user.get("role") != "superadmin" and unit_id is not None:
        unit = get_unit(unit_id)
        if not unit:
            raise HTTPException(status_code=404, detail="Unité introuvable")
        sf = current_user.get("service")
        if unit.get("service_utilisation") != sf and unit.get("service_responsable") != sf:
            raise HTTPException(status_code=403, detail="Cette unité n'appartient pas à votre service")

    assign_sensor_to_unit(sid, unit_id)
    return {"status": "ok", "sid": sid, "unit_id": unit_id}


# ─────────────────────────────────────────────────────────────────────────────
#  UNITÉS — filtrées selon le service de l'utilisateur
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/units")
async def list_units(current_user: dict = Depends(get_current_user)):
    sf = _service_filter(current_user)
    return {"units": get_all_units(service_filter=sf)}


@app.get("/units/form-options")
async def unit_form_options(_: dict = Depends(get_current_user)):
    return {
        "unit_types":           UNIT_TYPES,
        "services_utilisation": SERVICES_UTILISATION,
        "services_responsable": SERVICES_RESPONSABLE,
    }


@app.get("/units/{unit_id}")
async def get_unit_endpoint(unit_id: int, _: dict = Depends(get_current_user)):
    unit = get_unit(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unité introuvable")
    return unit


@app.post("/units")
async def create_unit_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    name = payload.get("name", "").strip()
    if not name:
        return {"status": "error", "detail": "Le nom est obligatoire"}

    # Un user crée forcément dans son propre service
    if current_user.get("role") != "superadmin":
        sf = current_user.get("service", "")
        payload["service_utilisation"] = sf
        payload["service_responsable"] = sf

    unit = create_unit(
        name,
        payload.get("unit_type", ""),
        payload.get("service_utilisation", ""),
        payload.get("service_responsable", ""),
    )
    return {"status": "ok", "unit": unit}


@app.put("/units/{unit_id}")
async def update_unit_endpoint(
    unit_id: int, request: Request,
    current_user: dict = Depends(get_current_user),
):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    name = payload.get("name", "").strip()
    if not name:
        return {"status": "error", "detail": "Le nom est obligatoire"}

    # Vérifier que l'unité appartient au service de l'user
    if current_user.get("role") != "superadmin":
        unit = get_unit(unit_id)
        if not unit:
            raise HTTPException(status_code=404, detail="Unité introuvable")
        sf = current_user.get("service")
        if unit.get("service_utilisation") != sf and unit.get("service_responsable") != sf:
            raise HTTPException(status_code=403, detail="Cette unité n'appartient pas à votre service")
        # Empêcher de changer le service de l'unité
        payload["service_utilisation"] = sf
        payload["service_responsable"] = sf

    found = update_unit(
        unit_id, name,
        payload.get("unit_type", ""),
        payload.get("service_utilisation", ""),
        payload.get("service_responsable", ""),
    )
    if not found:
        raise HTTPException(status_code=404, detail="Unité introuvable")
    return {"status": "ok", "unit_id": unit_id}


@app.delete("/units/{unit_id}")
async def delete_unit_endpoint(unit_id: int, current_user: dict = Depends(get_current_user)):
    unit = get_unit(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unité introuvable")
    # Un user ne peut supprimer que ses propres unités
    if current_user.get("role") != "superadmin":
        sf = current_user.get("service")
        if unit.get("service_utilisation") != sf and unit.get("service_responsable") != sf:
            raise HTTPException(status_code=403, detail="Cette unité n'appartient pas à votre service")
    delete_unit(unit_id)
    return {"status": "ok", "unit_id": unit_id}


# ─────────────────────────────────────────────────────────────────────────────
#  ROOT + DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "HMRA Monitor running", "total_records": count_measurements()}


@app.get("/dashboard")
async def dashboard():
    return FileResponse(os.path.join(BASE_DIR, "static", "dashboard.html"))


# ─────────────────────────────────────────────────────────────────────────────
#  LANCEMENT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    ensure_superadmin("admin", hash_password(SUPERADMIN_PASSWORD))

    print(f"\n{'═'*50}")
    print(f"  HMRA Monitor — Serveur")
    print(f"{'═'*50}")
    print(f"  Dashboard   → http://192.168.1.100:{PORT}/dashboard")
    print(f"  Login       → POST /auth/login")
    print(f"  Admin users → GET  /admin/users  (superadmin)")
    print(f"  API stats   → GET  /stats")
    print(f"  API alerts  → GET  /alerts")
    print(f"  API units   → GET  /units")
    print(f"{'═'*50}\n")

    uvicorn.run(app, host=HOST, port=PORT)