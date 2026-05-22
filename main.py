"""
main.py — HMRA Monitor — Routes FastAPI uniquement

Prérequis :
    pip install fastapi uvicorn

Lancement :
    python main.py
"""

import os
import json
from datetime import datetime

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import (
    PORT, HOST, OFFLINE_THRESHOLD_S,
    UNIT_TYPES, SERVICES_UTILISATION, SERVICES_RESPONSABLE,
)
from database import (
    init_db,
    insert_measurement,
    check_and_log_alerts,
    acknowledge_alert,
    acknowledge_all_alerts,
    query_stats,
    query_alerts,
    query_history,
    query_measurements,
    count_measurements,
    get_sensor_config,
    set_sensor_mode,
    rename_sensor,
    delete_sensor,
    get_all_units,
    get_unit,
    create_unit,
    update_unit,
    delete_unit,
    assign_sensor_to_unit,
    get_all_thresholds,
    get_thresholds_for_sensor,
    set_threshold,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="HMRA Monitor")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


# ── Ingest ───────────────────────────────────────────────────────────────────

@app.post("/ingest")
async def ingest(request: Request):

    body = await request.body()
    body_str = body.decode("utf-8", errors="replace")

    if not body_str.strip():
        return {"status": "error", "detail": "body vide"}

    try:
        data = json.loads(body_str)
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    received_at = datetime.now().isoformat()
    sid = data.get("sid")

    cfg = get_sensor_config().get(
        sid,
        {"mode": "active", "deleted": False}
    )

    if cfg["deleted"]:
        set_sensor_mode(sid, "active")
        print(f"[AUTO] Sensor {sid} restauré automatiquement")

    mode = cfg["mode"]

    if mode == "disabled":
        print(f"[INFO] Sensor {sid} ignoré (OFF)")
        return {"status": "ignored", "reason": "disabled"}

    insert_measurement(data, received_at)

    alerts = []
    if mode == "active":
        alerts = check_and_log_alerts(data, received_at)

    name = cfg.get("name") or f"Capteur {sid}"
    now  = datetime.now().strftime("%H:%M:%S")
    label = {"active": "", "maintenance": " [MAINTENANCE]", "disabled": " [OFF]"}[mode]

    print(f"\n{'─'*45}")
    print(f"  {now}  —  {name}{label}")
    print(f"  Température : {data.get('temp_c', '?')} °C")
    if "hum_rh"   in data: print(f"  Humidité    : {data.get('hum_rh')} %RH")
    if "pres_hpa" in data: print(f"  Pression    : {data.get('pres_hpa')} hPa")
    if alerts:             print(f"  {len(alerts)} alarme(s)")
    print(f"{'─'*45}")

    return {"status": "ok", "alerts": len(alerts)}


# ── Données brutes ────────────────────────────────────────────────────────────

@app.get("/data")
async def get_data(
    hours: int = Query(None),
    sid:   int = Query(None),
    limit: int = Query(100),
):
    rows = query_measurements(hours=hours, sid=sid, limit=limit)
    return {"count": len(rows), "data": rows}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
async def get_stats():
    rows          = query_stats()
    now           = datetime.now()
    active_alerts = query_alerts(limit=200, only_active=True)
    alarm_sids    = {a["sid"] for a in active_alerts}
    sensor_cfg    = get_sensor_config()

    for r in rows:
        sid = r["sid"]
        cfg = sensor_cfg.get(sid, {"mode": "active", "deleted": False, "note": None, "unit_id": None})

        r["sensor_name"] = cfg.get("name") or f"Capteur {sid}"
        mode = cfg["mode"]
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


# ── Alarmes ───────────────────────────────────────────────────────────────────

@app.get("/alerts")
async def get_alerts(
    limit:       int  = Query(50),
    active_only: bool = Query(False),
):
    rows = query_alerts(limit=limit, only_active=active_only)
    sensor_cfg = get_sensor_config()
    for r in rows:
        sid = r["sid"]
        cfg = sensor_cfg.get(sid, {})
        r["sensor_name"] = cfg.get("name") or f"Capteur {sid}"
    return {"count": len(rows), "alerts": rows}


@app.post("/alerts/{alert_id}/acknowledge")
async def ack_alert(alert_id: int):
    acknowledge_alert(alert_id)
    print(f"[ACK] Alarme {alert_id} acquittée")
    return {"status": "ok", "alert_id": alert_id}


@app.post("/alerts/acknowledge-all")
async def ack_all():
    affected = acknowledge_all_alerts()
    print(f"[ACK] {affected} alarme(s) acquittées")
    return {"status": "ok", "acknowledged": affected}


# ── Historique ────────────────────────────────────────────────────────────────

@app.get("/history/{sid}")
async def get_history(sid: int, hours: int = Query(24)):
    rows = query_history(sid=sid, hours=hours)
    return {"sid": sid, "count": len(rows), "data": rows}


# ── Seuils ────────────────────────────────────────────────────────────────────

@app.get("/thresholds")
async def list_thresholds():
    return {"thresholds": get_all_thresholds()}


@app.get("/thresholds/{sid}")
async def get_sensor_thresholds(sid: int):
    data = get_thresholds_for_sensor(sid)
    if not data:
        raise HTTPException(status_code=404, detail=f"Aucun seuil pour sid={sid}")
    return {"sid": sid, "thresholds": data}


@app.put("/thresholds/{sid}/{param}")
async def update_threshold(sid: int, param: str, request: Request):
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    vmin = payload.get("vmin")
    vmax = payload.get("vmax")

    if vmin is None or vmax is None:
        return {"status": "error", "detail": "vmin et vmax sont obligatoires"}
    if vmin >= vmax:
        return {"status": "error", "detail": "vmin doit être strictement inférieur à vmax"}

    set_threshold(sid, param, float(vmin), float(vmax))
    return {"status": "ok", "sid": sid, "param": param, "vmin": vmin, "vmax": vmax}


# ── Gestion des capteurs ──────────────────────────────────────────────────────

@app.get("/sensors/config")
async def sensors_config():
    cfg        = get_sensor_config()
    thresholds = get_all_thresholds()
    result     = []
    for sid, entry in cfg.items():
        result.append({
            "sid":        sid,
            "name":       entry.get("name") or f"Capteur {sid}",
            "mode":       entry["mode"],
            "deleted":    entry["deleted"],
            "note":       entry["note"],
            "unit_id":    entry["unit_id"],
            "thresholds": thresholds.get(sid, {}),
        })
    return result


@app.post("/sensors/{sid}/mode")
async def set_sensor_mode_endpoint(sid: int, request: Request):
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    mode = payload.get("mode", "active")
    note = payload.get("note", None)

    if mode not in ["active", "maintenance", "disabled"]:
        return {"status": "error", "detail": "mode invalide"}

    set_sensor_mode(sid, mode, note)
    label = {"active": "ACTIF", "maintenance": "MAINTENANCE", "disabled": "OFF"}[mode]
    return {"status": "ok", "sid": sid, "mode": mode, "message": f"Capteur {sid} {label}"}


@app.put("/sensors/{sid}/name")
async def rename_sensor_endpoint(sid: int, request: Request):
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    name = payload.get("name", "").strip()
    if not name:
        return {"status": "error", "detail": "Le nom ne peut pas être vide"}

    rename_sensor(sid, name)
    return {"status": "ok", "sid": sid, "name": name}


@app.delete("/sensors/{sid}")
async def remove_sensor(sid: int):
    delete_sensor(sid)
    return {"status": "ok", "sid": sid, "message": f"Capteur {sid} supprimé"}


@app.post("/sensors/{sid}/assign-unit")
async def assign_unit(sid: int, request: Request):
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    unit_id = payload.get("unit_id")
    assign_sensor_to_unit(sid, unit_id)
    return {"status": "ok", "sid": sid, "unit_id": unit_id}


# ── Gestion des unités ────────────────────────────────────────────────────────

@app.get("/units")
async def list_units():
    return {"units": get_all_units()}


@app.get("/units/form-options")
async def unit_form_options():
    return {
        "unit_types":           UNIT_TYPES,
        "services_utilisation": SERVICES_UTILISATION,
        "services_responsable": SERVICES_RESPONSABLE,
    }


@app.get("/units/{unit_id}")
async def get_unit_endpoint(unit_id: int):
    unit = get_unit(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unité introuvable")
    return unit


@app.post("/units")
async def create_unit_endpoint(request: Request):
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    name                = payload.get("name", "").strip()
    unit_type           = payload.get("unit_type", "")
    service_utilisation = payload.get("service_utilisation", "")
    service_responsable = payload.get("service_responsable", "")

    if not name:
        return {"status": "error", "detail": "Le nom est obligatoire"}

    unit = create_unit(name, unit_type, service_utilisation, service_responsable)
    return {"status": "ok", "unit": unit}


@app.put("/units/{unit_id}")
async def update_unit_endpoint(unit_id: int, request: Request):
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return {"status": "error", "detail": "JSON invalide"}

    name                = payload.get("name", "").strip()
    unit_type           = payload.get("unit_type", "")
    service_utilisation = payload.get("service_utilisation", "")
    service_responsable = payload.get("service_responsable", "")

    if not name:
        return {"status": "error", "detail": "Le nom est obligatoire"}

    found = update_unit(unit_id, name, unit_type, service_utilisation, service_responsable)
    if not found:
        raise HTTPException(status_code=404, detail="Unité introuvable")
    return {"status": "ok", "unit_id": unit_id}


@app.delete("/units/{unit_id}")
async def delete_unit_endpoint(unit_id: int):
    unit = get_unit(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unité introuvable")
    delete_unit(unit_id)
    return {"status": "ok", "unit_id": unit_id, "message": f"Unité '{unit['name']}' supprimée"}


# ── Root + Dashboard ──────────────────────────────────────────────────────────

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
    print(f"\n{'═'*45}")
    print(f"  HMRA Monitor — Serveur")
    print(f"{'═'*45}")
    print(f"  Dashboard   → http://192.168.1.100:{PORT}/dashboard")
    print(f"  API stats   → http://192.168.1.100:{PORT}/stats")
    print(f"  API alerts  → http://192.168.1.100:{PORT}/alerts")
    print(f"  API units   → http://192.168.1.100:{PORT}/units")
    print(f"  API seuils  → http://192.168.1.100:{PORT}/thresholds")
    print(f"  API config  → http://192.168.1.100:{PORT}/sensors/config")
    print(f"{'═'*45}\n")
    uvicorn.run(app, host=HOST, port=PORT)