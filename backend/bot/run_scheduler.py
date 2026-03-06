"""Point d'entree pour le bot scheduler en production."""

import asyncio
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from backend.bot.scheduler import InstaFarmScheduler


async def main():
    """Demarre le scheduler avec APScheduler."""
    scheduler = InstaFarmScheduler()
    sched = scheduler.setup_jobs()

    if sched is None:
        print("APScheduler non installe. pip install apscheduler")
        sys.exit(1)

    print("InstaFarm Bot Scheduler demarre.")
    print("Jobs configures :")
    for job in sched.get_jobs():
        print(f"  - {job.id}: {job.trigger}")

    # Keep running
    stop_event = asyncio.Event()

    def shutdown(sig, frame):
        print(f"\nSignal {sig} recu. Arret en cours...")
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    await stop_event.wait()

    sched.shutdown(wait=False)
    print("Scheduler arrete proprement.")


if __name__ == "__main__":
    asyncio.run(main())
