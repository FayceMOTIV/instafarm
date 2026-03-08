#!/bin/bash
set -e

PROJECT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
LAUNCH_AGENTS=~/Library/LaunchAgents

echo "InstaFarm Daemon Installer (Mac)"
echo "================================="
echo "Projet : $PROJECT_DIR"
echo ""

# Dechager si deja charge
launchctl unload "$LAUNCH_AGENTS/tech.facemedia.instafarm-api.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_AGENTS/tech.facemedia.instafarm-scheduler.plist" 2>/dev/null || true
sleep 1

# Charger les services
echo "Demarrage API..."
launchctl load "$LAUNCH_AGENTS/tech.facemedia.instafarm-api.plist"

echo "Demarrage Scheduler..."
launchctl load "$LAUNCH_AGENTS/tech.facemedia.instafarm-scheduler.plist"

# Attendre demarrage
sleep 3

# Verifier
echo ""
API_OK=false
for i in 1 2 3; do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        API_OK=true
        break
    fi
    sleep 2
done

if [ "$API_OK" = true ]; then
    echo "API       : OK (http://localhost:8000)"
else
    echo "API       : EN COURS DE DEMARRAGE (verifier /tmp/instafarm-api-error.log)"
fi

pgrep -f "backend.scrapers.scheduler" >/dev/null 2>&1 && echo "Scheduler : OK" || echo "Scheduler : EN COURS DE DEMARRAGE"

echo ""
echo "InstaFarm tourne en daemon !"
echo "  Logs API  : tail -f /tmp/instafarm-api.log"
echo "  Logs Sched: tail -f /tmp/instafarm-scheduler.log"
echo ""
echo "Pour stopper :"
echo "  launchctl unload $LAUNCH_AGENTS/tech.facemedia.instafarm-api.plist"
echo "  launchctl unload $LAUNCH_AGENTS/tech.facemedia.instafarm-scheduler.plist"
