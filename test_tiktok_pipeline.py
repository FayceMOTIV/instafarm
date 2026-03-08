"""Test rapide du pipeline TikTok.

Usage:
    python test_tiktok_pipeline.py [niche]

Exemples:
    python test_tiktok_pipeline.py restauration
    python test_tiktok_pipeline.py coiffure
"""

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()


async def main():
    from backend.tiktok.pipeline import generate_tiktok_video

    niche = sys.argv[1] if len(sys.argv) > 1 else "restauration"
    print(f"\n{'='*60}")
    print(f"  TIKTOK PIPELINE TEST — Niche: {niche}")
    print(f"{'='*60}\n")

    result = await generate_tiktok_video(niche)

    print(f"\n{'='*60}")
    print(f"  RESULTAT")
    print(f"{'='*60}")
    print(f"  Video:    {result['video_path']}")
    print(f"  Audio:    {result['audio_path']} ({result['audio_duration']:.1f}s)")
    print(f"  Images:   {len(result['image_paths'])}")
    print(f"  Hook:     {result['hook'][:60]}")
    print(f"  CTA:      {result['cta_keyword']}")
    print(f"  Temps:    {result['elapsed_seconds']}s")
    print(f"{'='*60}\n")

    # Ouvrir la video sur macOS
    import subprocess
    subprocess.run(["open", result["video_path"]])


if __name__ == "__main__":
    asyncio.run(main())
