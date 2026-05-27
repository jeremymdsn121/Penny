"""Voice memo transcription via OpenAI Whisper.

Twilio delivers audio attachments as a URL (MediaUrl). We download the bytes
with Twilio credentials (Basic Auth) then send them to the Whisper API.
"""

import httpx
from openai import AsyncOpenAI

from app.config import settings


class TranscriptionError(Exception):
    """Raised when audio download or transcription fails."""


async def transcribe_twilio_audio(media_url: str) -> str:
    """Download a Twilio media URL and return the Whisper transcript.

    Args:
        media_url: The MediaUrl0 value from the Twilio webhook payload.
                   Requires Basic Auth with Twilio credentials.

    Returns:
        Transcribed text string.

    Raises:
        TranscriptionError: If the audio can't be fetched or transcribed.
    """
    if not settings.OPENAI_API_KEY:
        raise TranscriptionError(
            "OPENAI_API_KEY is not set — voice transcription is unavailable"
        )
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise TranscriptionError("Twilio credentials required to download media")

    # Download the audio from Twilio (requires Basic Auth).
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                media_url,
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                follow_redirects=True,
            )
        if resp.status_code >= 400:
            raise TranscriptionError(
                f"Failed to download audio: HTTP {resp.status_code}"
            )
        audio_bytes = resp.content
        content_type = resp.headers.get("content-type", "audio/ogg")
    except httpx.RequestError as exc:
        raise TranscriptionError(f"Network error downloading audio: {exc}") from exc

    # Determine a sensible filename extension from the content type.
    _EXT_MAP = {
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "mp4",
        "audio/wav": "wav",
        "audio/webm": "webm",
        "audio/amr": "amr",
    }
    ext = _EXT_MAP.get(content_type.split(";")[0].strip(), "ogg")
    filename = f"voice_memo.{ext}"

    # Send to Whisper.
    try:
        openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        transcript = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio_bytes, content_type),
        )
        return transcript.text
    except Exception as exc:
        raise TranscriptionError(f"Whisper transcription failed: {exc}") from exc
