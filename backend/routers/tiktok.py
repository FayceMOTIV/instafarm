"""API Router TikTok — generation de videos."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.tiktok.pipeline import generate_tiktok_video

router = APIRouter()


class GenerateRequest(BaseModel):
    niche: str
    hook_index: int | None = None


class GenerateResponse(BaseModel):
    video_path: str
    audio_path: str
    audio_duration: float
    hook: str
    description_tiktok: str
    cta_keyword: str
    elapsed_seconds: float
    image_count: int


@router.post("/generate", response_model=GenerateResponse)
async def generate_video(req: GenerateRequest):
    """Genere une video TikTok complete pour une niche."""
    try:
        result = await generate_tiktok_video(req.niche, req.hook_index)
        return GenerateResponse(
            video_path=result["video_path"],
            audio_path=result["audio_path"],
            audio_duration=result["audio_duration"],
            hook=result["hook"],
            description_tiktok=result["description_tiktok"],
            cta_keyword=result["cta_keyword"],
            elapsed_seconds=result["elapsed_seconds"],
            image_count=len(result["image_paths"]),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
