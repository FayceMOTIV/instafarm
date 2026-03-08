#!/bin/bash
# Empeche le Mac de dormir tant qu'InstaFarm tourne
# Usage : bash backend/deploy/keep_awake.sh &

# Trouver le PID de l'API ou du scheduler
API_PID=$(pgrep -f "uvicorn backend.main" | head -1)
SCHED_PID=$(pgrep -f "backend.scrapers.scheduler" | head -1)

TARGET_PID="${API_PID:-$SCHED_PID}"

if [ -z "$TARGET_PID" ]; then
    echo "Aucun process InstaFarm trouve, caffeinate en mode indefini..."
    caffeinate -i -s &
    echo "Caffeinate actif (PID: $!) — Mac restera eveille"
    echo "Pour stopper : kill $!"
else
    caffeinate -i -w "$TARGET_PID" &
    echo "Caffeinate actif — lie au PID $TARGET_PID"
    echo "Mac restera eveille tant qu'InstaFarm tourne"
fi
