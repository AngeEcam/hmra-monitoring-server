"""
database.py — Toute la logique SQLite pour HMRA Monitor
"""

import sqlite3
import os
from datetime import datetime, timedelta
from config import DB_PATH


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
            acknowledged_at TEXT,
            auto_resolved   INTEGER DEFAULT 0,
            resolved_at     TEXT
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
            sid     INTEGER PRIMARY KEY,
            mode    TEXT NOT NULL DEFAULT 'active',
            deleted INTEGER DEFAULT 0,
            note    TEXT,
            unit_id INTEGER,
            name    TEXT
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # ── Table utilisateurs ────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role         TEXT NOT NULL DEFAULT 'user',
            service      TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT
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

    print(f"[DB] Base initialisée : {os.path.abspath(DB_PATH)}")


def ensure_superadmin(username: str, password_hash: str):
    """
    Crée le compte superadmin s'il n'existe pas encore.
    Appelé au démarrage depuis main.py.
    """
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute(
        "SELECT id FROM users WHERE role = 'superadmin' LIMIT 1"
    ).fetchone()
    if not existing:
        now = datetime.now().isoformat()
        conn.execute("""
            INSERT INTO users (username, password_hash, role, service, created_at)
            VALUES (?, ?, 'superadmin', NULL, ?)
        """, (username, password_hash, now))
        conn.commit()
        print(f"[AUTH] Compte superadmin '{username}' créé")
    conn.close()


# ── CRUD utilisateurs ─────────────────────────────────────────────────────────

def get_user_by_username(username: str):
    """Retourne l'utilisateur correspondant au username, ou None."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users() -> list:
    """Retourne tous les utilisateurs (sans le hash du mot de passe)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, username, role, service, created_at, updated_at FROM users ORDER BY username"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(username: str, password_hash: str, role: str, service: str) -> dict:
    """Crée un nouvel utilisateur. Lève ValueError si le username existe déjà."""
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("""
            INSERT INTO users (username, password_hash, role, service, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (username, password_hash, role, service or None, now))
        user_id = cur.lastrowid
        conn.commit()
        print(f"[AUTH] Utilisateur créé : {username} (role={role}, service={service})")
        return {
            "id": user_id, "username": username,
            "role": role, "service": service, "created_at": now
        }
    except sqlite3.IntegrityError:
        raise ValueError(f"Le nom d'utilisateur '{username}' est déjà pris")
    finally:
        conn.close()


def update_user(user_id: int, username: str = None, password_hash: str = None,
                role: str = None, service: str = None) -> bool:
    """Met à jour les champs non-None d'un utilisateur. Retourne True si trouvé."""
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now().isoformat()

    fields, params = [], []
    if username is not None:
        fields.append("username = ?")
        params.append(username)
    if password_hash is not None:
        fields.append("password_hash = ?")
        params.append(password_hash)
    if role is not None:
        fields.append("role = ?")
        params.append(role)
    if service is not None:
        fields.append("service = ?")
        params.append(service if service != "" else None)

    if not fields:
        conn.close()
        return False

    fields.append("updated_at = ?")
    params.append(now)
    params.append(user_id)

    cur = conn.execute(
        f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params
    )
    found = cur.rowcount > 0
    conn.commit()
    conn.close()
    return found


def delete_user(user_id: int) -> bool:
    """Supprime un utilisateur. Retourne True si trouvé."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("DELETE FROM users WHERE id = ? AND role != 'superadmin'", (user_id,))
    found = cur.rowcount > 0
    conn.commit()
    conn.close()
    return found


def reset_user_password(user_id: int, new_hash: str) -> bool:
    """Réinitialise le mot de passe d'un utilisateur."""
    return update_user(user_id, password_hash=new_hash)


# ── Écriture mesures ──────────────────────────────────────────────────────────

def _pt100_default_name(sid: int):
    if sid is not None and sid >= 16:
        slave_id = sid >> 4
        canal    = sid & 0xF
        return f"PT100 slave {slave_id} canal {canal}"
    return None


def insert_measurement(data: dict, received_at: str):
    sid  = data.get("sid")
    name = _pt100_default_name(sid)
    conn = sqlite3.connect(DB_PATH)
    if name:
        conn.execute("""
            INSERT INTO sensor_config (sid, mode, name)
            VALUES (?, 'active', ?)
            ON CONFLICT(sid) DO UPDATE SET
                name = CASE
                    WHEN sensor_config.name IS NULL OR sensor_config.name = ''
                    THEN excluded.name
                    ELSE sensor_config.name
                END
        """, (sid, name))
    else:
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

        active = conn.execute("""
            SELECT id FROM alert_log
            WHERE sid=? AND param=? AND acknowledged=0
            ORDER BY triggered_at DESC LIMIT 1
        """, (sid, param)).fetchone()

        if is_out:
            if not active:
                conn.execute("""
                    INSERT INTO alert_log
                    (triggered_at, sid, param, value, threshold, acknowledged)
                    VALUES (?,?,?,?,?,0)
                """, (received_at, sid, param, value, threshold_str))
                alerts.append({"sid": sid, "param": param,
                                "value": value, "threshold": threshold_str})
        else:
            if active:
                conn.execute("""
                    UPDATE alert_log
                    SET acknowledged=1, acknowledged_at=?, auto_resolved=1, resolved_at=?
                    WHERE id=?
                """, (received_at, received_at, active[0]))

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
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO thresholds (sid, param, vmin, vmax, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sid, param) DO UPDATE SET
            vmin=excluded.vmin, vmax=excluded.vmax, updated_at=excluded.updated_at
    """, (sid, param, vmin, vmax, now))
    conn.commit()
    conn.close()


# ── Gestion des unités ────────────────────────────────────────────────────────

def get_all_units(service_filter: str = None) -> list:
    """
    Retourne toutes les unités avec leurs sid associés.
    Si service_filter est fourni, ne retourne que les unités dont
    service_utilisation OU service_responsable correspond.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if service_filter:
        units = conn.execute("""
            SELECT * FROM units
            WHERE service_utilisation = ? OR service_responsable = ?
            ORDER BY name ASC
        """, (service_filter, service_filter)).fetchall()
    else:
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    unit = conn.execute(
        "SELECT * FROM units WHERE unit_id = ?", (unit_id,)
    ).fetchone()
    if not unit:
        conn.close()
        return None
    sids = [r[0] for r in conn.execute(
        "SELECT sid FROM sensor_config WHERE unit_id = ? AND deleted = 0", (unit_id,)
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
        SET name=?, unit_type=?, service_utilisation=?, service_responsable=?
        WHERE unit_id=?
    """, (name, unit_type, service_utilisation, service_responsable, unit_id))
    found = cur.rowcount > 0
    conn.commit()
    conn.close()
    return found


def delete_unit(unit_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE sensor_config SET unit_id = NULL WHERE unit_id = ?", (unit_id,))
    conn.execute("DELETE FROM units WHERE unit_id = ?", (unit_id,))
    conn.commit()
    conn.close()


def assign_sensor_to_unit(sid: int, unit_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO sensor_config (sid, unit_id)
        VALUES (?, ?)
        ON CONFLICT(sid) DO UPDATE SET unit_id = excluded.unit_id
    """, (sid, unit_id))
    conn.commit()
    conn.close()


# ── Gestion des capteurs ──────────────────────────────────────────────────────

def get_sensor_config() -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM sensor_config WHERE deleted = 0").fetchall()
    conn.close()
    return {r["sid"]: dict(r) for r in rows}


def set_sensor_mode(sid: int, mode: str, note: str = None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO sensor_config (sid, mode, note)
        VALUES (?, ?, ?)
        ON CONFLICT(sid) DO UPDATE SET mode=excluded.mode, note=excluded.note
    """, (sid, mode, note))
    conn.commit()
    conn.close()


def rename_sensor(sid: int, name: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO sensor_config (sid, name)
        VALUES (?, ?)
        ON CONFLICT(sid) DO UPDATE SET name=excluded.name
    """, (sid, name))
    conn.commit()
    conn.close()


def delete_sensor(sid: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE sensor_config SET deleted=1, unit_id=NULL WHERE sid=?", (sid,))
    conn.execute("DELETE FROM measurements WHERE sid=?", (sid,))
    conn.execute("DELETE FROM alert_log WHERE sid=?", (sid,))
    conn.execute("DELETE FROM thresholds WHERE sid=?", (sid,))
    conn.commit()
    conn.close()


# ── Lecture mesures ───────────────────────────────────────────────────────────

def query_stats(service_filter: str = None) -> list:
    """
    Retourne la dernière mesure par capteur.
    Si service_filter est fourni, ne retourne que les capteurs
    appartenant à une unité de ce service.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if service_filter:
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
            INNER JOIN units u          ON u.unit_id = sc.unit_id
            WHERE (u.service_utilisation = ? OR u.service_responsable = ?)
            ORDER BY m.sid
        """, (service_filter, service_filter)).fetchall()
    else:
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


def query_alerts(limit: int = 50, only_active: bool = False,
                 service_filter: str = None) -> list:
    """
    Retourne les alarmes.
    Si service_filter est fourni, filtre sur les capteurs du service.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if service_filter:
        base = """
            SELECT al.*
            FROM alert_log al
            INNER JOIN sensor_config sc ON sc.sid = al.sid
            INNER JOIN units u          ON u.unit_id = sc.unit_id
            WHERE (u.service_utilisation = ? OR u.service_responsable = ?)
        """
        params = [service_filter, service_filter]
        if only_active:
            base += " AND al.acknowledged = 0"
        base += " ORDER BY al.triggered_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(base, params).fetchall()
    else:
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
    n = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    conn.close()
    return n