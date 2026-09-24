#!/usr/bin/env bash
set -euo pipefail

python -m pip install -q -r requirements.txt

echo "Super Agent Liquidity & Risk Intelligence Platform"
echo "  dashboard : http://127.0.0.1:8000"
echo "  health    : http://127.0.0.1:8000/healthz"
echo "  api       : http://127.0.0.1:8000/api/state"
echo

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
