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

# Bremse gegen Passwort-Raten: nach so vielen Fehlversuchen von einer IP-Adresse ist die
# Anmeldung fuer LOGIN_BLOCK_SECONDS gesperrt (pro Benutzername gilt das Doppelte)
LOGIN_MAX_FAILURES = int(os.environ.get("LOGIN_MAX_FAILURES", "5"))
LOGIN_BLOCK_SECONDS = int(os.environ.get("LOGIN_BLOCK_SECONDS", "300"))

# API-Beschreibung unter /docs und /openapi.json - im Betrieb aus, beim Entwickeln an
ENABLE_API_DOCS = os.environ.get("ENABLE_API_DOCS", "").strip().lower() in ("1", "true", "yes", "ja")
# Nur noetig, wenn das Frontend von einer anderen Adresse kommt als die API (mehrere mit
# Komma). Leer = kein CORS: Frontend und API laufen ueber denselben nginx.
CORS_ORIGINS = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()]
