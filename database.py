"""
database.py — Toute la logique SQLite pour HMRA Monitor
"""

import sqlite3
import os
from datetime import datetime, timedelta
from config import DB_PATH, THRESHOLDS, SENSOR_NAMES


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,
            ts          INTEGER,
            sid         INTEGER,
            temp_c      REAL,
            hum_rh      REAL,
            pres_hpa    REAL,
            flags       INTEGER,
            gw_ip       TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            triggered_at    TEXT NOT NULL,
            sid             INTEGER,
            param           TEXT,
            value           REAL,
            threshold       TEXT,
            acknowledged    INTEGER DEFAULT 0,
            acknowledged_at TEXT
        )
    """)
    # Migration colonnes manquantes (base existante)
    for col, default in [("acknowledged", "INTEGER DEFAULT 0"),
                         ("acknowledged_at", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE alert_log ADD COLUMN {col} {default}")
        except Exception:
            pass

    conn.execute("CREATE INDEX IF NOT EXISTS idx_received_at ON measurements(received_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sid         ON measurements(sid)")
    conn.commit()
    conn.close()
    print(f"[DB] Base initialisée : {os.path.abspath(DB_PATH)}")


# ── Écriture ─────────────────────────────────

def insert_measurement(data: dict, received_at: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO measurements (received_at, ts, sid, temp_c, hum_rh, pres_hpa, flags, gw_ip)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        received_at, data.get("ts"), data.get("sid"),
        data.get("temp_c"), data.get("hum_rh"), data.get("pres_hpa"),
        data.get("flags"), data.get("gw_ip"),
    ))
    conn.commit()
    conn.close()


def check_and_log_alerts(data: dict, received_at: str) -> list:
    sid = data.get("sid")
    if sid not in THRESHOLDS:
        return []
    alerts = []
    conn = sqlite3.connect(DB_PATH)
    for param, (vmin, vmax) in THRESHOLDS[sid].items():
        value = data.get(param)
        if value is None:
            continue
        if value < vmin or value > vmax:
            threshold_str = f"[{vmin}, {vmax}]"
            conn.execute(
                """INSERT INTO alert_log
                   (triggered_at, sid, param, value, threshold, acknowledged)
                   VALUES (?,?,?,?,?,0)""",
                (received_at, sid, param, value, threshold_str)
            )
            alerts.append({"sid": sid, "param": param,
                            "value": value, "threshold": threshold_str})
            print(f"[ALARME] sid={sid} {param}={value} hors seuil {threshold_str}")
    conn.commit()
    conn.close()
    return alerts


def acknowledge_alert(alert_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE alert_log SET acknowledged=1, acknowledged_at=? WHERE id=?",
        (datetime.now().isoformat(), alert_id)
    )
    conn.commit()
    conn.close()


def acknowledge_all_alerts() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE alert_log SET acknowledged=1, acknowledged_at=? WHERE acknowledged=0",
        (datetime.now().isoformat(),)
    )
    affected = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()
    return affected


# ── Lecture ──────────────────────────────────

def query_stats() -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT m.* FROM measurements m
        INNER JOIN (
            SELECT sid, MAX(received_at) as last FROM measurements GROUP BY sid
        ) latest ON m.sid = latest.sid AND m.received_at = latest.last
        ORDER BY m.sid
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_alerts(limit: int = 50, only_active: bool = False) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if only_active:
        rows = conn.execute(
            "SELECT * FROM alert_log WHERE acknowledged=0 ORDER BY triggered_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM alert_log ORDER BY triggered_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_history(sid: int, hours: int = 24) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows = conn.execute("""
        SELECT received_at, temp_c, hum_rh, pres_hpa
        FROM measurements
        WHERE sid = ? AND received_at >= ?
        ORDER BY received_at ASC LIMIT 500
    """, (sid, since)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_measurements(hours=None, sid=None, limit=100) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conditions, params = [], []
    if hours:
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        conditions.append("received_at >= ?")
        params.append(since)
    if sid:
        conditions.append("sid = ?")
        params.append(sid)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM measurements {where} ORDER BY received_at DESC LIMIT ?", params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_measurements() -> int:
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    conn.close()
    return count