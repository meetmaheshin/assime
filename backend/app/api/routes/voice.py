"""Voice endpoints backed by Cartesia (TTS + STT)."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.user import User
from app.services import voice as voice_svc

router = APIRouter(prefix="/voice", tags=["voice"])


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.get("/status")
async def voice_status() -> dict:
    return {
        "enabled": settings.voice_enabled,
        "stt": settings.resolved_stt_provider,
        "deepgram_key_set": bool(settings.deepgram_api_key),
        "stt_provider_setting": settings.stt_provider,
        "tts": "cartesia" if settings.voice_enabled else "none",
    }


@router.post("/tts")
async def tts(payload: TTSRequest, user: User = Depends(get_current_user)):
    # Stream so the browser can start playing before the whole clip is ready.
    return StreamingResponse(
        voice_svc.tts_stream(payload.text), media_type="audio/mpeg"
    )


@router.post("/stt")
async def stt(
    audio: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict:
    data = await audio.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty audio"
        )
    try:
        text = await voice_svc.stt(data, audio.filename or "clip.webm",
                                   audio.content_type or "audio/webm")
    except voice_svc.VoiceError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    return {"text": text}
