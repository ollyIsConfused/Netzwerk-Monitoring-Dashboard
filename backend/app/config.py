import os

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-.env")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))

STATUS_BROADCAST_INTERVAL_SECONDS = int(os.environ.get("STATUS_BROADCAST_INTERVAL_SECONDS", "5"))
# Kommt so lange kein neuer Messwert (Collector bzw. Agent), gilt der Status als veraltet.
# Muss deutlich groesser sein als eine Abfragerunde des Collectors bzw. das Agent-Intervall.
STALE_AFTER_SECONDS = int(os.environ.get("STALE_AFTER_SECONDS", "180"))
ALERT_DISPATCH_INTERVAL_SECONDS = int(os.environ.get("ALERT_DISPATCH_INTERVAL_SECONDS", "10"))

# Shared secret used by the collector service instead of a per-user JWT.
COLLECTOR_API_TOKEN = os.environ.get("COLLECTOR_API_TOKEN", "")

# Empfaenger fuer "Passwort vergessen"-Anfragen (mehrere mit Komma); leer = alle aktiven Admins
ADMIN_NOTIFY_EMAIL = os.environ.get("ADMIN_NOTIFY_EMAIL", "")
# Adresse des Dashboards fuer Links in E-Mails, z. B. http://192.168.30.15:8080 (optional)
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
# Mindestabstand zwischen zwei "Passwort vergessen"-Mails fuer dasselbe Konto
PASSWORD_RESET_COOLDOWN_MINUTES = int(os.environ.get("PASSWORD_RESET_COOLDOWN_MINUTES", "15"))
