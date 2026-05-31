"""
analyse_capteurs.py
────────────────────────────────────────────────────────────────────
Analyse comparative des capteurs sur la nuit de mesure (16h→8h30)

Configuration :
  STHP01A  Sid=1        → Frigo  (temp + humidité)
  XYMD04   Sid=2        → Frigo  (temp + humidité)
  PT100    Sid=49 (3<<4|1) → Frigo  (temp uniquement)
  PT100    Sid=50 (3<<4|2) → Congélateur (temp uniquement)
  XYMD04   Sid=4        → Congélateur (temp + humidité)

Usage :
  python analyse_capteurs.py                    # analyse les dernières 20h
  python analyse_capteurs.py --hours 18         # personnaliser la durée
  python analyse_capteurs.py --from "2025-01-01 16:00" --to "2025-01-02 08:30"

Sorties :
  - Console : statistiques (moyenne, écart-type, min/max, dérive)
  - Graphes interactifs matplotlib
  - analyse_rapport.csv : export des données brutes rééchantillonnées
"""

import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import argparse
from datetime import datetime, timedelta

# ── CONFIG ──────────────────────────────────────────────────────────
DB_PATH = "hmra_monitor.db"

# Décodage des sensor_id
# PT100 : sid = (slave_id << 4) | canal  →  slave 3, ch1 = 49, ch2 = 50
SENSORS = {
    1:  {"label": "STHP01A",    "emplacement": "Frigo",       "type": "SHT31",   "precision_T": 0.3, "precision_H": 2.0},
    2:  {"label": "XYMD04",     "emplacement": "Frigo",       "type": "SHT40",   "precision_T": 0.3, "precision_H": 3.0},
    49: {"label": "PT100 ch1",  "emplacement": "Frigo",       "type": "PT100",   "precision_T": 0.5, "precision_H": None},
    50: {"label": "PT100 ch2",  "emplacement": "Congélateur", "type": "PT100",   "precision_T": 0.5, "precision_H": None},
    4:  {"label": "XYMD04",     "emplacement": "Congélateur", "type": "SHT40",   "precision_T": 0.3, "precision_H": 3.0},
}

COLORS = {
    1:  "#2196F3",   # bleu
    2:  "#FF9800",   # orange
    49: "#4CAF50",   # vert
    50: "#9C27B0",   # violet
    4:  "#F44336",   # rouge
}

RESAMPLE = "5min"   # rééchantillonnage pour lisser les graphes


# ── CHARGEMENT DES DONNÉES ──────────────────────────────────────────

def load_data(db_path: str, hours: float = 20,
              dt_from: str = None, dt_to: str = None) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)

    if dt_from and dt_to:
        # Normalise le format pour matcher "2026-05-30T16:00:00"
        dt_from = dt_from.replace(" ", "T")
        dt_to   = dt_to.replace(" ", "T")
        # Ajoute les secondes si manquantes
        if len(dt_from) == 16: dt_from += ":00"
        if len(dt_to)   == 16: dt_to   += ":00"

        query = """
            SELECT received_at, sid, temp_c, hum_rh
            FROM measurements
            WHERE received_at >= ? AND received_at <= ?
            ORDER BY received_at ASC
        """
        df = pd.read_sql_query(query, conn, params=(dt_from, dt_to))
    else:
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        query = """
            SELECT received_at, sid, temp_c, hum_rh
            FROM measurements
            WHERE received_at >= ?
            ORDER BY received_at ASC
        """
        df = pd.read_sql_query(query, conn, params=(since,))

    conn.close()
    df["received_at"] = pd.to_datetime(df["received_at"])
    return df


# ── STATISTIQUES ────────────────────────────────────────────────────

def print_stats(df: pd.DataFrame):
    print("\n" + "═"*70)
    print("  STATISTIQUES PAR CAPTEUR")
    print("═"*70)

    for sid, info in SENSORS.items():
        sub = df[df["sid"] == sid].dropna(subset=["temp_c"])
        if sub.empty:
            print(f"\n  [{info['label']} – {info['emplacement']}]  ⚠ Aucune donnée")
            continue

        t = sub["temp_c"]
        print(f"\n  [{info['label']} – {info['emplacement']}] ({info['type']})")
        print(f"    Nb mesures    : {len(t)}")
        print(f"    Période       : {sub['received_at'].min().strftime('%d/%m %H:%M')} → "
              f"{sub['received_at'].max().strftime('%d/%m %H:%M')}")
        print(f"    Température   : moy={t.mean():.2f}°C  std={t.std():.3f}°C  "
              f"min={t.min():.2f}°C  max={t.max():.2f}°C  "
              f"Δ={t.max()-t.min():.2f}°C")
        print(f"    Précision fab.: ±{info['precision_T']}°C")

        if info["precision_H"] is not None:
            h = sub["hum_rh"].dropna()
            if not h.empty:
                print(f"    Humidité      : moy={h.mean():.1f}%  std={h.std():.2f}%  "
                      f"min={h.min():.1f}%  max={h.max():.1f}%")
                print(f"    Précision fab.: ±{info['precision_H']}% RH")

    # Comparaison inter-capteurs sur le frigo
    print("\n" + "─"*70)
    print("  COMPARAISON TEMPÉRATURE FRIGO (Sid 1 vs 2 vs 49)")
    sids_frigo = [1, 2, 49]
    frames = {}
    for sid in sids_frigo:
        sub = df[df["sid"] == sid][["received_at", "temp_c"]].dropna()
        sub = sub.set_index("received_at").resample(RESAMPLE)["temp_c"].mean()
        frames[sid] = sub

    combined = pd.DataFrame(frames).dropna()
    if not combined.empty:
        for (a, b) in [(1, 2), (1, 49), (2, 49)]:
            if a in combined and b in combined:
                diff = combined[a] - combined[b]
                la, lb = SENSORS[a]["label"], SENSORS[b]["label"]
                print(f"    {la} – {lb}: biais moy={diff.mean():.3f}°C  "
                      f"max écart={diff.abs().max():.3f}°C  std={diff.std():.3f}°C")
    else:
        print("    (pas assez de données simultanées pour comparer)")

    # Comparaison congélateur
    print("\n" + "─"*70)
    print("  COMPARAISON TEMPÉRATURE CONGÉLATEUR (Sid 4 vs 50)")
    sids_cong = [4, 50]
    frames2 = {}
    for sid in sids_cong:
        sub = df[df["sid"] == sid][["received_at", "temp_c"]].dropna()
        sub = sub.set_index("received_at").resample(RESAMPLE)["temp_c"].mean()
        frames2[sid] = sub

    combined2 = pd.DataFrame(frames2).dropna()
    if not combined2.empty:
        diff2 = combined2[4] - combined2[50]
        print(f"    XYMD04 – PT100 ch2: biais moy={diff2.mean():.3f}°C  "
              f"max écart={diff2.abs().max():.3f}°C  std={diff2.std():.3f}°C")
    else:
        print("    (pas assez de données simultanées)")

    print("\n" + "═"*70)


# ── GRAPHES ─────────────────────────────────────────────────────────

def plot_temperature(df: pd.DataFrame):
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    fig.suptitle("Comparaison température – Frigo & Congélateur", fontsize=14, fontweight="bold")

    # Frigo
    ax1 = axes[0]
    ax1.set_title("Frigo — Sid 1 (STHP01A), Sid 2 (XYMD04), Sid 49 (PT100 ch1)", fontsize=11)
    for sid in [1, 2, 49]:
        sub = df[df["sid"] == sid][["received_at", "temp_c"]].dropna()
        if sub.empty:
            continue
        sub = sub.set_index("received_at").resample(RESAMPLE)["temp_c"].mean()
        label = f"{SENSORS[sid]['label']} (±{SENSORS[sid]['precision_T']}°C)"
        ax1.plot(sub.index, sub.values, color=COLORS[sid], label=label, linewidth=1.2)
        # Bande de précision
        ax1.fill_between(sub.index,
                         sub.values - SENSORS[sid]["precision_T"],
                         sub.values + SENSORS[sid]["precision_T"],
                         color=COLORS[sid], alpha=0.07)
    ax1.set_ylabel("Température (°C)")
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(True, alpha=0.3)

    # Congélateur
    ax2 = axes[1]
    ax2.set_title("Congélateur — Sid 4 (XYMD04), Sid 50 (PT100 ch2)", fontsize=11)
    for sid in [4, 50]:
        sub = df[df["sid"] == sid][["received_at", "temp_c"]].dropna()
        if sub.empty:
            continue
        sub = sub.set_index("received_at").resample(RESAMPLE)["temp_c"].mean()
        label = f"{SENSORS[sid]['label']} (±{SENSORS[sid]['precision_T']}°C)"
        ax2.plot(sub.index, sub.values, color=COLORS[sid], label=label, linewidth=1.2)
        ax2.fill_between(sub.index,
                         sub.values - SENSORS[sid]["precision_T"],
                         sub.values + SENSORS[sid]["precision_T"],
                         color=COLORS[sid], alpha=0.07)
    ax2.set_ylabel("Température (°C)")
    ax2.legend(loc="upper right", fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax2.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.xticks(rotation=45)
    plt.xlabel("Heure")
    plt.tight_layout()
    plt.savefig("graph_temperature.png", dpi=150)
    print("  ✓ graph_temperature.png sauvegardé")
    plt.show()


def plot_humidity(df: pd.DataFrame):
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    fig.suptitle("Humidité relative – Frigo & Congélateur", fontsize=14, fontweight="bold")

    for ax, sid, title in [
        (axes[0], [1, 2],  "Frigo — Sid 1 (STHP01A), Sid 2 (XYMD04)"),
        (axes[1], [4],     "Congélateur — Sid 4 (XYMD04)"),
    ]:
        ax.set_title(title, fontsize=11)
        for s in sid:
            sub = df[df["sid"] == s][["received_at", "hum_rh"]].dropna()
            if sub.empty:
                continue
            sub = sub.set_index("received_at").resample(RESAMPLE)["hum_rh"].mean()
            label = f"{SENSORS[s]['label']} (±{SENSORS[s]['precision_H']}% RH)"
            ax.plot(sub.index, sub.values, color=COLORS[s], label=label, linewidth=1.2)
        ax.set_ylabel("Humidité (%RH)")
        ax.legend(loc="upper right", fontsize=9)
        ax.grid(True, alpha=0.3)

    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    axes[1].xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.xticks(rotation=45)
    plt.xlabel("Heure")
    plt.tight_layout()
    plt.savefig("graph_humidite.png", dpi=150)
    print("  ✓ graph_humidite.png sauvegardé")
    plt.show()


def plot_diff_frigo(df: pd.DataFrame):
    """Graphe d'écart entre capteurs du frigo — révèle les biais systématiques."""
    frames = {}
    for sid in [1, 2, 49]:
        sub = df[df["sid"] == sid][["received_at", "temp_c"]].dropna()
        if sub.empty:
            continue
        frames[sid] = sub.set_index("received_at").resample(RESAMPLE)["temp_c"].mean()

    combined = pd.DataFrame(frames).dropna()
    if combined.empty:
        return

    fig, ax = plt.subplots(figsize=(14, 4))
    ax.set_title("Écarts de température entre capteurs Frigo (référence = STHP01A)", fontsize=11)

    for sid, color, name in [(2, COLORS[2], "XYMD04 – STHP01A"),
                              (49, COLORS[49], "PT100 ch1 – STHP01A")]:
        if sid in combined:
            diff = combined[sid] - combined[1]
            ax.plot(diff.index, diff.values, color=color, label=name, linewidth=1.2)

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.axhline(0.3,  color="gray", linewidth=0.5, linestyle=":")
    ax.axhline(-0.3, color="gray", linewidth=0.5, linestyle=":", label="±0.3°C limite")
    ax.set_ylabel("Écart (°C)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("graph_ecarts_frigo.png", dpi=150)
    print("  ✓ graph_ecarts_frigo.png sauvegardé")
    plt.show()


def export_csv(df: pd.DataFrame):
    """Export rééchantillonné par capteur, pivot large."""
    pivots = []
    for sid, info in SENSORS.items():
        sub = df[df["sid"] == sid][["received_at", "temp_c", "hum_rh"]].dropna(subset=["temp_c"])
        if sub.empty:
            continue
        sub = sub.set_index("received_at").resample(RESAMPLE).mean()
        sub.columns = [f"{info['label']}_{info['emplacement']}_T",
                       f"{info['label']}_{info['emplacement']}_H"]
        pivots.append(sub)

    if pivots:
        out = pd.concat(pivots, axis=1)
        out.to_csv("analyse_rapport.csv")
        print("  ✓ analyse_rapport.csv sauvegardé")


# ── MAIN ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyse comparative capteurs HMRA")
    parser.add_argument("--hours", type=float, default=20,
                        help="Nombre d'heures de données à analyser (défaut: 20)")
    parser.add_argument("--from", dest="dt_from", default=None,
                        help="Date/heure début ex: '2025-01-01 16:00'")
    parser.add_argument("--to", dest="dt_to", default=None,
                        help="Date/heure fin ex: '2025-01-02 08:30'")
    parser.add_argument("--no-plot", action="store_true",
                        help="Désactiver les graphes (stats seules)")
    args = parser.parse_args()

    print(f"\nChargement des données depuis {DB_PATH}...")
    df = load_data(DB_PATH, hours=args.hours, dt_from=args.dt_from, dt_to=args.dt_to)

    if df.empty:
        print("❌ Aucune donnée trouvée dans la base pour cette période.")
        return

    print(f"  {len(df)} mesures chargées "
          f"({df['received_at'].min().strftime('%d/%m %H:%M')} → "
          f"{df['received_at'].max().strftime('%d/%m %H:%M')})")

    # Statistiques console
    print_stats(df)

    # Export CSV
    export_csv(df)

    if not args.no_plot:
        plot_temperature(df)
        plot_humidity(df)
        plot_diff_frigo(df)


if __name__ == "__main__":
    main()