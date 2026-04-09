"""Step 4: Synthesize speech from text via TTS.

Approach is taken from ``live_voice_call`` (arkitect AsyncTTSClient).
"""

import logging
from dataclasses import dataclass

from arkitect.core.component.tts import AsyncTTSClient, AudioParams, ConnectionParams
from arkitect.core.component.tts.constants import (
    EventSessionFinished,
    EventTTSSentenceEnd,
)

import config

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    audio_data: bytes
    format: str = "pcm"


class TTSSynthesizer:
    """Convert text into speech audio using the volcengine TTS service."""

    def __init__(
        self,
        app_key: str = "",
        access_key: str = "",
        speaker: str = "",
    ):
        self.app_key = app_key or config.TTS_APP_KEY
        self.access_key = access_key or config.TTS_ACCESS_KEY
        self.speaker = speaker or config.TTS_SPEAKER
        self._client: AsyncTTSClient | None = None

    async def _init_client(self) -> None:
        self._client = AsyncTTSClient(
            app_key=self.app_key,
            access_key=self.access_key,
            connection_params=ConnectionParams(
                speaker=self.speaker,
                audio_params=AudioParams(),
            ),
        )
        await self._client.init()

    async def synthesize(self, text: str) -> TTSResult:
        """Synthesize *text* into audio bytes.

        The text is wrapped in a trivial async generator so it can be fed into
        the streaming TTS interface used by ``live_voice_call``.
        """
        if self._client is None:
            await self._init_client()

        async def _text_gen():
            yield text

        buffer = bytearray()
        async for tts_resp in self._client.tts(source=_text_gen(), include_transcript=True):
            if tts_resp.event == EventTTSSentenceEnd:
                pass
            elif tts_resp.audio:
                buffer.extend(tts_resp.audio)

            if tts_resp.event == EventSessionFinished:
                break

        await self._client.close()
        logger.info("TTS synthesis complete, audio length=%d bytes", len(buffer))
        return TTSResult(audio_data=bytes(buffer))
