"""Pipeline TikTok end-to-end.

Script -> Images -> Voice -> Video assembly -> Upload.
"""

import os
import time
import traceback

from backend.tiktok.broll_fetcher import fetch_broll_clips
from backend.tiktok.image_generator import generate_all_images
from backend.tiktok.music_fetcher import fetch_background_music
from backend.tiktok.script_generator import generate_video_script
from backend.tiktok.video_assembler import assemble_video
from backend.tiktok.voice_generator import generate_voiceover


async def generate_tiktok_video(niche: str, hook_index: int | None = None) -> dict:
    """Pipeline complet : genere une video TikTok de A a Z.

    Returns:
        dict avec video_path, script, audio_path, image_paths, duration, etc.
    """
    start_time = time.time()

    # Creer les dossiers temporaires
    for d in ["scripts", "scenes", "audio", "videos"]:
        os.makedirs(f"/tmp/instafarm/{d}", exist_ok=True)

    # 1. Generer le script via Groq
    print(f"[TIKTOK] === Pipeline {niche} ===")
    print("[TIKTOK] 1/4 Generation du script...")
    script = await generate_video_script(niche, hook_index)
    scenes = script.get("scenes", [])
    voiceover_text = script.get("full_voiceover", "")

    if not scenes:
        raise ValueError("Script invalide: pas de scenes")
    if not voiceover_text:
        # Fallback : concatener les narrations
        voiceover_text = " ".join(s.get("narration", "") for s in scenes)

    print(f"[TIKTOK]   Hook: {script.get('hook', '')[:60]}")
    print(f"[TIKTOK]   Scenes: {len(scenes)}")

    # 2. Generer images + voix + musique + B-rolls en parallele
    print("[TIKTOK] 2/4 Generation images + voix + musique + B-rolls (parallele)...")
    import asyncio
    images_task = generate_all_images(scenes, niche)
    voice_task = generate_voiceover(voiceover_text)
    music_task = fetch_background_music(niche)
    broll_task = fetch_broll_clips(scenes, niche)

    image_paths, (audio_path, audio_duration), music_path, broll_paths = (
        await asyncio.gather(images_task, voice_task, music_task, broll_task)
    )

    # Remplacer les images par des B-rolls quand disponibles
    broll_count = 0
    for i, broll in enumerate(broll_paths):
        if broll and os.path.exists(broll):
            image_paths[i] = broll
            broll_count += 1

    print(f"[TIKTOK]   Images: {len(image_paths)} ({broll_count} B-rolls)")
    print(f"[TIKTOK]   Audio: {audio_duration:.1f}s")
    print(f"[TIKTOK]   Musique: {'oui' if music_path else 'non'}")

    # 3. Assembler la video
    print("[TIKTOK] 3/4 Assemblage video FFmpeg...")
    video_path = await assemble_video(
        image_paths=image_paths,
        audio_path=audio_path,
        scenes=scenes,
        audio_duration=audio_duration,
        music_path=music_path,
    )

    elapsed = time.time() - start_time
    print(f"[TIKTOK] 4/4 DONE en {elapsed:.0f}s")

    result = {
        "success": True,
        "video_path": video_path,
        "script": script,
        "audio_path": audio_path,
        "audio_duration": audio_duration,
        "image_paths": image_paths,
        "niche": niche,
        "hook": script.get("hook", ""),
        "description_tiktok": script.get("description_tiktok", ""),
        "cta_keyword": script.get("cta_keyword", ""),
        "elapsed_seconds": round(elapsed, 1),
    }

    return result


async def run_video_pipeline(niche: str, publish: bool = False, **kwargs) -> dict:
    """Pipeline complet : generation + upload optionnel."""
    result = await generate_tiktok_video(niche, **kwargs)

    if publish and result.get("success"):
        from backend.firebase import db
        doc = db.collection("tiktok_accounts").document(niche).get()
        if doc.exists:
            account = doc.to_dict()
            cookies_path = account.get("cookies_path")
            if cookies_path and os.path.exists(cookies_path):
                from backend.tiktok.tiktok_uploader_service import upload_tiktok_video

                upload_result = await upload_tiktok_video(
                    video_path=result["video_path"],
                    description=result.get("description_tiktok", f"Video {niche}"),
                    cookies_path=cookies_path,
                    niche=niche,
                )
                result["upload"] = upload_result

                if upload_result.get("success"):
                    from backend.tiktok.account_manager import mark_video_published
                    await mark_video_published(niche, db)
            else:
                result["upload"] = {"success": False, "error": "No valid cookies"}
        else:
            result["upload"] = {"success": False, "error": "No account for niche"}

    # Enregistrer le job en Firebase
    try:
        from backend.firebase import db
        from datetime import datetime, timezone

        db.collection("tiktok_pipeline_jobs").add({
            "niche": niche,
            "success": result.get("success", False),
            "video_path": result.get("video_path"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "hook": result.get("hook"),
            "published": publish,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception:
        pass

    return result


async def run_video_pipeline_safe(niche: str, **kwargs) -> dict:
    """Wrapper avec gestion d'erreurs — jamais de crash silencieux."""
    try:
        result = await run_video_pipeline(niche=niche, **kwargs)

        if not result.get("success"):
            from backend.tiktok.alerting import alert_pipeline_failure
            await alert_pipeline_failure(
                niche=niche,
                error=result.get("error", "Unknown error"),
                job_id=result.get("job_id"),
            )

        return result

    except Exception as e:
        error_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"
        from backend.tiktok.alerting import alert_pipeline_failure
        await alert_pipeline_failure(niche=niche, error=error_detail)

        return {
            "success": False,
            "niche": niche,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
