#!/usr/bin/env bash
# Wrapper, damit pm2 die Werte aus .env als echte Umgebungsvariablen bekommt
# (pm2-ecosystem-Dateien haben kein eingebautes "env_file" wie docker-compose).
set -euo pipefail
cd "$(dirname "$0")/../../backend"

set -a
source ../.env
set +a

export PYTHONPATH="$(cd .. && pwd)"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
