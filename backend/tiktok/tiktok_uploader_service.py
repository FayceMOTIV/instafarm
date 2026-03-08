"""Service d'upload TikTok avec description + hashtags trending."""

import os

from backend.tiktok.trend_fetcher import get_trending_hashtags_fr


async def upload_tiktok_video(
    video_path: str,
    description: str,
    cookies_path: str,
    niche: str,
    schedule_time=None,
    hashtags: list[str] | None = None,
) -> dict:
    """Upload avec description complete = texte Groq + hashtags trending."""

    # 1. Recuperer les hashtags trending (ou fallback statiques)
    if hashtags is None:
        trending = await get_trending_hashtags_fr(niche, limit=8)
    else:
        trending = hashtags

    # 2. Assembler la description finale
    existing_tags = {word for word in description.split() if word.startswith("#")}
    additional_tags = [tag for tag in trending if tag not in existing_tags]

    # TikTok description : max 2200 chars
    full_description = description
    for tag in additional_tags[:5]:
        if len(full_description) + len(tag) + 1 < 2180:
            full_description += f" {tag}"

    print(f"[UPLOAD] Description ({len(full_description)} chars): {full_description[:150]}...")

    # 3. Upload via tiktok-uploader
    try:
        from tiktok_uploader.upload import upload_video

        result = upload_video(
            video_path,
            description=full_description,
            cookies=cookies_path,
            schedule=schedule_time,
        )

        return {
            "success": True,
            "description": full_description,
            "hashtags_used": trending,
            "result": result,
        }
    except ImportError:
        print("[UPLOAD] tiktok-uploader non installe — upload skip")
        return {
            "success": False,
            "error": "tiktok-uploader not installed",
            "description": full_description,
        }
    except Exception as e:
        from backend.tiktok.alerting import alert_upload_failure

        await alert_upload_failure(niche, str(e))
        return {
            "success": False,
            "error": str(e),
            "description": full_description,
        }
