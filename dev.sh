#!/usr/bin/env bash
# Lokale Entwicklung: startet Datenbank (Docker), Backend (Port 8000) und
# Frontend (Port 5173) aus einem einzigen Terminal. Strg+C beendet Backend und
# Frontend; die Datenbank laeuft weiter (stoppen mit: docker compose stop db).
# SKIP_DB=1 ./dev.sh, wenn die Datenbank nicht ueber Docker laeuft.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=deploy/env-tools.sh
. deploy/env-tools.sh

if [ ! -f .env ]; then
  # Erster Start: .env mit Zufallswerten fuer die lokale Docker-Datenbank anlegen
  cp .env.example .env
  chmod 600 .env
  env_set .env JWT_SECRET "$(random_secret)"
  env_set .env COLLECTOR_API_TOKEN "$(random_secret)"
  env_set .env POSTGRES_PASSWORD "$(random_secret)"
  echo ".env angelegt (Zufallswerte, lokale Datenbank in Docker)."
fi
[ -x backend/.venv/bin/uvicorn ] || {
  echo "Fehlt: backend/.venv – zuerst:"
  echo "  cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
}
command -v node >/dev/null 2>&1 || { echo "Fehlt: Node.js (20.19+ oder 22.12+), z. B. brew install node"; exit 1; }
# Mindestversion von Vite 8
node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit((a === 20 && b >= 19) || (a === 22 && b >= 12) || a > 22 ? 0 : 1)' \
  || { echo "Node.js $(node --version) ist zu alt - Vite 8 braucht 20.19+ oder 22.12+ (brew upgrade node)."; exit 1; }
[ -d frontend/node_modules ] || (cd frontend && npm install)

if [ "${SKIP_DB:-0}" != "1" ]; then
  docker compose up -d --wait db || { echo "Datenbank startet nicht – laeuft Docker Desktop?"; exit 1; }
fi

set -a; source .env; set +a
export PYTHONPATH="$PWD"
# Beim Entwickeln die API-Beschreibung unter http://localhost:8000/docs einschalten
export ENABLE_API_DOCS=1
if [ -z "${DATABASE_URL:-}" ]; then
  # Ohne eigene DATABASE_URL: der Docker-Container "db" mit den POSTGRES_*-Werten aus .env
  DATABASE_URL="postgresql+psycopg2://$(url_encode "${POSTGRES_USER:-monitoring}"):$(url_encode "${POSTGRES_PASSWORD:-monitoring}")@localhost:5432/${POSTGRES_DB:-monitoring}"
  export DATABASE_URL
fi

if ! (cd backend && .venv/bin/python - <<'PY'
import sys
from sqlalchemy import text
from shared.database import engine
try:
    with engine.connect() as conn:
        conn.execute(text("select 1"))
except Exception as exc:  # Meldung ohne Passwort ausgeben
    print("Datenbank: " + str(getattr(exc, "orig", exc)).strip().splitlines()[0])
    sys.exit(1)
PY
); then
  echo
  echo "Keine Verbindung zur Datenbank."
  echo "Steht oben 'password authentication failed': Der Docker-Container wurde mit einem"
  echo "anderen POSTGRES_PASSWORD angelegt, als jetzt in .env steht. Lokale Testdaten"
  echo "verwerfen und neu anlegen:  docker compose down -v  und dann  ./dev.sh"
  exit 1
fi

# Legt Admin-Benutzer und Beispiel-VLANs nur an, wenn sie noch fehlen
(cd backend && .venv/bin/python -m app.seed)

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8000 ist schon belegt – laeuft das Backend noch in einem anderen Terminal?"
  exit 1
fi

(cd backend && exec .venv/bin/uvicorn app.main:app --reload --reload-dir app --reload-dir ../shared --port 8000) &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT

# Frontend erst starten, wenn das Backend antwortet – sonst sieht man im Browser
# nur "Anmeldung fehlgeschlagen" statt der eigentlichen Fehlermeldung.
for _ in $(seq 1 30); do
  curl -s -o /dev/null http://127.0.0.1:8000/docs && break
  sleep 1
done
curl -s -o /dev/null http://127.0.0.1:8000/docs || { echo "Backend antwortet nicht – Fehlermeldung oben lesen."; exit 1; }

cd frontend
npm run dev
