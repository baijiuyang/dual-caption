"""Soniox async transcription using the official Python SDK."""

import json
import os
import tempfile

from soniox import SonioxClient
from soniox.types import (
    CreateTranscriptionConfig,
    StructuredContext,
    StructuredContextGeneralItem,
)
from soniox.utils import render_tokens


def transcribe_audio(audio_bytes: bytes, filename: str, api_key: str) -> str:
    """Return plain-text transcript."""
    result = _transcribe(audio_bytes, filename, api_key)
    return render_tokens(result.tokens, [])


def transcribe_audio_json(audio_bytes: bytes, filename: str, api_key: str) -> str:
    """Return JSON transcript with per-token timestamps (start_ms, end_ms)."""
    result = _transcribe(audio_bytes, filename, api_key)
    tokens = [token.model_dump(exclude_none=True) for token in result.tokens]
    return json.dumps(tokens, ensure_ascii=False, indent=2)


def _transcribe(audio_bytes: bytes, filename: str, api_key: str):
    client = SonioxClient(api_key=api_key)

    suffix = os.path.splitext(filename)[1] or ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        file = client.files.upload(tmp_path)
    finally:
        os.unlink(tmp_path)

    config = CreateTranscriptionConfig(
        model="stt-async-v4",
        language_hints=["en", "zh"],
        context=StructuredContext(
            general=[
                StructuredContextGeneralItem(key="speaker", value="Joey"),
                StructuredContextGeneralItem(
                    key="speaker_languages",
                    value="Native Chinese speaker, also speaks English",
                ),
                StructuredContextGeneralItem(key="content_type", value="Biking vlog"),
                StructuredContextGeneralItem(
                    key="topic",
                    value="Biking tour across the United States along the Northern Tier route",
                ),
            ],
            text="Joey is a Chinese speaker who also speaks English. He is vlogging his bicycle tour across the United States along the Northern Tier route from the Adventure Cycling Association.",
        ),
    )
    try:
        transcription = client.stt.create(config=config, file_id=file.id)
        client.stt.wait(transcription.id)
        return client.stt.get_transcript(transcription.id)
    finally:
        client.stt.delete(transcription.id)
        client.files.delete(file.id)
