#!/usr/bin/env bash
# Installiert ODER aktualisiert Backend + Frontend auf dem Webserver.
# Mehrfach ausfuehrbar: beim ersten Mal Einrichtung, danach als Update:
#   cd /opt/monitoring && git pull && ./deploy/webserver/install.sh
#
# Was es tut: Python-Umgebung + Pakete, Datenbank-Check, Admin anlegen (nur beim
# ersten Mal), Frontend bauen, Backend per pm2 (neu) starten, optional nginx-Site.
# Was es NICHT tut: Firewall-Regeln aendern - die noetigen Befehle werden nur angezeigt.
set -euo pipefail

PORT=8080
SETUP_NGINX=ask
MAILTEST=no

usage() {
  cat <<EOF
Aufruf: $0 [--port N] [--nginx | --no-nginx] [--mailtest]
  --port N     Port der nginx-Site fuer das Dashboard (Standard: 8080)
  --nginx      nginx-Site ohne Rueckfrage einrichten/aktualisieren
  --no-nginx   nginx-Schritt ueberspringen
  --mailtest   nur eine Test-Mail mit den SMTP-Werten aus .env schicken (an die Admins)
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --nginx) SETUP_NGINX=yes; shift ;;
    --no-nginx) SETUP_NGINX=no; shift ;;
    --mailtest) MAILTEST=yes; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unbekannte Option: $1"; usage; exit 1 ;;
  esac
done

cd "$(dirname "$0")/../.."
ROOT="$PWD"
# shellcheck source=../env-tools.sh
. deploy/env-tools.sh

step() { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '    WARNUNG: %s\n' "$*"; }
fail() { printf '\nFEHLER: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
step "Voraussetzungen prüfen"

PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    case "$version" in
      3.10|3.11|3.12) PYTHON="$candidate"; break ;;
    esac
  fi
done
[ -n "$PYTHON" ] || fail "Python 3.10 bis 3.12 wird gebraucht (für neuere gibt es kein fertiges psycopg2-Paket).
  Ubuntu/Debian: sudo apt install python3 python3-venv"
"$PYTHON" -c 'import ensurepip' 2>/dev/null || fail "venv-Modul fehlt: sudo apt install ${PYTHON}-venv"
info "Python: $PYTHON ($("$PYTHON" --version 2>&1))"

command -v npm >/dev/null 2>&1 || fail "Node.js/npm fehlt (20.19+ oder 22.12+)."
# Mindestversion von Vite 8
node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit((a === 20 && b >= 19) || (a === 22 && b >= 12) || a > 22 ? 0 : 1)' \
  || fail "Node.js $(node --version) passt nicht - Vite 8 braucht 20.19+ oder 22.12+."
command -v pm2 >/dev/null 2>&1 || fail "pm2 fehlt: sudo npm install -g pm2"
command -v openssl >/dev/null 2>&1 || fail "openssl fehlt: sudo apt install openssl"
info "Node: $(node --version), pm2: $(pm2 --version)"

# ---------------------------------------------------------------------------
step ".env prüfen"

ask() {
  # ask VARIABLE "Frage" [Vorgabe]
  local answer prompt="$2"
  [ -n "${3:-}" ] && prompt="$prompt [$3]"
  read -r -p "    $prompt: " answer
  printf -v "$1" '%s' "${answer:-${3:-}}"
}

ask_secret() {
  # Eingabe wird nicht angezeigt
  local answer
  read -r -s -p "    $2: " answer
  echo
  printf -v "$1" '%s' "$answer"
}

first_run_setup() {
  info "Erste Einrichtung. Die Antworten landen nur in .env (nur für dich lesbar),"
  info "Passwörter werden bei der Eingabe nicht angezeigt. Enter übernimmt [Vorgaben]."
  echo
  info "PostgreSQL-Datenbank (muss schon existieren, siehe docs/deployment.md Abschnitt 0):"
  ask db_host "  Server (IP oder Name)" "localhost"
  ask db_port "  Port" "5432"
  ask db_name "  Datenbank" "monitoring"
  ask db_user "  Benutzer" "monitoring"
  ask_secret db_password "  Passwort des Datenbank-Benutzers"
  [ -n "$db_password" ] || fail "Ohne Datenbank-Passwort geht es nicht. .env löschen und das Skript neu starten."
  env_set .env DATABASE_URL \
    "postgresql+psycopg2://$(url_encode "$db_user"):$(url_encode "$db_password")@${db_host}:${db_port}/$(url_encode "$db_name")"

  echo
  ask admin_email "E-Mail-Adresse des Admins (bekommt die 'Passwort vergessen'-Anfragen)"
  case "$admin_email" in
    *@*.*) env_set .env SEED_ADMIN_EMAIL "$admin_email" ;;
    *) fail "'$admin_email' ist keine E-Mail-Adresse. .env löschen und das Skript neu starten." ;;
  esac

  echo
  info "E-Mail-Versand (für Alarme und Passwort-Mails). Leer lassen = später in .env eintragen."
  ask smtp_host "  SMTP-Server, z. B. smtp.gmail.com" ""
  if [ -n "$smtp_host" ]; then
    ask smtp_port "  Port (587 = STARTTLS, 465 = SSL)" "587"
    ask smtp_user "  Benutzer (meist die E-Mail-Adresse)" "$admin_email"
    ask_secret smtp_password "  Passwort (bei Gmail ein App-Passwort)"
    smtp_password_quoted=$(env_quote "$smtp_password") \
      || fail "Das SMTP-Passwort enthält ein einfaches Anführungszeichen - bitte von Hand in .env eintragen."
    env_set .env SMTP_HOST "$smtp_host"
    env_set .env SMTP_PORT "$smtp_port"
    env_set .env SMTP_USER "$smtp_user"
    env_set .env SMTP_PASSWORD "$smtp_password_quoted"
    env_set .env ALERT_EMAIL_TO "$admin_email"
  fi
  echo
  info ".env geschrieben. Ändern geht jederzeit mit: nano .env (danach dieses Skript erneut starten)"
}

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  env_set .env JWT_SECRET "$(random_secret)"
  env_set .env COLLECTOR_API_TOKEN "$(random_secret)"
  # In einer echten Umgebung keine Beispiel-VLANs anlegen
  env_set .env SEED_EXAMPLE_VLANS 0
  if [ -t 0 ]; then
    first_run_setup
  else
    fail ".env wurde neu angelegt (JWT_SECRET und COLLECTOR_API_TOKEN sind schon zufällig gesetzt).
  Jetzt noch eintragen:  nano .env
    DATABASE_URL=postgresql+psycopg2://monitoring:<passwort>@<datenbank-ip>:5432/monitoring
    SEED_ADMIN_EMAIL=<deine E-Mail-Adresse>
    SMTP_...  (optional, für Alarm- und Passwort-Mails)
  Danach dieses Skript erneut starten (im Terminal fragt es die Werte selbst ab)."
  fi
fi
chmod 600 .env

if grep -q '^JWT_SECRET=change-me' .env || ! grep -q '^JWT_SECRET=.' .env; then
  env_set .env JWT_SECRET "$(random_secret)"
  info "JWT_SECRET war ein Platzhalter - Zufallswert gesetzt."
fi
if grep -q '^COLLECTOR_API_TOKEN=change-me' .env || ! grep -q '^COLLECTOR_API_TOKEN=.' .env; then
  env_set .env COLLECTOR_API_TOKEN "$(random_secret)"
  warn "COLLECTOR_API_TOKEN war ein Platzhalter - Zufallswert gesetzt. Denselben Wert auf dem Router-Pi eintragen."
fi

HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
HOST_IP=${HOST_IP:-<webserver-ip>}
# Fuer Links in den Passwort-Mails; wer das Dashboard ueber einen anderen Namen aufruft, aendert es in .env
if ! grep -q '^DASHBOARD_URL=.' .env && [ "$HOST_IP" != "<webserver-ip>" ]; then
  env_set .env DASHBOARD_URL "http://$HOST_IP:$PORT"
  info "DASHBOARD_URL=http://$HOST_IP:$PORT gesetzt (für Links in E-Mails)"
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

[ -n "${DATABASE_URL:-}" ] || fail "DATABASE_URL fehlt in .env, z. B.:
    DATABASE_URL=postgresql+psycopg2://monitoring:<passwort>@<nas-ip>:5432/monitoring"
case "$DATABASE_URL" in
  *@localhost[:/]*|*@127.0.0.1[:/]*) info "Datenbank läuft auf diesem Rechner (localhost)" ;;
esac
[ -n "${SMTP_HOST:-}" ] || warn "SMTP_HOST ist leer - Alarm- und Passwort-Mails werden nicht verschickt (Einmal-Passwörter zeigt dann das Dashboard an)."
info ".env ok (Werte werden nicht angezeigt)"

if [ "$MAILTEST" = yes ]; then
  step "Test-Mail"
  [ -x backend/.venv/bin/python ] || fail "Erst einmal ohne --mailtest installieren."
  (cd backend && PYTHONPATH="$ROOT" .venv/bin/python -m app.mailtest) | sed 's/^/    /'
  exit "${PIPESTATUS[0]}"
fi

# ---------------------------------------------------------------------------
step "Backend: Python-Umgebung und Pakete"

[ -x backend/.venv/bin/python ] || "$PYTHON" -m venv backend/.venv
backend/.venv/bin/pip install --quiet --upgrade pip
backend/.venv/bin/pip install --quiet -r backend/requirements.txt
info "Pakete installiert"

# ---------------------------------------------------------------------------
step "Datenbank-Verbindung prüfen"

if ! (cd backend && PYTHONPATH="$ROOT" .venv/bin/python - <<'PY'
import sys
from sqlalchemy import text
from shared.database import engine
try:
    with engine.connect() as conn:
        conn.execute(text("select 1"))
except Exception as exc:  # Meldung ohne Passwort ausgeben
    print("    " + str(getattr(exc, "orig", exc)).strip().splitlines()[0])
    sys.exit(1)
PY
); then
  fail "Keine Verbindung zur Datenbank. Typische Ursachen:
    - Firewall: der Router muss Webserver -> NAS Port 5432 erlauben
    - NAS: listen_addresses in postgresql.conf, Zeile für diese IP in pg_hba.conf
    - Passwort in DATABASE_URL falsch (Sonderzeichen wie @ : / # müssen URL-kodiert sein)"
fi
info "Datenbank erreichbar"

step "Tabellen und Admin-Benutzer (nur falls noch nicht vorhanden)"
(cd backend && PYTHONPATH="$ROOT" .venv/bin/python -m app.seed) | sed 's/^/    /'

# ---------------------------------------------------------------------------
step "Frontend bauen"

BUILD_LOG=$(mktemp)
if ! (cd frontend && npm ci --no-audit --no-fund --loglevel=error && npm run build) > "$BUILD_LOG" 2>&1; then
  tail -n 30 "$BUILD_LOG"
  fail "Frontend-Build fehlgeschlagen (vollständiges Log: $BUILD_LOG)."
fi
rm -f "$BUILD_LOG"
[ -f frontend/dist/index.html ] || fail "Frontend-Build fehlgeschlagen (frontend/dist/index.html fehlt)."
info "Build fertig: frontend/dist"

# ---------------------------------------------------------------------------
step "Backend mit pm2 starten"

chmod +x deploy/webserver/run-backend.sh
if pm2 describe monitoring-backend >/dev/null 2>&1; then
  pm2 restart monitoring-backend --update-env >/dev/null
  info "monitoring-backend neu gestartet"
else
  pm2 start deploy/webserver/ecosystem.config.js >/dev/null
  info "monitoring-backend gestartet"
fi
# Fruehere Versionen haben das Frontend per pm2/serve ausgeliefert - das macht jetzt nginx
pm2 delete monitoring-frontend >/dev/null 2>&1 && info "alte pm2-App monitoring-frontend entfernt" || true
pm2 save >/dev/null

healthy=no
for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then healthy=yes; break; fi
  sleep 1
done
[ "$healthy" = yes ] || fail "Backend antwortet nicht. Logs ansehen: pm2 logs monitoring-backend --lines 50"
info "Backend antwortet auf 127.0.0.1:8000"

if ! ls /etc/systemd/system/pm2-*.service >/dev/null 2>&1; then
  warn "pm2 startet nach einem Neustart noch nicht automatisch. Einmalig: pm2 startup (den angezeigten sudo-Befehl ausführen)"
fi

# ---------------------------------------------------------------------------
step "nginx-Site (Frontend + Weiterleitung von /api und /ws)"

NGINX_CONF=/etc/nginx/sites-available/monitoring-dashboard
NGINX_LINK=/etc/nginx/sites-enabled/monitoring-dashboard

site_responds() {
  curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1
}

setup_nginx() {
  local rendered
  rendered=$(mktemp)
  sed "s|__PORT__|$PORT|g; s|__ROOT__|$ROOT|g" deploy/webserver/nginx-monitoring.conf.template > "$rendered"

  if [ -f "$NGINX_CONF" ] && cmp -s "$rendered" "$NGINX_CONF" && [ -L "$NGINX_LINK" ]; then
    rm -f "$rendered"
    if site_responds; then
      info "unverändert (Port $PORT)"
      return
    fi
    # z. B. wenn ein frueherer Lauf vor dem Neuladen abgebrochen ist
    info "Konfiguration unverändert, aber die Seite antwortet nicht - nginx wird neu geladen"
  else
    sudo install -m 644 "$rendered" "$NGINX_CONF"
    rm -f "$rendered"
    sudo ln -sf "$NGINX_CONF" "$NGINX_LINK"
  fi

  if sudo nginx -t 2>/dev/null; then
    sudo systemctl reload nginx
    sleep 1
    if site_responds; then
      info "aktiv auf Port $PORT"
    else
      warn "nginx wurde neu geladen, aber http://127.0.0.1:$PORT/api/health antwortet nicht (läuft nginx? sudo systemctl status nginx)"
    fi
  else
    sudo rm -f "$NGINX_LINK"
    sudo nginx -t || true
    fail "nginx-Konfiguration fehlerhaft - Site wieder deaktiviert, das bestehende nginx läuft unverändert weiter."
  fi

  if ! sudo -u www-data test -r "$ROOT/frontend/dist/index.html" 2>/dev/null; then
    warn "nginx (www-data) kann $ROOT/frontend/dist nicht lesen. Das Repo am besten nach /opt/monitoring legen."
  fi
}

if ! command -v nginx >/dev/null 2>&1; then
  warn "nginx ist nicht installiert - übersprungen (sudo apt install nginx, danach Skript erneut starten)"
elif [ "$SETUP_NGINX" = no ]; then
  info "übersprungen (--no-nginx)"
elif [ "$SETUP_NGINX" = yes ]; then
  setup_nginx
elif [ -t 0 ]; then
  read -r -p "    nginx-Site auf Port $PORT einrichten bzw. aktualisieren (braucht sudo)? [j/N] " answer
  case "$answer" in
    j|J|y|Y) setup_nginx ;;
    *) info "übersprungen" ;;
  esac
else
  info "übersprungen (kein Terminal für die Rückfrage - mit --nginx erzwingen)"
fi

# ---------------------------------------------------------------------------
step "Fertig"
cat <<EOF
    Dashboard:          http://$HOST_IP:$PORT
    Erste Anmeldung:    Benutzer admin, Passwort admin (bzw. SEED_ADMIN_PASSWORD) -
                        danach muss sofort ein eigenes Passwort festgelegt werden
    Update später:      git pull && ./deploy/webserver/install.sh
    Backend-Logs:       pm2 logs monitoring-backend
    Test-Mail:          ./deploy/webserver/install.sh --mailtest

    Für den Collector auf dem Router-Pi (/etc/monitoring-collector.env):
      BACKEND_URL=http://$HOST_IP:$PORT/api
      COLLECTOR_API_TOKEN=<derselbe Wert wie hier, anzeigen mit: grep ^COLLECTOR_API_TOKEN .env>

    Firewall (wird NICHT automatisch geändert):
      - Browser per VPN brauchen Zugriff auf Port $PORT dieses Servers (Regel auf dem Router).
      - Läuft hier selbst ufw:  sudo ufw allow from <router-ip-im-vlan> to any port $PORT proto tcp
EOF
if [ -n "${SMTP_HOST:-}" ]; then
  info "  - E-Mails: ausgehend Port ${SMTP_PORT:-587} zu $SMTP_HOST muss erlaubt sein."
fi
