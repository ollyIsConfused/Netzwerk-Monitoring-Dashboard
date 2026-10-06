#!/usr/bin/env bash
# Monitoring-Agent: schickt CPU-Last, Arbeitsspeicher, Festplattenbelegung und (falls
# vorhanden) Temperatur an das Dashboard (POST /agent/push). Braucht nur bash, awk, df
# und curl. Eingerichtet wird er mit deploy/agent/install-agent.sh (systemd-Timer).
#
# Einstellungen kommen aus der Umgebung (/etc/monitoring-agent.env):
#   BACKEND_URL      Backend-Adresse, ueber nginx mit /api am Ende (http://<webserver-ip>:8080/api)
#   AGENT_TOKEN      Agent-Token aus der Geraete-Konfiguration im Dashboard
#   DISKS            Mountpunkte, durch Leerzeichen getrennt (Standard: /)
#   STATE_DIRECTORY  setzt systemd; dort liegen die CPU-Zaehler vom letzten Lauf
#
# Von Hand:  ./monitoring-agent.sh --print   zeigt die Werte, ohne etwas zu senden
set -euo pipefail
set -f           # keine Platzhalter-Erweiterung, z. B. bei DISKS
export LC_ALL=C  # Dezimalpunkt statt Komma in den Zahlen

PRINT_ONLY=no
[ "${1:-}" = "--print" ] && PRINT_ONLY=yes

fail() {
  # Exit-Code unterscheidet die Ursachen fuer install-agent.sh
  printf 'FEHLER: %s\n' "$2" >&2
  exit "$1"
}

# ---------------------------------------------------------------------------
# Messwerte

cpu_counters() {
  # Erste Zeile von /proc/stat: cpu user nice system idle iowait irq softirq steal ...
  local _label user nice system idle iowait irq softirq steal _rest
  read -r _label user nice system idle iowait irq softirq steal _rest < /proc/stat
  echo "$((user + nice + system + idle + iowait + irq + softirq + steal)) $((idle + iowait))"
}

cpu_pct() {
  # Durchschnitt seit dem letzten Lauf; ohne gespeicherte Werte eine Sekunde lang messen
  local state_file="" previous current
  [ -n "${STATE_DIRECTORY:-}" ] && state_file="$STATE_DIRECTORY/cpu"
  current=$(cpu_counters)
  if [ -n "$state_file" ] && [ -r "$state_file" ]; then
    previous=$(cat "$state_file")
  else
    previous=$current
    sleep 1
    current=$(cpu_counters)
  fi
  [ -n "$state_file" ] && echo "$current" > "$state_file" 2>/dev/null || true
  # Nach einem Neustart sind die Zaehler kleiner als gespeichert - dann kein Wert
  echo "$previous $current" | awk '{
    total = $3 - $1; idle = $4 - $2
    if (total > 0 && idle >= 0) printf "%.1f", (total - idle) * 100 / total
  }'
}

mem_pct() {
  # MemAvailable beruecksichtigt Cache, der bei Bedarf frei wird
  awk '/^MemTotal:/ { total = $2 } /^MemAvailable:/ { avail = $2 }
       END { if (total > 0) printf "%.1f", (total - avail) * 100 / total }' /proc/meminfo
}

disk_metric_name() {
  # / -> disk_pct, /mnt/storage -> disk_mnt_storage_pct (max. 64 Zeichen fuer die Datenbank)
  local slug
  [ "$1" = "/" ] && { echo "disk_pct"; return; }
  slug=$(printf '%s' "${1#/}" | tr -c 'A-Za-z0-9' '_' | cut -c1-55)
  echo "disk_${slug}_pct"
}

disk_pct() {
  # Belegt in Prozent wie bei df (belegt / (belegt + frei)), aber mit Nachkommastelle
  local line mounted_on
  line=$(df -P -k "$1" 2>/dev/null | awk 'NR == 2') || true
  [ -n "$line" ] || { echo "WARNUNG: $1 nicht gefunden - übersprungen" >&2; return 0; }
  mounted_on=$(echo "$line" | awk '{ print $6 }')
  if [ "$mounted_on" != "$1" ]; then
    # Sonst wuerde z. B. bei nicht eingehaengtem Festplatten-Array die Systemplatte gemeldet
    echo "WARNUNG: $1 ist nicht eingehängt (liegt auf $mounted_on) - übersprungen" >&2
    return 0
  fi
  echo "$line" | awk '{ if ($3 + $4 > 0) printf "%.1f", $3 * 100 / ($3 + $4) }'
}

temp_c() {
  local file=/sys/class/thermal/thermal_zone0/temp
  [ -r "$file" ] || return 0
  awk '$1 ~ /^[0-9]+$/ && $1 > 0 { printf "%.1f", $1 / 1000 }' "$file"
}

declare -a NAMES=() VALUES=()
add() {
  [ -n "$2" ] || return 0
  NAMES+=("$1")
  VALUES+=("$2")
}

add cpu_pct "$(cpu_pct)"
add mem_pct "$(mem_pct)"
for mount in ${DISKS:-/}; do
  add "$(disk_metric_name "$mount")" "$(disk_pct "$mount")"
done
add temp_c "$(temp_c)"

summary=""
json=""
for i in "${!NAMES[@]}"; do
  summary+="${summary:+, }${NAMES[$i]}=${VALUES[$i]}"
  json+="${json:+,}\"${NAMES[$i]}\":${VALUES[$i]}"
done

if [ "$PRINT_ONLY" = yes ]; then
  for i in "${!NAMES[@]}"; do printf '%s=%s\n' "${NAMES[$i]}" "${VALUES[$i]}"; done
  exit 0
fi
[ -n "$json" ] || fail 1 "Keine Messwerte ermittelt."

# ---------------------------------------------------------------------------
# Senden

BACKEND_URL=${BACKEND_URL:-}
BACKEND_URL=${BACKEND_URL%/}
AGENT_TOKEN=${AGENT_TOKEN:-}
[ -n "$BACKEND_URL" ] || fail 1 "BACKEND_URL ist nicht gesetzt (z. B. http://<webserver-ip>:8080/api)."
# Nur diese Zeichen, damit das Token sicher in das JSON passt
[[ "$AGENT_TOKEN" =~ ^[A-Za-z0-9._~-]{16,128}$ ]] \
  || fail 1 "AGENT_TOKEN fehlt oder enthält unerlaubte Zeichen (16-128 Zeichen: Buchstaben, Ziffern, . _ ~ -)."
command -v curl >/dev/null 2>&1 || fail 1 "curl fehlt (sudo apt install curl)."

result=$(curl -sS -o /dev/null -w '%{http_code} %{content_type}' --max-time 10 \
  -H 'Content-Type: application/json' \
  --data-binary "{\"agent_token\":\"$AGENT_TOKEN\",\"metrics\":{$json}}" \
  "$BACKEND_URL/agent/push" 2>/dev/null) || true
code=${result%% *}
content_type=${result#* }

case "$code" in
  202) echo "Gesendet: $summary" ;;
  401) fail 3 "Das Backend kennt das Token nicht. Im Dashboard unter Geräte > Bearbeiten muss bei diesem Gerät der Agent aktiviert sein und genau dieses Token stehen." ;;
  404|405) fail 4 "Unter $BACKEND_URL antwortet nicht das Backend. Über nginx lautet die Adresse http://<webserver-ip>:8080/api, direkt am Backend (Port 8000) ohne /api." ;;
  422) fail 5 "Das Backend hat die Werte abgelehnt (422): $summary" ;;
  000|"") fail 2 "Keine Verbindung zu $BACKEND_URL - Adresse falsch, Backend aus oder eine Firewall blockiert." ;;
  *)
    case "$content_type" in
      text/html*) fail 4 "Unter $BACKEND_URL antwortet eine Webseite statt des Backends. Über nginx muss die Adresse auf /api enden." ;;
    esac
    fail 1 "Unerwartete Antwort $code von $BACKEND_URL/agent/push."
    ;;
esac
