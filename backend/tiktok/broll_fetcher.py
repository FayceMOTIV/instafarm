"""Fetcher de B-roll videos depuis Pexels.

Telecharge des clips video courts libres de droits pour enrichir les TikToks.
Fallback : pas de B-roll (images statiques conservees).
"""

import asyncio
import os
import random
import time

import httpx

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# Mots-cles par niche pour les B-rolls
NICHE_BROLL_QUERIES = {
    "restauration": ["restaurant cooking", "chef kitchen", "food plating", "dining table"],
    "coiffure": ["hairdresser salon", "hair styling", "beauty salon"],
    "btp_artisan": ["construction worker", "renovation house", "craftsman tools"],
    "dentiste": ["dental clinic", "medical office", "healthcare"],
    "auto_garage": ["auto repair", "mechanic car", "car workshop"],
    "sport_fitness": ["gym workout", "fitness training", "exercise"],
    "immobilier": ["modern house interior", "real estate tour", "luxury apartment"],
    "photographe": ["photographer studio", "camera shooting", "creative photography"],
}

# Resolution cible pour TikTok vertical
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


async def fetch_broll_clip(
    niche: str, scene_index: int, duration: float = 5.0
) -> str | None:
    """Telecharge un clip B-roll adapte a la niche.

    Returns:
        Chemin du fichier MP4 ou None si echec.
    """
    if not PEXELS_API_KEY:
        return None

    queries = NICHE_BROLL_QUERIES.get(niche, ["business professional"])
    query = random.choice(queries)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={
                    "query": query,
                    "orientation": "portrait",
                    "size": "medium",
                    "per_page": 15,
                },
            )

            if resp.status_code != 200:
                print(f"[TIKTOK] Pexels Video API {resp.status_code}")
                return None

            data = resp.json()
            videos = data.get("videos", [])

            if not videos:
                return None

            # Filtrer les videos de duree acceptable (3-15s)
            suitable = [v for v in videos if 3 <= v.get("duration", 0) <= 15]
            if not suitable:
                suitable = videos

            video = random.choice(suitable)
            video_files = video.get("video_files", [])

            if not video_files:
                return None

            # Chercher la meilleure resolution portrait
            best = _pick_best_file(video_files)
            if not best:
                return None

            download_url = best.get("link")
            if not download_url:
                return None

            # Telecharger
            ts = int(time.time())
            raw_path = f"/tmp/instafarm/broll/raw_{scene_index}_{ts}.mp4"
            output_path = f"/tmp/instafarm/broll/broll_{scene_index}_{ts}.mp4"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            vid_resp = await client.get(download_url, timeout=60)
            if vid_resp.status_code != 200:
                return None

            with open(raw_path, "wb") as f:
                f.write(vid_resp.content)

            if os.path.getsize(raw_path) < 50000:
                os.remove(raw_path)
                return None

            # Recadrer en 1080x1920 et limiter la duree
            success = await _process_broll(raw_path, output_path, duration)

            # Cleanup raw
            try:
                os.remove(raw_path)
            except OSError:
                pass

            if success:
                print(f"[TIKTOK] B-roll scene {scene_index}: Pexels ({query})")
                return output_path

            return None

    except Exception as e:
        print(f"[TIKTOK] B-roll fetch erreur: {e}")
        return None


async def fetch_broll_clips(
    scenes: list[dict], niche: str
) -> list[str | None]:
    """Tente de telecharger des B-rolls pour certaines scenes.

    Alterne : scene 0 = image, scene 1 = B-roll, scene 2 = image, etc.
    """
    if not PEXELS_API_KEY:
        print("[TIKTOK] Pas de PEXELS_API_KEY, pas de B-roll")
        return [None] * len(scenes)

    tasks = []
    for i, scene in enumerate(scenes):
        # B-roll toutes les 2 scenes (scenes impaires)
        if i % 2 == 1:
            duration = scene.get("duration_seconds", 5)
            tasks.append(fetch_broll_clip(niche, i, min(duration, 8)))
        else:
            tasks.append(_noop())

    return await asyncio.gather(*tasks)


async def _noop() -> None:
    """Placeholder pour les scenes sans B-roll."""
    return None


def _pick_best_file(video_files: list[dict]) -> dict | None:
    """Choisit le meilleur fichier video (portrait, HD)."""
    # Preferer HD portrait
    portrait = [
        f for f in video_files
        if f.get("height", 0) > f.get("width", 0)
        and f.get("height", 0) >= 720
    ]

    if portrait:
        # Trier par hauteur descendante, prendre le plus proche de 1920
        portrait.sort(key=lambda f: abs(f.get("height", 0) - 1920))
        return portrait[0]

    # Sinon n'importe quel fichier HD
    hd = [f for f in video_files if f.get("height", 0) >= 720]
    if hd:
        return hd[0]

    return video_files[0] if video_files else None


async def _process_broll(
    input_path: str, output_path: str, duration: float
) -> bool:
    """Recadre le B-roll en 1080x1920 et limite la duree."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-t", str(min(duration, 8)),
        "-vf", (
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT}"
        ),
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-an",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        print(f"[TIKTOK] B-roll process erreur: {stderr.decode()[-200:]}")
        return False

    return os.path.exists(output_path) and os.path.getsize(output_path) > 10000
