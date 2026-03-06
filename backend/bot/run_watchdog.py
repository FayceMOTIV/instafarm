"""Point d'entree pour le watchdog en production. Check toutes les 5 minutes."""

import asyncio
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from backend.bot.watchdog import Watchdog

INTERVAL_SECONDS = 300  # 5 minutes


async def main():
    """Boucle infinie : check_all_services toutes les 5 minutes."""
    watchdog = Watchdog()
    print(f"InstaFarm Watchdog demarre (interval: {INTERVAL_SECONDS}s)")

    stop_event = asyncio.Event()

    def shutdown(sig, frame):
        print(f"\nSignal {sig} recu. Arret en cours...")
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while not stop_event.is_set():
        try:
            await watchdog.check_all_services()
            print("Watchdog check OK")
        except Exception as e:
            print(f"Watchdog erreur: {e}", file=sys.stderr)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass  # Normal — on relance le check

    print("Watchdog arrete proprement.")


if __name__ == "__main__":
    asyncio.run(main())
