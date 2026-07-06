"""Cartesia voice: text-to-speech (Sonic) and speech-to-text (Ink-Whisper).

Server-side proxy so the Cartesia key never reaches the browser. Returns MP3
audio for TTS and a transcript string for STT.
"""
from __future__ import annotations

import logging
import re

import httpx

from app.core.config import settings


def _collapse_repeats(text: str) -> str:
    """Whisper sometimes loops a phrase on noisy/silent audio. Drop consecutive
    duplicate sentences, and if one sentence dominates, keep a single copy."""
    if not text:
        return text
    parts = re.split(r"(?<=[.!?।])\s+", text.strip())
    out: list[str] = []
    for p in parts:
        key = p.strip().lower()
        if key and (not out or out[-1].strip().lower() != key):
            out.append(p)
    # Collapse phrase-level loops (no punctuation) like "hi there hi there hi there".
    joined = " ".join(out)
    m = re.match(r"^(.{6,60}?)(?:\s+\1){2,}\s*$", joined.strip(), re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return joined.strip()

_BASE = "https://api.cartesia.ai"


def _headers() -> dict:
    return {
        "X-API-Key": settings.cartesia_api_key,
        "Cartesia-Version": settings.cartesia_version,
    }


class VoiceError(RuntimeError):
    pass


def _tts_payload(text: str, lang: str = "en") -> dict:
    return {
        "model_id": settings.resolved_tts_model,
        "transcript": text,
        "voice": {"mode": "id", "id": settings.cartesia_voice_id},
        "output_format": {
            "container": "mp3",
            "sample_rate": 44100,
            "bit_rate": 128000,
        },
        "language": "hi" if lang == "hi" else "en",
    }


async def tts_stream(text: str, lang: str = "en"):
    """Stream MP3 audio from Cartesia as it's generated (low latency).

    Yields byte chunks; the browser plays them progressively via MediaSource.
    On any failure it logs and simply ends the stream (empty), so the client
    can fall back to the browser's built-in speech instead of erroring.
    """
    if not settings.voice_enabled:
        return
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST", f"{_BASE}/tts/bytes", headers=_headers(),
                json=_tts_payload(text, lang),
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread())[:300].decode("utf-8", "replace")
                    logging.warning("Cartesia TTS failed (%s): %s", resp.status_code, body)
                    return
                async for chunk in resp.aiter_bytes():
                    yield chunk
    except Exception:
        logging.exception("Cartesia TTS stream error")
        return


async def _deepgram_stt(audio: bytes, content_type: str) -> str:
    """Deepgram nova-2, language=multi — strong on Hindi/Hinglish."""
    # Browser MediaRecorder sends "audio/webm;codecs=opus" — Deepgram wants the
    # bare container type, and the codecs param can trip it up.
    ct = (content_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    params = {
        "model": settings.resolved_deepgram_model,
        "language": settings.deepgram_language,
        "smart_format": "true",
        "punctuate": "true",
    }
    headers = {
        "Authorization": f"Token {settings.deepgram_api_key}",
        "Content-Type": ct,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.deepgram.com/v1/listen",
            params=params, headers=headers, content=audio)
    if resp.status_code != 200:
        raise VoiceError(f"Deepgram STT failed ({resp.status_code}): {resp.text[:300]}")
    try:
        alt = resp.json()["results"]["channels"][0]["alternatives"][0]
        text = (alt.get("transcript") or "").strip()
    except (KeyError, IndexError):
        text = ""
    logging.info("deepgram STT: %d bytes, ct=%s -> %d chars", len(audio), ct, len(text))
    return text


async def _cartesia_stt(audio: bytes, filename: str, content_type: str) -> str:
    files = {"file": (filename or "clip.webm", audio, content_type or "audio/webm")}
    data = {"model": settings.cartesia_stt_model}
    if settings.cartesia_stt_language:  # empty = auto-detect
        data["language"] = settings.cartesia_stt_language
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{_BASE}/stt", headers=_headers(), data=data, files=files)
    if resp.status_code != 200:
        raise VoiceError(f"STT failed ({resp.status_code}): {resp.text[:300]}")
    return (resp.json().get("text") or "").strip()


async def stt(audio: bytes, filename: str, content_type: str) -> str:
    """Transcribe an uploaded audio clip; returns the recognized text."""
    if settings.resolved_stt_provider == "deepgram":
        text = await _deepgram_stt(audio, content_type)
    elif settings.voice_enabled:
        text = await _cartesia_stt(audio, filename, content_type)
    else:
        raise VoiceError("No STT provider configured")
    return _collapse_repeats(text)
