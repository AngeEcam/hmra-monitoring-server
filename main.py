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

from fastapi import FastAPI, Request, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import PORT, HOST, SENSOR_NAMES, OFFLINE_THRESHOLD_S
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
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="HMRA Monitor")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


# ── Ingest ───────────────────────────────────

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
    insert_measurement(data, received_at)
    alerts = check_and_log_alerts(data, received_at)

    sid  = data.get("sid", "?")
    name = SENSOR_NAMES.get(sid, f"sid={sid}")
    now  = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'─'*45}")
    print(f"  {now}  —  {name}")
    print(f"  Température : {data.get('temp_c', '?')} °C")
    if "hum_rh"   in data: print(f"  Humidité    : {data.get('hum_rh')} %RH")
    if "pres_hpa" in data: print(f"  Pression    : {data.get('pres_hpa')} hPa")
    if alerts:             print(f"  ⚠️  {len(alerts)} alarme(s)")
    print(f"{'─'*45}")
    return {"status": "ok", "alerts": len(alerts)}


# ── Données brutes ───────────────────────────

@app.get("/data")
async def get_data(
    hours: int = Query(None),
    sid:   int = Query(None),
    limit: int = Query(100)
):
    rows = query_measurements(hours=hours, sid=sid, limit=limit)
    return {"count": len(rows), "data": rows}


# ── Stats ────────────────────────────────────

@app.get("/stats")
async def get_stats():
    rows          = query_stats()
    now           = datetime.now()
    active_alerts = query_alerts(limit=200, only_active=True)
    alarm_sids    = set(a["sid"] for a in active_alerts)

    for r in rows:
        r["sensor_name"] = SENSOR_NAMES.get(r["sid"], "Inconnu")
        last             = datetime.fromisoformat(r["received_at"])
        r["age_seconds"] = int((now - last).total_seconds())
        r["offline"]     = r["age_seconds"] > OFFLINE_THRESHOLD_S
        r["has_alarm"]   = r["sid"] in alarm_sids
    return {"sensors": rows, "offline_threshold_s": OFFLINE_THRESHOLD_S}


# ── Alarmes ──────────────────────────────────

@app.get("/alerts")
async def get_alerts(
    limit:       int  = Query(50),
    active_only: bool = Query(False)
):
    rows = query_alerts(limit=limit, only_active=active_only)
    for r in rows:
        r["sensor_name"] = SENSOR_NAMES.get(r["sid"], "Inconnu")
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


# ── Historique ───────────────────────────────

@app.get("/history/{sid}")
async def get_history(sid: int, hours: int = Query(24)):
    rows = query_history(sid=sid, hours=hours)
    return {"sid": sid, "count": len(rows), "data": rows}


# ── Root + Dashboard ─────────────────────────

@app.get("/")
async def root():
    return {"status": "HMRA Monitor running", "total_records": count_measurements()}


@app.get("/dashboard")
async def dashboard():
    return FileResponse(os.path.join(BASE_DIR, "static", "dashboard.html"))


# ─────────────────────────────────────────────
#  LANCEMENT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print(f"\n{'═'*45}")
    print(f"  HMRA Monitor — Serveur")
    print(f"{'═'*45}")
    print(f"  Dashboard  → http://192.168.1.100:{PORT}/dashboard")
    print(f"  API stats  → http://192.168.1.100:{PORT}/stats")
    print(f"  API data   → http://192.168.1.100:{PORT}/data")
    print(f"  API alerts → http://192.168.1.100:{PORT}/alerts")
    print(f"{'═'*45}\n")
    uvicorn.run(app, host=HOST, port=PORT)