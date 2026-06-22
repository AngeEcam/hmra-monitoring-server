# hmra-monitoring-server

Serveur de monitoring environnemental de l'HMRA — **FastAPI + SQLite** avec dashboard temps réel et alerting par email.

Brique « serveur » du projet **[TFE_2025_2026](https://github.com/AngeEcam/TFE_2025_2026)** (voir ce dépôt pour l'architecture d'ensemble et le câblage).

---

## Rôle

Reçoit les mesures envoyées par la passerelle ESP32, les stocke, évalue les seuils, déclenche les alarmes (email) et les expose dans un dashboard web.

```
… ESP32 ──HTTP POST /ingest──▶ FastAPI ──▶ SQLite ──▶ Dashboard + alarmes email
```

---

## Contenu du dépôt

| Fichier | Rôle |
|---|---|
| `main.py` | routes FastAPI (ingestion, données, alarmes, seuils, capteurs, unités, utilisateurs) |
| `auth.py` | authentification JWT (OAuth2, HS256), hachage bcrypt, dépendances |
| `config.py` | configuration centralisée, secrets chargés depuis `.env` |
| `database.py` | schéma SQLite + requêtes + migrations |
| `notifier.py` | envoi d'alertes par email (SMTP), asynchrone |
| `analyse_capteurs.py` | analyse comparative vs Ebro EBI 310, génération des graphiques |
| `static/` | dashboard web (`dashboard.html`) |
| `requirements.txt` | dépendances Python |
| `graph_*.png` | figures de validation (écarts frigo, température, humidité) |

---

## Installation

```bash
pip install -r requirements.txt

# Secrets — créer un fichier .env (le serveur refuse de démarrer sans SECRET_KEY)
cp .env.example .env        # si présent ; sinon créer .env (voir ci-dessous)
```

Contenu de `.env` :

```ini
# Sécurité — OBLIGATOIRE
# Générer : python -c "import secrets; print(secrets.token_urlsafe(48))"
SECRET_KEY=

SUPERADMIN_PASSWORD=admin
TOKEN_EXPIRE_MINUTES=480

# Notifications email (SMTP) — optionnel
SMTP_SENDER=
SMTP_LOGIN=
SMTP_PASSWORD=
```

> Ajoutez `.env` et `*.db` à votre `.gitignore`. (Pensez aussi à retirer le `.DS_Store` actuellement versionné.)

---

## Lancement

```bash
python main.py
```

- Écoute sur `http://0.0.0.0:8080` (configurable dans `config.py`).
- La base SQLite (`hmra_monitor.db`) et le compte **superadmin** sont créés au premier démarrage.
- Dashboard : `http://<serveur>:8080/dashboard`.
- Documentation OpenAPI interactive : `http://<serveur>:8080/docs`.

> **Production** : lancer via `uvicorn` derrière un reverse-proxy (Nginx) assurant le **HTTPS**.

---

## API REST (résumé)

L'API utilise **OAuth2 Password Flow** + JWT. En-tête requis sur la plupart des routes : `Authorization: Bearer <token>`.
Deux rôles : `user` (cloisonné à son service) et `superadmin` (accès global).

### Authentification
| Méthode | Route | Description |
|---|---|---|
| `POST` | `/auth/login` | login OAuth2 (form `username`/`password`) → token |
| `GET` | `/auth/me` | infos du token courant |

### Ingestion (appelée par la passerelle, sans auth)
| Méthode | Route | Description |
|---|---|---|
| `POST` | `/ingest` | reçoit une mesure JSON |

Format attendu :
```json
{"ts":2135,"sid":1,"temp_c":22.5,"hum_rh":41.1,"pres_hpa":994.8,"flags":1,"gw_ip":"192.168.1.50"}
```
Comportement selon le mode du capteur : `active` (enregistre + alarmes), `maintenance` (enregistre sans alarme), `disabled` (ignore).

### Données & statistiques
| Méthode | Route | Description |
|---|---|---|
| `GET` | `/data` | mesures brutes (`hours`, `sid`, `limit`) |
| `GET` | `/stats` | vue agrégée par capteur (filtrée par service) |
| `GET` | `/history/{sid}` | historique d'un capteur (`hours`) |

### Alarmes
| Méthode | Route | Description |
|---|---|---|
| `GET` | `/alerts` | liste (`limit`, `only_active`) |
| `POST` | `/alerts/{id}/acknowledge` | acquitter une alarme |
| `POST` | `/alerts/acknowledge-all` | tout acquitter |

### Seuils
| Méthode | Route | Description |
|---|---|---|
| `GET` | `/thresholds` · `/thresholds/{sid}` | consulter |
| `PUT` | `/thresholds/{sid}/{param}` | définir min/max (`{ "vmin":…, "vmax":… }`) |

### Capteurs
| Méthode | Route | Description |
|---|---|---|
| `GET` | `/sensors/config` | configuration de tous les capteurs |
| `POST` | `/sensors/{sid}/mode` | `active` \| `maintenance` \| `disabled` |
| `PUT` | `/sensors/{sid}/name` | renommer |
| `POST` | `/sensors/{sid}/assign-unit` | associer à une unité |
| `DELETE` | `/sensors/{sid}` | supprimer *(superadmin)* |

### Unités (enceintes)
| Méthode | Route | Description |
|---|---|---|
| `GET` | `/units` · `/units/{id}` · `/units/form-options` | consulter |
| `POST` / `PUT` / `DELETE` | `/units` … | créer / modifier / supprimer |

### Administration *(superadmin)*
| Méthode | Route | Description |
|---|---|---|
| `GET` | `/admin/users` | lister les utilisateurs |
| `POST` | `/admin/users` | créer (`{username, password, role, service, email?, notify_email?}`) |
| `PUT` | `/admin/users/{id}` | modifier |
| `POST` | `/admin/users/{id}/reset-password` | réinitialiser le mot de passe |
| `DELETE` | `/admin/users/{id}` | supprimer |
| `GET` | `/admin/services` | services disponibles |

---

## Sécurité

- **JWT** OAuth2 signé **HS256**, stocké côté client en `sessionStorage`.
- Mots de passe hachés en **bcrypt** (facteur de coût adaptatif).
- **Cloisonnement par service** appliqué côté serveur sur chaque route (non contournable côté client).
- **Secrets externalisés** dans `.env` ; le serveur refuse de démarrer sans `SECRET_KEY`.

---

## Validation

Le script `analyse_capteurs.py` compare les mesures aux relevés du logger certifié **Ebro EBI 310** et génère les figures `graph_*.png`. Protocole et résultats détaillés : [docs/VALIDATION.md du hub](https://github.com/AngeEcam/TFE_2025_2026/blob/master/docs/VALIDATION.md).
