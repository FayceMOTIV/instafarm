#!/bin/bash
# Wrapper pour lancer l'API InstaFarm via LaunchAgent
cd /Users/faicalkriouar/Desktop/instafarm

# Charger le .env
set -a
source .env 2>/dev/null || true
set +a

exec /usr/local/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
