#!/bin/bash
# Wrapper pour lancer le Scheduler InstaFarm via LaunchAgent
cd /Users/faicalkriouar/Desktop/instafarm

export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# Charger le .env
set -a
source .env 2>/dev/null || true
set +a

echo "[$(date)] Scheduler starting..." >&2
exec /usr/local/bin/python3 -u -m backend.scrapers.scheduler
