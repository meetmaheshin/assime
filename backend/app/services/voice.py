"""Cartesia voice: text-to-speech (Sonic) and speech-to-text (Ink-Whisper).

Server-side proxy so the Cartesia key never reaches the browser. Returns MP3
audio for TTS and a transcript string for STT.
"""
from __future__ import annotations

import httpx

from app.core.config import settings

_BASE = "https://api.cartesia.ai"


def _headers() -> dict:
    return {
        "X-API-Key": settings.cartesia_api_key,
        "Cartesia-Version": settings.cartesia_version,
    }


class VoiceError(RuntimeError):
    pass


def _tts_payload(text: str) -> dict:
    return {
        "model_id": settings.cartesia_tts_model,
        "transcript": text,
        "voice": {"mode": "id", "id": settings.cartesia_voice_id},
        "output_format": {
            "container": "mp3",
            "sample_rate": 44100,
            "bit_rate": 128000,
        },
        "language": "en",
    }


async def tts_stream(text: str):
    """Stream MP3 audio from Cartesia as it's generated (low latency).

    Yields byte chunks; the browser plays them progressively via MediaSource.
    """
    if not settings.voice_enabled:
        raise VoiceError("Cartesia not configured")
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST", f"{_BASE}/tts/bytes", headers=_headers(), json=_tts_payload(text)
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread())[:300].decode("utf-8", "replace")
                raise VoiceError(f"TTS failed ({resp.status_code}): {body}")
            async for chunk in resp.aiter_bytes():
                yield chunk


async def stt(audio: bytes, filename: str, content_type: str) -> str:
    """Transcribe an uploaded audio clip; returns the recognized text."""
    if not settings.voice_enabled:
        raise VoiceError("Cartesia not configured")
    files = {"file": (filename or "clip.webm", audio, content_type or "audio/webm")}
    data = {"model": settings.cartesia_stt_model, "language": "en"}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{_BASE}/stt", headers=_headers(), data=data, files=files
        )
    if resp.status_code != 200:
        raise VoiceError(f"STT failed ({resp.status_code}): {resp.text[:300]}")
    return (resp.json().get("text") or "").strip()
