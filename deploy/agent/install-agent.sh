#!/usr/bin/env bash
# Installiert ODER aktualisiert den Monitoring-Agenten auf einem Server (NAS, Webserver,
# Router-Pi, Pi-hole ...). Mehrfach ausfuehrbar, z. B. nach einem git pull:
#   sudo ./deploy/agent/install-agent.sh
#
# Was es tut: Einstellungen abfragen (/etc/monitoring-agent.env), Agent nach
# /opt/monitoring-agent kopieren, einmal senden und pruefen, systemd-Timer einrichten.
# Was es NICHT tut: Firewall-Regeln aendern - die noetige Freigabe wird nur angezeigt.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"

cd "$(dirname "$0")/../.."
REPO="$PWD"
# Fuer Tests umbiegbar
TARGET=${AGENT_TARGET:-/opt/monitoring-agent}
ENV_FILE=${AGENT_ENV_FILE:-/etc/monitoring-agent.env}
UNIT_DIR=${AGENT_UNIT_DIR:-/etc/systemd/system}

step() { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
fail() { printf '\nFEHLER: %s\n' "$*" >&2; exit 1; }

env_value() {
  # Wert aus der bestehenden Konfiguration lesen, ohne die Datei als Skript auszufuehren
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | sed 's/^"\(.*\)"$/\1/'
}

ask() {
  # ask VARIABLE "Frage" [Vorgabe]
  local answer prompt="$2"
  [ -n "${3:-}" ] && prompt="$prompt [$3]"
  read -r -p "    $prompt: " answer
  printf -v "$1" '%s' "${answer:-${3:-}}"
}

suggest_disks() {
  # / und eigene Mountpunkte (z. B. das Festplatten-Array der NAS), keine Systemordner
  df -P -x tmpfs -x devtmpfs -x squashfs -x overlay -x efivarfs 2>/dev/null \
    | awk 'NR > 1 { print $6 }' \
    | grep -Ev '^/(boot|run|dev|sys|proc|snap|var/lib/docker)(/|$)' \
    | sort -u | tr '\n' ' ' | sed 's/ $//' || true
}

# ---------------------------------------------------------------------------
step "Voraussetzungen prüfen"

command -v curl >/dev/null 2>&1 || fail "curl fehlt: sudo apt install curl"
command -v systemctl >/dev/null 2>&1 || fail "systemd fehlt - der Agent wird über einen systemd-Timer gestartet."
for tool in awk df sed; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool fehlt."
done
info "curl und systemd vorhanden"

# ---------------------------------------------------------------------------
step "Einstellungen ($ENV_FILE)"

backend_url=$(env_value BACKEND_URL)
token=$(env_value AGENT_TOKEN)
disks=$(env_value DISKS)
interval=$(env_value INTERVAL)

if [ -t 0 ]; then
  info "Enter übernimmt [Vorgaben]. Das Token wird bei der Eingabe nicht angezeigt."
  ask backend_url "Backend-Adresse, über nginx mit /api am Ende (http://<webserver-ip>:8080/api)" "$backend_url"
  token_prompt="Agent-Token aus dem Dashboard (Geräte > Bearbeiten > Agent)"
  [ -n "$token" ] && token_prompt="$token_prompt, Enter = bisheriges behalten"
  read -r -s -p "    $token_prompt: " new_token
  echo
  [ -n "$new_token" ] && token=$new_token
  ask disks "Laufwerke (Mountpunkte, durch Leerzeichen getrennt)" "${disks:-$(suggest_disks)}"
  ask interval "Sende-Intervall in Sekunden" "${interval:-60}"
elif [ ! -f "$ENV_FILE" ]; then
  fail "Ohne Terminal kann das Skript nicht nachfragen. $ENV_FILE anlegen (chmod 600):
    BACKEND_URL=http://<webserver-ip>:8080/api
    AGENT_TOKEN=<Agent-Token aus dem Dashboard>
    DISKS=\"/\"
    INTERVAL=60
  Danach dieses Skript erneut starten."
fi

backend_url=${backend_url%/}
disks=${disks:-/}
interval=${interval:-60}

[[ "$backend_url" =~ ^https?://[^[:space:]]+$ ]] \
  || fail "Die Backend-Adresse muss mit http:// oder https:// beginnen (z. B. http://<webserver-ip>:8080/api)."
[[ "$token" =~ ^[A-Za-z0-9._~-]{16,128}$ ]] \
  || fail "Das Agent-Token fehlt oder passt nicht (16 bis 128 Zeichen). Im Dashboard beim Gerät mit 'Generieren' erzeugen."
[[ "$disks" =~ ^[A-Za-z0-9/._\ -]+$ ]] || fail "Laufwerke: nur Pfade ohne Sonderzeichen, durch Leerzeichen getrennt."
for mount in $disks; do
  [[ "$mount" == /* ]] || fail "Laufwerk '$mount' muss mit / beginnen."
done
if ! [[ "$interval" =~ ^[0-9]+$ ]] || [ "$interval" -lt 15 ] || [ "$interval" -gt 120 ]; then
  fail "Das Intervall muss zwischen 15 und 120 Sekunden liegen - sonst meldet das Dashboard die Werte als veraltet."
fi

install -d -m 755 "$(dirname "$ENV_FILE")"
(
  umask 077
  cat > "$ENV_FILE" <<ENV
# Monitoring-Agent - geschrieben von deploy/agent/install-agent.sh, nur fuer root lesbar
BACKEND_URL=$backend_url
AGENT_TOKEN=$token
DISKS="$disks"
INTERVAL=$interval
ENV
)
chmod 600 "$ENV_FILE"
info "gespeichert (das Token wird nicht angezeigt)"

# ---------------------------------------------------------------------------
step "Agent nach $TARGET kopieren"

install -d -m 755 "$TARGET"
install -m 755 "$REPO/agent/monitoring-agent.sh" "$TARGET/monitoring-agent.sh"
info "aktuell"

# ---------------------------------------------------------------------------
step "Testsendung an das Backend"

set +e
output=$(BACKEND_URL="$backend_url" AGENT_TOKEN="$token" DISKS="$disks" "$TARGET/monitoring-agent.sh" 2>&1)
rc=$?
set -e
printf '%s\n' "$output" | sed 's/^/    /'

if [ "$rc" -eq 2 ]; then
  # Keine Verbindung: meist fehlt die Weiterleitung zwischen den VLANs
  host_port=${backend_url#*://}
  host_port=${host_port%%/*}
  host=${host_port%%:*}
  port=${host_port##*:}
  if [ "$port" = "$host_port" ]; then
    port=80
    [[ "$backend_url" == https://* ]] && port=443
  fi
  source_ip=$(ip -o route get "$host" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' || true)
  cat <<EOF

    Liegt dieses Gerät in einem anderen VLAN als der Webserver, muss der Router die
    Verbindung weiterleiten. Auf dem Router-Pi zuerst den IST-Zustand ansehen
    (sudo ufw status numbered) und dann zum Beispiel:
      sudo ufw route allow in on eth0.<vlan-dieses-geraets> out on eth0.<vlan-des-webservers> \\
        proto tcp from ${source_ip:-<ip-dieses-geraets>} to $host port $port
EOF
fi
[ "$rc" -eq 0 ] || fail "Testsendung fehlgeschlagen (siehe oben). Ursache beheben und das Skript erneut starten."

# ---------------------------------------------------------------------------
step "systemd-Timer"

sed "s|__TARGET__|$TARGET|g; s|__ENV_FILE__|$ENV_FILE|g" "$REPO/deploy/agent/monitoring-agent.service" \
  > "$UNIT_DIR/monitoring-agent.service"
sed "s|__INTERVAL__|$interval|g" "$REPO/deploy/agent/monitoring-agent.timer" > "$UNIT_DIR/monitoring-agent.timer"
chmod 644 "$UNIT_DIR/monitoring-agent.service" "$UNIT_DIR/monitoring-agent.timer"
systemctl daemon-reload
# Einmal ueber systemd laufen lassen - prueft auch die Einschraenkungen aus der Unit
if ! systemctl start monitoring-agent.service; then
  journalctl -u monitoring-agent -n 20 --no-pager || true
  fail "Der Agent läuft unter systemd nicht durch - siehe Log oben."
fi
systemctl enable monitoring-agent.timer >/dev/null 2>&1
systemctl restart monitoring-agent.timer
systemctl is-active --quiet monitoring-agent.timer || fail "Der Timer startet nicht: systemctl status monitoring-agent.timer"
info "aktiv, sendet alle $interval Sekunden"

step "Fertig"
cat <<EOF
    Nächste Sendungen:  systemctl list-timers monitoring-agent.timer
    Log:                journalctl -u monitoring-agent -n 20
    Werte ansehen:      $TARGET/monitoring-agent.sh --print
    Update:             git pull && sudo ./deploy/agent/install-agent.sh
    Abschalten:         sudo systemctl disable --now monitoring-agent.timer

    Im Dashboard gibt es beim Gerät unter 'Schwellenwerte' Vorlagen für CPU-Last,
    Arbeitsspeicher, Festplatte und Temperatur.
EOF
