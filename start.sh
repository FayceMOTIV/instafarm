#!/bin/bash
set -e

echo "Starting InstaFarm..."

# Xvfb pour Playwright headless sur Linux
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

echo "Xvfb started on :99"

exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
