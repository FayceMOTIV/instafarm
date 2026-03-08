"""Generateur d'images IA pour les scenes TikTok.

Cascade : Replicate Flux Schnell ($0.003/img) -> PIL gradient fallback.
"""

import asyncio
import os
import random
import time
from io import BytesIO

import httpx
from PIL import Image, ImageDraw, ImageFont

REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY", "")

# Style par niche pour enrichir les prompts Flux
NICHE_STYLE = {
    "restauration": "cozy French restaurant, warm lighting, professional food photography, appetizing",
    "coiffure": "modern hair salon, professional hairstylist, bright studio lighting",
    "btp_artisan": "professional craftsman, construction site, high quality renovation",
    "dentiste": "modern dental clinic, clean white interior, professional",
    "auto_garage": "professional auto repair garage, modern equipment",
    "sport_fitness": "modern gym, fitness training, energetic atmosphere",
    "immobilier": "luxury real estate, modern interior design, natural lighting",
    "photographe": "professional photography studio, creative atmosphere",
}

# Couleurs gradient par niche (fallback)
NICHE_GRADIENT_COLORS = {
    "restauration": [(255, 87, 34), (255, 152, 0)],
    "coiffure": [(156, 39, 176), (233, 30, 99)],
    "btp_artisan": [(33, 150, 243), (3, 169, 244)],
    "dentiste": [(0, 188, 212), (0, 150, 136)],
    "auto_garage": [(96, 125, 139), (55, 71, 79)],
    "sport_fitness": [(255, 193, 7), (255, 87, 34)],
    "immobilier": [(76, 175, 80), (139, 195, 74)],
    "photographe": [(33, 33, 33), (97, 97, 97)],
}


def _build_flux_prompt(image_prompt: str, niche: str) -> str:
    """Construit un prompt Flux Schnell optimal."""
    style = NICHE_STYLE.get(niche, "professional business")

    # Les image_prompts du script Groq sont deja en anglais et detailles
    # On les enrichit avec le style niche + directives qualite
    base = image_prompt.rstrip(", .")

    return (
        f"{base}, {style}, "
        f"vertical portrait format 9:16, photorealistic, high quality, "
        f"cinematic lighting, sharp focus, 4K, professional photography, "
        f"no text no watermark no logo"
    )


async def generate_scene_image(prompt: str, scene_index: int, niche: str = "restauration") -> str:
    """Genere une image pour une scene. Retourne le chemin du fichier."""
    ts = int(time.time())
    output_path = f"/tmp/instafarm/scenes/scene_{scene_index}_{ts}.jpg"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Provider 1 : Replicate Flux Schnell
    flux_prompt = _build_flux_prompt(prompt, niche)
    if await _generate_flux_schnell(flux_prompt, output_path):
        print(f"[TIKTOK] Image scene {scene_index}: Flux Schnell")
        return output_path

    # Provider 2 : Gradient PIL fallback
    _generate_gradient(prompt, niche, scene_index, output_path)
    print(f"[TIKTOK] Image scene {scene_index}: gradient PIL fallback")
    return output_path


async def generate_all_images(scenes: list[dict], niche: str = "restauration") -> list[str]:
    """Genere toutes les images en parallele."""
    print(f"[TIKTOK] Generation de {len(scenes)} images...")
    tasks = [
        generate_scene_image(scene["image_prompt"], i, niche)
        for i, scene in enumerate(scenes)
    ]
    return await asyncio.gather(*tasks)


async def _generate_flux_schnell(prompt: str, output_path: str) -> bool:
    """Replicate Flux Schnell — $0.003/image, ~3-5s."""
    if not REPLICATE_API_KEY:
        return False

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # Lancer la prediction avec Prefer: wait (sync)
            resp = await client.post(
                "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions",
                headers={
                    "Authorization": f"Bearer {REPLICATE_API_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "wait",
                },
                json={
                    "input": {
                        "prompt": prompt,
                        "num_inference_steps": 4,
                        "output_format": "jpg",
                        "output_quality": 90,
                        "go_fast": True,
                        "aspect_ratio": "9:16",
                    },
                },
            )

            if resp.status_code not in (200, 201):
                print(f"[TIKTOK] Flux API {resp.status_code}: {resp.text[:200]}")
                return False

            data = resp.json()
            output = data.get("output")

            # Si pas de resultat immediat, polling
            if not output:
                prediction_id = data.get("id")
                if not prediction_id:
                    return False

                for _ in range(30):
                    await asyncio.sleep(1)
                    poll = await client.get(
                        f"https://api.replicate.com/v1/predictions/{prediction_id}",
                        headers={"Authorization": f"Bearer {REPLICATE_API_KEY}"},
                    )
                    poll_data = poll.json()
                    if poll_data.get("status") == "succeeded":
                        output = poll_data.get("output")
                        break
                    if poll_data.get("status") == "failed":
                        print(f"[TIKTOK] Flux failed: {poll_data.get('error', '')[:200]}")
                        return False

            if not output:
                return False

            img_url = output[0] if isinstance(output, list) else output

            # Telecharger l'image
            img_resp = await client.get(img_url, timeout=30)
            if img_resp.status_code != 200:
                return False

            with open(output_path, "wb") as f:
                f.write(img_resp.content)

            return os.path.getsize(output_path) > 10000

    except Exception as e:
        print(f"[TIKTOK] Flux erreur: {e}")
        return False


def _generate_gradient(text: str, niche: str, scene_index: int, output_path: str) -> None:
    """Gradient colore par niche avec texte (fallback)."""
    colors = NICHE_GRADIENT_COLORS.get(niche, [(63, 81, 181), (103, 58, 183)])
    W, H = 1080, 1920

    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    for y in range(H):
        r = int(colors[0][0] + (colors[1][0] - colors[0][0]) * y / H)
        g = int(colors[0][1] + (colors[1][1] - colors[0][1]) * y / H)
        b = int(colors[0][2] + (colors[1][2] - colors[0][2]) * y / H)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Overlay sombre
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 80))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 72)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
    except Exception:
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
        except Exception:
            font_large = ImageFont.load_default()
            font_small = font_large

    draw.text((W // 2, H // 2 - 100), f"SCENE {scene_index + 1}",
              fill="white", font=font_large, anchor="mm")

    short_text = text.split(",")[0].strip()[:80]
    words = short_text.split()
    lines, current = [], []
    for word in words:
        if len(" ".join(current + [word])) < 25:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))

    for i, line in enumerate(lines[:3]):
        draw.text((W // 2, H // 2 + 50 + i * 60), line,
                  fill="white", font=font_small, anchor="mm")

    for _ in range(8):
        x = random.randint(50, W - 50)
        y = random.randint(50, H - 50)
        r = random.randint(15, 60)
        c = (min(colors[0][0] + 40, 255), min(colors[0][1] + 40, 255), min(colors[0][2] + 40, 255))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c)

    img.save(output_path, "JPEG", quality=95)
