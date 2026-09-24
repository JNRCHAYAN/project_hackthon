#!/usr/bin/env bash
set -euo pipefail

# Overridable so the demo can move when 8000 is already taken — Docker Desktop
# binds it on some developer machines, and the failure mode there is an opaque
# "address already in use" right as you are about to present. Render injects
# PORT itself, so this stays a local convenience and does not change the
# deployed behaviour.
PORT="${PORT:-8000}"

python -m pip install -q -r requirements.txt

echo "Super Agent Liquidity & Risk Intelligence Platform"
echo "  dashboard : http://127.0.0.1:${PORT}"
echo "  health    : http://127.0.0.1:${PORT}/healthz"
echo "  api       : http://127.0.0.1:${PORT}/api/state"
echo
echo "  (port ${PORT} busy? re-run as:  PORT=8123 ./run.sh)"
echo

python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload
