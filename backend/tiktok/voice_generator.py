"""Generateur de voix off TikTok.

Cascade : ElevenLabs multilingual v2 -> Fish Audio -> Edge-TTS (fallback).
"""

import asyncio
import os
import re
import time

import edge_tts
import httpx

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "XB0fDUnXU5powFXDhCwa")  # Charlotte FR

FISH_AUDIO_API_KEY = os.getenv("FISH_AUDIO_API_KEY", "")
FISH_VOICES_FR = {
    "female": "a14863fa7f2b4e43b012be0ce0c93be2",
    "male": "54a5170264694bfc8e04106377a6b57a",
}

EDGE_TTS_VOICE = "fr-FR-DeniseNeural"
EDGE_TTS_RATE = "+5%"

# Corrections anglicismes pour TTS francais
ANGLICISM_CORRECTIONS = {
    "booster vos": "ameliorer vos",
    "booster votre": "ameliorer votre",
    "booster ton": "ameliorer ton",
    "booster": "developper",
    "boostez": "developpez",
    "booste": "developpe",
    "followers": "abonnes",
    "branding": "image de marque",
    "hashtag": "hashtague",
    "hashtags": "hashtagues",
    "content": "contenu",
    "leads": "prospects",
    "tips": "conseils",
    "call to action": "appel a l'action",
    "ROI": "retour sur investissement",
    "funnel": "entonnoir",
    "benchmark": "reference",
    "workflow": "processus",
    "checklist": "liste de controle",
    "best practices": "meilleures pratiques",
    "discount": "reduction",
    "pricing": "tarifs",
    "package": "forfait",
    "feedback": "retour",
    "post": "publication",
    "posts": "publications",
}


def preprocess_text_for_french_tts(text: str) -> str:
    """Corrige les anglicismes pour une prononciation TTS naturelle."""
    result = text
    for eng, fr in ANGLICISM_CORRECTIONS.items():
        result = re.sub(r'\b' + re.escape(eng) + r'\b', fr, result, flags=re.IGNORECASE)
    return result


async def generate_voiceover(text: str, engine: str = "auto") -> tuple[str, float]:
    """Genere la voix off. Retourne (chemin_audio, duree_secondes)."""
    ts = int(time.time())
    output_path = f"/tmp/instafarm/audio/voiceover_{ts}.mp3"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Preprocessing : corriger les anglicismes
    cleaned_text = preprocess_text_for_french_tts(text)

    # Cascade : ElevenLabs -> Fish Audio -> Edge-TTS
    generators = [_generate_elevenlabs, _generate_fish_audio, _generate_edgetts]

    for gen in generators:
        try:
            result = await gen(cleaned_text, output_path)
            if result and os.path.exists(result) and os.path.getsize(result) > 1000:
                duration = await _get_audio_duration(result)
                print(f"[TIKTOK] Voiceover: {result} ({duration:.1f}s, {gen.__name__})")
                return result, duration
        except Exception as e:
            print(f"[TIKTOK] Voice erreur ({gen.__name__}): {e}")
            continue

    raise RuntimeError("Impossible de generer la voix off")


async def _generate_elevenlabs(text: str, output_path: str) -> str | None:
    """ElevenLabs multilingual v2 — meilleure voix FR."""
    if not ELEVENLABS_API_KEY:
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.45,
                    "similarity_boost": 0.85,
                    "style": 0.3,
                    "use_speaker_boost": True,
                },
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[TIKTOK] ElevenLabs {resp.status_code}: {resp.text[:200]}")
            return None

        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path


async def _generate_fish_audio(text: str, output_path: str) -> str | None:
    """Fish Audio TTS — backup qualite FR."""
    if not FISH_AUDIO_API_KEY:
        return None

    from fish_audio_sdk import Session, TTSRequest

    session = Session(apikey=FISH_AUDIO_API_KEY)
    voice_id = FISH_VOICES_FR["female"]

    request = TTSRequest(
        text=text,
        reference_id=voice_id,
        format="mp3",
        mp3_bitrate=128,
    )

    with open(output_path, "wb") as f:
        for chunk in session.tts(request):
            f.write(chunk)

    return output_path


async def _generate_edgetts(text: str, output_path: str) -> str:
    """Edge-TTS gratuit (Microsoft) — dernier recours."""
    communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE, rate=EDGE_TTS_RATE)
    await communicate.save(output_path)
    return output_path


async def _get_audio_duration(path: str) -> float:
    """Duree audio via ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
    except Exception:
        return 45.0
