# Hilfsfunktionen fuer die .env, genutzt von dev.sh und deploy/webserver/install.sh.
# Zum Einbinden (source), nicht zum Ausfuehren. Gibt nie Werte aus.
# Laeuft mit GNU- und BSD-Werkzeugen, also auf Linux und macOS gleich.

random_secret() { openssl rand -hex 32; }

# env_set DATEI SCHLUESSEL WERT
# Ersetzt die Zeile SCHLUESSEL=... (oder haengt sie an). Kein sed, daher sind Sonderzeichen
# im Wert unkritisch; die Rechte der Datei (600) bleiben erhalten.
env_set() {
  local file="$1" key="$2" value="$3" tmp
  tmp=$(mktemp)
  KEY="$key" VALUE="$value" awk '
    BEGIN { key = ENVIRON["KEY"]; value = ENVIRON["VALUE"] }
    index($0, key "=") == 1 { if (!done) print key "=" value; done = 1; next }
    { print }
    END { if (!done) print key "=" value }
  ' "$file" > "$tmp"
  cat "$tmp" > "$file"
  rm -f "$tmp"
}

# env_quote WERT - fuer Werte mit Leer- oder Sonderzeichen: in einfache Anfuehrungszeichen
# setzen, damit bash ("source .env") und docker compose sie gleich lesen.
# Ein einfaches Anfuehrungszeichen im Wert selbst geht nicht (Rueckgabe 1).
env_quote() {
  local value="$1"
  case "$value" in
    *\'*) return 1 ;;
  esac
  if printf '%s' "$value" | grep -q '^[A-Za-z0-9_.@:/%+=,-]*$'; then
    printf '%s' "$value"
  else
    printf "'%s'" "$value"
  fi
}

# url_encode WERT - fuer Passwoerter in DATABASE_URL (liest ueber stdin, damit der Wert
# nicht in der Prozessliste auftaucht). Braucht python3.
url_encode() {
  printf '%s' "$1" | python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=""))'
}
