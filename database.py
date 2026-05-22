"""
database.py — Toute la logique SQLite pour HMRA Monitor
"""

import sqlite3
import os
from datetime import datetime, timedelta
from config import DB_PATH, THRESHOLDS, SENSOR_NAMES


# ── Initialisation ────────────────────────────────────────────────────────────

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS units (
            unit_id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name                  TEXT NOT NULL,
            unit_type             TEXT,
            service_utilisation   TEXT,
            service_responsable   TEXT,
            created_at            TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_config (
            sid                   INTEGER PRIMARY KEY,
            mode                  TEXT NOT NULL DEFAULT "active",
            deleted               INTEGER DEFAULT 0,
            note                  TEXT,
            unit_id               INTEGER,
            name                  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thresholds (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sid         INTEGER NOT NULL,
            param       TEXT NOT NULL,
            vmin        REAL NOT NULL,
            vmax        REAL NOT NULL,
            updated_at  TEXT NOT NULL,
            UNIQUE(sid, param)
        )
    """)

    # Migration colonnes manquantes (base existante)
    migrations = [
    ("alert_log",    "acknowledged",    "INTEGER DEFAULT 0"),
    ("alert_log",    "acknowledged_at", "TEXT"),
    ("alert_log",    "auto_resolved",   "INTEGER DEFAULT 0"),
    ("alert_log",    "resolved_at",     "TEXT"),
    ("sensor_config","unit_id",         "INTEGER"),
    ("sensor_config","mode",            "TEXT DEFAULT 'active'"),
    ("sensor_config","name",            "TEXT"),
    ]

    for table, col, default in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {default}")
        except Exception:
            pass

    conn.execute("CREATE INDEX IF NOT EXISTS idx_received_at  ON measurements(received_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sid          ON measurements(sid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_unit      ON sensor_config(unit_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thr_sid      ON thresholds(sid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_mode      ON sensor_config(mode)")
    conn.commit()
    conn.close()

    # Seeder les seuils depuis config.py (uniquement les absents)
    _seed_thresholds()
    # Seeder les noms depuis config.py (uniquement si pas encore de nom en base)
    _seed_sensor_names()
    print(f"[DB] Base initialisée : {os.path.abspath(DB_PATH)}")


def _seed_sensor_names():
    """
    Insere les noms de SENSOR_NAMES une seule fois (premiere init).
    Si le flag sensor_names_seeded est deja en base, ne fait rien.
    Les suppressions faites par l'utilisateur ne sont donc jamais ecrasees.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    already = conn.execute(
        "SELECT 1 FROM meta WHERE key = 'sensor_names_seeded'"
    ).fetchone()
    if not already:
        for sid, name in SENSOR_NAMES.items():
            conn.execute("""
                INSERT INTO sensor_config (sid, name)
                VALUES (?, ?)
                ON CONFLICT(sid) DO UPDATE SET
                    name = CASE
                        WHEN sensor_config.name IS NULL OR sensor_config.name = ''
                        THEN excluded.name
                        ELSE sensor_config.name
                    END
            """, (sid, name))
        conn.execute("INSERT INTO meta (key, value) VALUES ('sensor_names_seeded', '1')")
        print("[DB] Seed noms capteurs effectue (premiere init)")
    conn.commit()
    conn.close()


def _seed_thresholds():
    """
    Insère dans la table thresholds les seuils définis dans config.py
    pour les couples (sid, param) qui n'existent pas encore en base.
    Les valeurs déjà modifiées via le dashboard ne sont PAS écrasées.
    """
    now  = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    for sid, params in THRESHOLDS.items():
        for param, (vmin, vmax) in params.items():
            conn.execute("""
                INSERT INTO thresholds (sid, param, vmin, vmax, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sid, param) DO NOTHING
            """, (sid, param, vmin, vmax, now))
    conn.commit()
    conn.close()


# ── Écriture mesures ──────────────────────────────────────────────────────────

def insert_measurement(data: dict, received_at: str):
    sid = data.get("sid")
    conn = sqlite3.connect(DB_PATH)
    # Enregistrer automatiquement le capteur s'il est inconnu
    conn.execute("""
        INSERT INTO sensor_config (sid, mode)
        VALUES (?, 'active')
        ON CONFLICT(sid) DO NOTHING
    """, (sid,))
    conn.execute("""
        INSERT INTO measurements (received_at, ts, sid, temp_c, hum_rh, pres_hpa, flags, gw_ip)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        received_at, data.get("ts"), sid,
        data.get("temp_c"), data.get("hum_rh"), data.get("pres_hpa"),
        data.get("flags"), data.get("gw_ip"),
    ))
    conn.commit()
    conn.close()


def check_and_log_alerts(data: dict, received_at: str) -> list:
    sid = data.get("sid")
    alerts = []
    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute(
        "SELECT param, vmin, vmax FROM thresholds WHERE sid = ?", (sid,)
    ).fetchall()

    if not rows:
        conn.close()
        return []

    for param, vmin, vmax in rows:
        value = data.get(param)
        if value is None:
            continue

        is_out = value < vmin or value > vmax
        threshold_str = f"[{vmin}, {vmax}]"

        # Cherche une alarme active (non acquittée) pour ce (sid, param)
        active = conn.execute("""
            SELECT id FROM alert_log
            WHERE sid=? AND param=? AND acknowledged=0
            ORDER BY triggered_at DESC LIMIT 1
        """, (sid, param)).fetchone()

        if is_out:
            if not active:
                # Nouvelle alarme — on insère UNE SEULE FOIS
                conn.execute("""
                    INSERT INTO alert_log
                    (triggered_at, sid, param, value, threshold, acknowledged)
                    VALUES (?,?,?,?,?,0)
                """, (received_at, sid, param, value, threshold_str))
                alerts.append({"sid": sid, "param": param,
                                "value": value, "threshold": threshold_str})
                print(f"[ALARME] sid={sid} {param}={value} hors seuil {threshold_str}")
            # else: alarme déjà ouverte → on ne crée pas de doublon

        else:
            if active:
                # Capteur revenu dans les seuils → auto-ack
                conn.execute("""
                    UPDATE alert_log
                    SET acknowledged=1,
                        acknowledged_at=?,
                        auto_resolved=1,
                        resolved_at=?
                    WHERE id=?
                """, (received_at, received_at, active[0]))
                print(f"[AUTO-ACK] sid={sid} {param}={value} revenu OK → alarme #{active[0]} clôturée automatiquement")

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


# ── Gestion des seuils ────────────────────────────────────────────────────────

def get_all_thresholds() -> dict:
    """
    Retourne {sid: {param: {"vmin": float, "vmax": float, "updated_at": str}}}
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT sid, param, vmin, vmax, updated_at FROM thresholds ORDER BY sid, param"
    ).fetchall()
    conn.close()

    result = {}
    for sid, param, vmin, vmax, updated_at in rows:
        result.setdefault(sid, {})[param] = {
            "vmin": vmin, "vmax": vmax, "updated_at": updated_at
        }
    return result


def get_thresholds_for_sensor(sid: int) -> dict:
    """Retourne {param: {"vmin": float, "vmax": float, "updated_at": str}} pour un sid."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT param, vmin, vmax, updated_at FROM thresholds WHERE sid = ?", (sid,)
    ).fetchall()
    conn.close()
    return {
        param: {"vmin": vmin, "vmax": vmax, "updated_at": updated_at}
        for param, vmin, vmax, updated_at in rows
    }


def set_threshold(sid: int, param: str, vmin: float, vmax: float):
    """Met à jour ou crée un seuil pour un (sid, param)."""
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO thresholds (sid, param, vmin, vmax, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sid, param) DO UPDATE SET
            vmin       = excluded.vmin,
            vmax       = excluded.vmax,
            updated_at = excluded.updated_at
    """, (sid, param, vmin, vmax, now))
    conn.commit()
    conn.close()
    print(f"[THR] sid={sid} {param} → [{vmin}, {vmax}]")


def reset_thresholds_to_defaults(sid: int = None):
    """
    Réinitialise les seuils depuis config.py.
    Si sid est fourni, réinitialise uniquement ce capteur.
    Sinon, réinitialise tous les capteurs.
    """
    now  = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    targets = {sid: THRESHOLDS[sid]} if sid and sid in THRESHOLDS else THRESHOLDS
    for s, params in targets.items():
        for param, (vmin, vmax) in params.items():
            conn.execute("""
                INSERT INTO thresholds (sid, param, vmin, vmax, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sid, param) DO UPDATE SET
                    vmin = excluded.vmin, vmax = excluded.vmax,
                    updated_at = excluded.updated_at
            """, (s, param, vmin, vmax, now))
    conn.commit()
    conn.close()
    scope = f"sid={sid}" if sid else "tous les capteurs"
    print(f"[THR] Seuils réinitialisés depuis config.py ({scope})")


# ── Gestion des unités ────────────────────────────────────────────────────────

def get_all_units() -> list:
    """Retourne toutes les unités avec la liste des sid qui leur sont associés."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    units = conn.execute("SELECT * FROM units ORDER BY name ASC").fetchall()

    sids_map = {}
    for r in conn.execute(
        "SELECT unit_id, sid FROM sensor_config WHERE unit_id IS NOT NULL AND deleted = 0"
    ).fetchall():
        sids_map.setdefault(r[0], []).append(r[1])

    conn.close()
    result = []
    for u in units:
        d = dict(u)
        d["sids"] = sids_map.get(u["unit_id"], [])
        result.append(d)
    return result


def get_unit(unit_id: int):
    """Retourne une unité par son id avec ses sid associés, ou None."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    unit = conn.execute(
        "SELECT * FROM units WHERE unit_id = ?", (unit_id,)
    ).fetchone()
    if not unit:
        conn.close()
        return None

    sids = [r[0] for r in conn.execute(
        "SELECT sid FROM sensor_config WHERE unit_id = ? AND deleted = 0",
        (unit_id,)
    ).fetchall()]

    conn.close()
    d = dict(unit)
    d["sids"] = sids
    return d


def create_unit(name: str, unit_type: str,
                service_utilisation: str, service_responsable: str) -> dict:
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""
        INSERT INTO units (name, unit_type, service_utilisation, service_responsable, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (name, unit_type, service_utilisation, service_responsable, now))
    unit_id = cur.lastrowid
    conn.commit()
    conn.close()
    print(f"[UNIT] Créée : unit_id={unit_id} — {name} ({unit_type})")
    return {
        "unit_id": unit_id, "name": name, "unit_type": unit_type,
        "service_utilisation": service_utilisation,
        "service_responsable": service_responsable,
        "created_at": now, "sids": []
    }


def update_unit(unit_id: int, name: str, unit_type: str,
                service_utilisation: str, service_responsable: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""
        UPDATE units
        SET name = ?, unit_type = ?, service_utilisation = ?, service_responsable = ?
        WHERE unit_id = ?
    """, (name, unit_type, service_utilisation, service_responsable, unit_id))
    found = cur.rowcount > 0
    conn.commit()
    conn.close()
    if found:
        print(f"[UNIT] Modifiée : unit_id={unit_id} — {name}")
    return found


def delete_unit(unit_id: int):
    """Supprime une unité et désassigne ses capteurs."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE sensor_config SET unit_id = NULL WHERE unit_id = ?", (unit_id,)
    )
    conn.execute("DELETE FROM units WHERE unit_id = ?", (unit_id,))
    conn.commit()
    conn.close()
    print(f"[UNIT] Supprimée : unit_id={unit_id}")


def assign_sensor_to_unit(sid: int, unit_id):
    """Assigne ou désassigne un capteur d'une unité."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO sensor_config (sid, unit_id)
        VALUES (?, ?)
        ON CONFLICT(sid) DO UPDATE SET unit_id = excluded.unit_id
    """, (sid, unit_id))
    conn.commit()
    conn.close()
    if unit_id is not None:
        print(f"[UNIT] sid={sid} assigné à unit_id={unit_id}")
    else:
        print(f"[UNIT] sid={sid} désassigné de son unité")


# ── Gestion des capteurs (activation / suppression) ───────────────────────────

def get_sensor_config() -> dict:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT sid, mode, deleted, note, unit_id, name FROM sensor_config"
    ).fetchall()
    conn.close()

    return {
        r[0]: {
            "mode":    r[1] if r[1] else "active",
            "deleted": bool(r[2]),
            "note":    r[3],
            "unit_id": r[4],
            "name":    r[5],
        }
        for r in rows
    }


def set_sensor_mode(sid: int, mode: str, note: str = None):
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        INSERT INTO sensor_config (sid, mode, note)
        VALUES (?, ?, ?)
        ON CONFLICT(sid) DO UPDATE SET
            mode = excluded.mode,
            note = COALESCE(excluded.note, sensor_config.note)
    """, (sid, mode, note))

    conn.commit()
    conn.close()


def rename_sensor(sid: int, name: str):
    """Renomme un capteur. Crée la ligne sensor_config si elle n'existe pas."""
    name = name.strip()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO sensor_config (sid, name)
        VALUES (?, ?)
        ON CONFLICT(sid) DO UPDATE SET name = excluded.name
    """, (sid, name))
    conn.commit()
    conn.close()
    print(f"[CFG] Capteur sid={sid} renommé → '{name}'")


def delete_sensor(sid: int):
    """Suppression définitive : efface config, mesures et alarmes du capteur."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM sensor_config WHERE sid = ?", (sid,))
    conn.execute("DELETE FROM measurements WHERE sid = ?", (sid,))
    conn.execute("DELETE FROM alert_log WHERE sid = ?", (sid,))
    conn.execute("DELETE FROM thresholds WHERE sid = ?", (sid,))
    conn.commit()
    conn.close()
    print(f"[CFG] Capteur sid={sid} supprimé définitivement")





# ── Lecture mesures ───────────────────────────────────────────────────────────

def query_stats() -> list:
    """
    Retourne la dernière mesure par capteur, enrichie des infos
    d'unité et des seuils actifs.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT m.*,
               u.unit_id,
               u.name                AS unit_name,
               u.unit_type           AS unit_type,
               u.service_utilisation AS unit_service_utilisation,
               u.service_responsable AS unit_service_responsable
        FROM measurements m
        INNER JOIN (
            SELECT sid, MAX(received_at) AS last FROM measurements GROUP BY sid
        ) latest ON m.sid = latest.sid AND m.received_at = latest.last
        INNER JOIN sensor_config sc ON sc.sid = m.sid
        LEFT JOIN units u           ON u.unit_id = sc.unit_id
        ORDER BY m.sid
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_alerts(limit: int = 50, only_active: bool = False) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if only_active:
        rows = conn.execute(
            "SELECT * FROM alert_log WHERE acknowledged=0 "
            "ORDER BY triggered_at DESC LIMIT ?", (limit,)
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
        f"SELECT * FROM measurements {where} ORDER BY received_at DESC LIMIT ?",
        params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_measurements() -> int:
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    conn.close()
    return count