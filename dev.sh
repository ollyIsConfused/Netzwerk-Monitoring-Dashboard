#!/usr/bin/env bash
# Lokale Entwicklung: startet Datenbank (Docker), Backend (Port 8000) und
# Frontend (Port 5173) aus einem einzigen Terminal. Strg+C beendet Backend und
# Frontend; die Datenbank laeuft weiter (stoppen mit: docker compose stop db).
# SKIP_DB=1 ./dev.sh, wenn die Datenbank nicht ueber Docker laeuft.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "Fehlt: .env – zuerst 'cp .env.example .env' und Werte eintragen."; exit 1; }
[ -x backend/.venv/bin/uvicorn ] || {
  echo "Fehlt: backend/.venv – zuerst:"
  echo "  cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
}
[ -d frontend/node_modules ] || (cd frontend && npm install)

if [ "${SKIP_DB:-0}" != "1" ]; then
  docker compose up -d --wait db || { echo "Datenbank startet nicht – laeuft Docker Desktop?"; exit 1; }
fi

set -a; source .env; set +a
export PYTHONPATH="$PWD"

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
