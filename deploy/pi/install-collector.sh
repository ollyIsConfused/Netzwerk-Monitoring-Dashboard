#!/usr/bin/env bash
# Installiert ODER aktualisiert den Collector auf dem Router-Pi (systemd-Dienst).
# Mehrfach ausfuehrbar, z. B. nach einem git pull:
#   sudo ./deploy/pi/install-collector.sh
#
# Was es tut: Collector nach /opt/monitoring-collector kopieren, Python-Umgebung,
# Konfiguration pruefen, Verbindung zum Backend testen, Dienst (neu) starten.
# Was es NICHT tut: Firewall- oder Netzwerk-Konfiguration aendern.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"

cd "$(dirname "$0")/../.."
REPO="$PWD"
TARGET=/opt/monitoring-collector
ENV_FILE=/etc/monitoring-collector.env
UNIT=/etc/systemd/system/monitoring-collector.service

step() { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
fail() { printf '\nFEHLER: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
step "Voraussetzungen prüfen"

PYTHON=""
# pysnmp 4.4 braucht asyncore, das es ab Python 3.12 nicht mehr gibt
for candidate in python3.11 python3.10 python3.9 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    case "$version" in
      3.9|3.10|3.11) PYTHON="$candidate"; break ;;
    esac
  fi
done
[ -n "$PYTHON" ] || fail "Python 3.9 bis 3.11 wird gebraucht (Raspberry Pi OS Bookworm hat 3.11)."
"$PYTHON" -c 'import ensurepip' 2>/dev/null || fail "venv-Modul fehlt: sudo apt install python3-venv"
command -v ping >/dev/null 2>&1 || fail "ping fehlt: sudo apt install iputils-ping"
command -v curl >/dev/null 2>&1 || fail "curl fehlt: sudo apt install curl"
info "Python: $("$PYTHON" --version 2>&1)"

# ---------------------------------------------------------------------------
step "Collector nach $TARGET kopieren"

id monitoring >/dev/null 2>&1 || useradd --system --home "$TARGET" --shell /usr/sbin/nologin monitoring
install -d -m 755 "$TARGET"
rm -rf "$TARGET/collector.new"
cp -r "$REPO/collector" "$TARGET/collector.new"
find "$TARGET/collector.new" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf "$TARGET/collector"
mv "$TARGET/collector.new" "$TARGET/collector"

[ -x "$TARGET/venv/bin/python" ] || "$PYTHON" -m venv "$TARGET/venv"
"$TARGET/venv/bin/pip" install --quiet --upgrade pip
"$TARGET/venv/bin/pip" install --quiet -r "$TARGET/collector/requirements.txt"
chown -R monitoring:monitoring "$TARGET"
info "Code und Pakete aktuell"

# ---------------------------------------------------------------------------
step "Konfiguration $ENV_FILE prüfen"

if [ ! -f "$ENV_FILE" ]; then
  install -m 600 -o root -g root "$REPO/deploy/pi/monitoring-collector.env.example" "$ENV_FILE"
  fail "$ENV_FILE wurde angelegt. Jetzt eintragen:  sudo nano $ENV_FILE
    BACKEND_URL=http://<webserver-ip>:8080/api     (zeigt install.sh auf dem Webserver an)
    COLLECTOR_API_TOKEN=<Wert aus der .env auf dem Webserver>
  Danach dieses Skript erneut starten."
fi
chmod 600 "$ENV_FILE"

BACKEND_URL=$(grep -E '^BACKEND_URL=' "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
TOKEN=$(grep -E '^COLLECTOR_API_TOKEN=' "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
BACKEND_URL=${BACKEND_URL%/}

case "$BACKEND_URL" in
  ""|*example.com*) fail "BACKEND_URL in $ENV_FILE ist noch nicht gesetzt." ;;
esac
case "$TOKEN" in
  ""|change-me*) fail "COLLECTOR_API_TOKEN in $ENV_FILE ist noch der Platzhalter." ;;
esac
info "Werte gesetzt (werden nicht angezeigt)"

# ---------------------------------------------------------------------------
step "Verbindung zum Backend testen"

result=$(curl -s -o /dev/null -w '%{http_code} %{content_type}' --max-time 10 \
  -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/collector/devices" || true)
code=${result%% *}
content_type=${result#* }
case "$code" in
  200)
    # nginx liefert fuer unbekannte Pfade die Dashboard-Seite (HTML) mit 200 aus -
    # nur eine JSON-Antwort kommt wirklich vom Backend
    case "$content_type" in
      application/json*) info "Backend erreichbar, Token passt" ;;
      *) fail "Unter $BACKEND_URL antwortet nicht das Backend, sondern eine Webseite. Über nginx muss die URL auf /api enden (z. B. http://<webserver-ip>:8080/api)." ;;
    esac
    ;;
  401) fail "Backend erreichbar, aber das Token passt nicht. COLLECTOR_API_TOKEN muss exakt dem Wert in der .env des Webservers entsprechen." ;;
  503) fail "Backend erreichbar, aber dort ist kein COLLECTOR_API_TOKEN gesetzt (install.sh auf dem Webserver ausführen)." ;;
  404) fail "Unter $BACKEND_URL antwortet etwas, aber nicht das Backend. Über nginx endet die URL auf /api (z. B. http://<webserver-ip>:8080/api)." ;;
  000) fail "Keine Antwort von $BACKEND_URL - falsche Adresse, Backend aus oder Port blockiert." ;;
  *) fail "Unerwartete Antwort $code von $BACKEND_URL/collector/devices." ;;
esac

# ---------------------------------------------------------------------------
step "systemd-Dienst"

install -m 644 "$REPO/deploy/pi/monitoring-collector.service" "$UNIT"
systemctl daemon-reload
systemctl enable monitoring-collector >/dev/null 2>&1
systemctl restart monitoring-collector
sleep 3
if systemctl is-active --quiet monitoring-collector; then
  info "monitoring-collector läuft"
else
  journalctl -u monitoring-collector -n 20 --no-pager || true
  fail "Dienst startet nicht - siehe Log oben."
fi

step "Fertig"
cat <<EOF
    Live-Log:     journalctl -u monitoring-collector -f
    Status:       systemctl status monitoring-collector
    Update:       git pull && sudo ./deploy/pi/install-collector.sh
EOF
