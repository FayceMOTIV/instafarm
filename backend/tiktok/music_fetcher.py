"""Fetcher de musique de fond depuis Pixabay Audio.

Telecharge un morceau libre de droits adapte a la niche.
Fallback : silence (pas de musique).
"""

import os
import random
import time

import httpx

PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")

# Mots-cles par niche pour la recherche musicale
NICHE_MUSIC_QUERIES = {
    "restauration": ["upbeat acoustic", "happy background", "cafe jazz"],
    "coiffure": ["trendy pop", "fashion beat", "stylish lounge"],
    "btp_artisan": ["motivational corporate", "inspiring background"],
    "dentiste": ["calm ambient", "gentle piano", "soft background"],
    "auto_garage": ["rock energy", "driving beat", "powerful background"],
    "sport_fitness": ["workout energy", "pump up beat", "gym motivation"],
    "immobilier": ["elegant corporate", "luxury ambient", "cinematic"],
    "photographe": ["cinematic ambient", "creative inspiration", "dreamy"],
}

# Duree min/max acceptee (secondes)
MIN_DURATION = 30
MAX_DURATION = 180


async def fetch_background_music(niche: str, target_duration: float = 60) -> str | None:
    """Telecharge une musique de fond adaptee a la niche.

    Returns:
        Chemin du fichier MP3 ou None si echec.
    """
    if not PIXABAY_API_KEY:
        print("[TIKTOK] Pas de PIXABAY_API_KEY, pas de musique de fond")
        return None

    queries = NICHE_MUSIC_QUERIES.get(niche, ["background music", "ambient"])
    query = random.choice(queries)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://pixabay.com/api/",
                params={
                    "key": PIXABAY_API_KEY,
                    "q": query,
                    "media_type": "music",
                    "per_page": 10,
                    "safesearch": "true",
                    "order": "popular",
                    "min_duration": MIN_DURATION,
                    "max_duration": MAX_DURATION,
                },
            )

            if resp.status_code != 200:
                print(f"[TIKTOK] Pixabay Music API {resp.status_code}")
                return None

            data = resp.json()
            hits = data.get("hits", [])

            if not hits:
                print(f"[TIKTOK] Pas de musique trouvee pour '{query}'")
                return None

            # Prendre un morceau aleatoire parmi les resultats
            track = random.choice(hits)
            audio_url = track.get("audio") or track.get("previewURL")

            if not audio_url:
                print("[TIKTOK] Pas d'URL audio dans la reponse Pixabay")
                return None

            # Telecharger
            ts = int(time.time())
            output_path = f"/tmp/instafarm/audio/music_{ts}.mp3"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            audio_resp = await client.get(audio_url, timeout=30)
            if audio_resp.status_code != 200:
                return None

            with open(output_path, "wb") as f:
                f.write(audio_resp.content)

            if os.path.getsize(output_path) < 10000:
                os.remove(output_path)
                return None

            print(f"[TIKTOK] Musique: {track.get('title', 'unknown')} ({track.get('duration', '?')}s)")
            return output_path

    except Exception as e:
        print(f"[TIKTOK] Music fetch erreur: {e}")
        return None
