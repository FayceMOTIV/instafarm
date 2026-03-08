"""Generateur de scripts video TikTok via Groq."""

import json
import os
import random
import time

import httpx

from backend.tiktok.config import HOOKS, TIKTOK_NICHE_CONFIG

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")

SYSTEM_PROMPT = """Tu es un expert en creation de contenus TikTok viraux pour des professionnels francais.
Tu generes des scripts video de 40-55 secondes qui captent l'attention, apportent de la valeur, et finissent par un CTA.

REGLES STRICTES :
- Duree totale : 40-55 secondes
- Structure : Hook (3s) -> Probleme (10s) -> Solution (20s) -> CTA (7s)
- Ton : naturel, comme un ami qui donne un conseil, JAMAIS commercial
- 4 a 6 scenes maximum
- Les image_prompt sont TOUJOURS en anglais, ultra detailles, cinematiques, JAMAIS de texte dans l'image
- Les subtitles font 5 mots max
- Le full_voiceover est le texte EXACT dit par la voix off, naturel et punchy
- Le CTA doit dire de commenter un mot-cle specifique

REGLES LANGUE FRANCAISE (la voix sera lue par un TTS) :
- INTERDIT : booster, booste, boostez → utilise : ameliorer, developper, augmenter
- INTERDIT : followers → utilise : abonnes
- INTERDIT : content → utilise : contenu
- INTERDIT : leads → utilise : prospects
- INTERDIT : tips → utilise : conseils, astuces
- INTERDIT : branding → utilise : image de marque
- Phrases courtes, max 15 mots, langage direct et dynamique
- Ecris en francais naturel, PAS de franglais

Tu reponds UNIQUEMENT en JSON valide, sans texte autour."""

USER_PROMPT_TEMPLATE = """Genere un script video TikTok pour la niche "{niche}" avec ce hook :
"{hook}"

Le mot-cle CTA est : {cta_keyword}

Reponds en JSON strict avec cette structure :
{{
  "hook": "phrase choc 3 secondes MAX",
  "scenes": [
    {{
      "narration": "texte dit par la voix off pour cette scene",
      "image_prompt": "prompt anglais ultra detaille pour generation image IA, style cinematique professionnel, NO TEXT in image, vertical 9:16 format",
      "duration_seconds": 8,
      "subtitle": "texte court affiche (5 mots max)"
    }}
  ],
  "cta": "Commente {cta_keyword} et recois notre strategie {niche} gratuite",
  "cta_keyword": "{cta_keyword}",
  "full_voiceover": "script complet mot pour mot, 40-50 secondes, naturel et punchy",
  "description_tiktok": "description TikTok avec emojis + hashtags pertinents",
  "music_mood": "upbeat"
}}"""


async def generate_video_script(niche: str, hook_index: int | None = None) -> dict:
    """Genere un script video TikTok complet via Groq."""
    niche_hooks = HOOKS.get(niche, HOOKS["restauration"])
    niche_config = TIKTOK_NICHE_CONFIG.get(niche, TIKTOK_NICHE_CONFIG["restauration"])

    if hook_index is not None and 0 <= hook_index < len(niche_hooks):
        hook = niche_hooks[hook_index]
    else:
        hook = random.choice(niche_hooks)

    cta_keyword = niche_config["cta_keywords"][0]  # Premier keyword = principal

    user_prompt = USER_PROMPT_TEMPLATE.format(
        niche=niche,
        hook=hook,
        cta_keyword=cta_keyword,
    )

    # Essayer Groq principal puis fallback
    for model in [GROQ_MODEL, GROQ_FALLBACK_MODEL]:
        try:
            result = await _call_groq(model, user_prompt)
            if result:
                # Sauvegarder le script
                ts = int(time.time())
                script_path = f"/tmp/instafarm/scripts/{niche}_{ts}.json"
                with open(script_path, "w") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                print(f"[TIKTOK] Script sauvegarde: {script_path}")
                return result
        except Exception as e:
            print(f"[TIKTOK] Erreur Groq ({model}): {e}")
            continue

    # Fallback : script template
    print("[TIKTOK] Fallback: script template")
    return _fallback_script(niche, hook, cta_keyword)


async def _call_groq(model: str, user_prompt: str) -> dict | None:
    """Appelle Groq et parse le JSON."""
    if not GROQ_API_KEY:
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 2000,
                "temperature": 0.8,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        data = resp.json()

        if "error" in data:
            raise ValueError(data["error"].get("message", str(data["error"])))

        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


def _fallback_script(niche: str, hook: str, cta_keyword: str) -> dict:
    """Script template si Groq est indisponible."""
    return {
        "hook": hook,
        "scenes": [
            {
                "narration": hook,
                "image_prompt": "Professional French restaurant interior, warm lighting, elegant table setting, cinematic, vertical 9:16, no text, photorealistic",
                "duration_seconds": 5,
                "subtitle": hook[:30],
            },
            {
                "narration": f"Beaucoup de professionnels dans la {niche} font cette erreur sans le savoir.",
                "image_prompt": f"Close-up of a stressed business owner looking at laptop screen, dramatic lighting, vertical 9:16, cinematic, no text",
                "duration_seconds": 8,
                "subtitle": "L'erreur classique",
            },
            {
                "narration": "La solution est plus simple que tu ne le penses. Il suffit d'appliquer ces trois strategies.",
                "image_prompt": "Bright lightbulb moment concept, golden light rays, clean modern office background, vertical 9:16, cinematic, no text",
                "duration_seconds": 10,
                "subtitle": "La solution simple",
            },
            {
                "narration": "Premiere strategie : sois present la ou tes clients te cherchent. Deuxieme : automatise ce qui peut l'etre. Troisieme : fidelise avec de la valeur.",
                "image_prompt": "Split screen showing three business strategy icons, modern infographic style, blue and white colors, vertical 9:16, no text",
                "duration_seconds": 15,
                "subtitle": "3 strategies cles",
            },
            {
                "narration": f"Commente {cta_keyword} et je t'envoie notre guide gratuit pour booster ton activite.",
                "image_prompt": "Happy professional celebrating success with fist pump, confetti, bright warm lighting, vertical 9:16, cinematic, no text",
                "duration_seconds": 7,
                "subtitle": f"Commente {cta_keyword}",
            },
        ],
        "cta": f"Commente {cta_keyword} et recois notre strategie {niche} gratuite",
        "cta_keyword": cta_keyword,
        "full_voiceover": f"{hook} Beaucoup de professionnels dans la {niche} font cette erreur sans le savoir. La solution est plus simple que tu ne le penses. Il suffit d'appliquer ces trois strategies. Premiere : sois present la ou tes clients te cherchent. Deuxieme : automatise ce qui peut l'etre. Troisieme : fidelise avec de la valeur. Commente {cta_keyword} et je t'envoie notre guide gratuit pour booster ton activite.",
        "description_tiktok": f"Le secret des pros de la {niche} qui cartonnent 🚀 Commente {cta_keyword} pour recevoir le guide gratuit ! #{niche} #business #entrepreneur #france",
        "music_mood": "upbeat",
    }
