"""
notifier.py — Envoi d'alertes par email (SMTP Brevo)

Prérequis dans .env :
    SMTP_SENDER=alertes.hopital@outlook.com      # affiché dans le "De :"
    SMTP_LOGIN=acf9e0001@smtp-brevo.com          # login d'auth Brevo
    SMTP_PASSWORD=xsmtpsib-...                   # clé SMTP Brevo
"""

import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from config import SMTP_SENDER, SMTP_LOGIN, SMTP_PASSWORD

PARAM_LABELS = {
    "temp_c":   "Température",
    "hum_rh":   "Humidité",
    "pres_hpa": "Pression",
}
PARAM_UNITS = {
    "temp_c":   "°C",
    "hum_rh":   "%RH",
    "pres_hpa": "hPa",
}


def _build_html(sensor_name: str, sensor_id: int, alerts: list) -> str:
    now = datetime.now().strftime("%d/%m/%Y à %H:%M:%S")
    rows = ""
    for a in alerts:
        label = PARAM_LABELS.get(a["param"], a["param"])
        unit  = PARAM_UNITS.get(a["param"], "")
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #1e2d3d">{label}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #1e2d3d;color:#e74c3c;font-weight:bold">
            {a['value']:.1f} {unit}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #1e2d3d;color:#4a6070">
            {a['threshold']}
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,sans-serif">
  <div style="max-width:560px;margin:32px auto;background:#0d1219;border-radius:12px;
              overflow:hidden;border:1px solid #1e2d3d">
    <div style="background:#e74c3c;padding:20px 28px">
      <div style="color:#fff;font-size:1.1rem;font-weight:bold;letter-spacing:.05em">
        ⚠ ALERTE CAPTEUR — HMRA Monitor
      </div>
      <div style="color:#fcd0cc;font-size:.8rem;margin-top:4px">{now}</div>
    </div>
    <div style="padding:20px 28px 8px">
      <div style="color:#4a6070;font-size:.7rem;letter-spacing:.1em;text-transform:uppercase">Capteur</div>
      <div style="color:#c8d8e8;font-size:1rem;font-weight:bold;margin-top:4px">
        {sensor_name}
        <span style="color:#4a6070;font-size:.75rem;font-weight:normal"> — SID {sensor_id}</span>
      </div>
    </div>
    <div style="padding:8px 28px 20px">
      <table style="width:100%;border-collapse:collapse;color:#c8d8e8;font-size:.85rem">
        <thead>
          <tr style="background:#111820">
            <th style="padding:8px 12px;text-align:left;color:#4a6070;font-size:.7rem;letter-spacing:.08em;text-transform:uppercase">Paramètre</th>
            <th style="padding:8px 12px;text-align:left;color:#4a6070;font-size:.7rem;letter-spacing:.08em;text-transform:uppercase">Valeur mesurée</th>
            <th style="padding:8px 12px;text-align:left;color:#4a6070;font-size:.7rem;letter-spacing:.08em;text-transform:uppercase">Seuil autorisé</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div style="background:#080c10;padding:14px 28px;font-size:.72rem;color:#4a6070;border-top:1px solid #1e2d3d">
      Connectez-vous au dashboard HMRA Monitor pour acquitter cette alarme.
    </div>
  </div>
</body>
</html>"""


def _send(recipients: list[str], sensor_name: str, sensor_id: int, alerts: list):
    if not SMTP_LOGIN or not SMTP_PASSWORD:
        print("[NOTIFIER] SMTP non configuré (SMTP_LOGIN / SMTP_PASSWORD manquants)")
        return
    if not recipients:
        return

    subject = f"[HMRA] Alerte capteur : {sensor_name}"
    html    = _build_html(sensor_name, sensor_id, alerts)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"HMRA Monitor <{SMTP_SENDER}>"
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp-relay.brevo.com", 587, timeout=10) as server:
            server.starttls()
            server.login(SMTP_LOGIN, SMTP_PASSWORD)
            server.sendmail(SMTP_SENDER, recipients, msg.as_string())
        print(f"[NOTIFIER] Email envoyé à {recipients} pour '{sensor_name}'")
    except Exception as e:
        print(f"[NOTIFIER] Échec envoi email : {e}")


def notify_alerts(recipients: list[str], sensor_name: str, sensor_id: int, alerts: list):
    """Envoie les alertes par email de façon asynchrone (thread daemon)."""
    if not recipients or not alerts:
        return
    t = threading.Thread(
        target=_send,
        args=(recipients, sensor_name, sensor_id, alerts),
        daemon=True,
    )
    t.start()