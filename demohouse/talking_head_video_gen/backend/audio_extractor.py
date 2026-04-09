"""Step 1: Extract audio track from a video URL.

This is a stub – the actual implementation depends on the chosen web tool /
ffmpeg service. Only the interface is defined here.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AudioExtractResult:
    audio_path: str
    duration_seconds: float
    sample_rate: int = 16000
    format: str = "wav"


class BaseAudioExtractor(ABC):
    """Extract the audio track from a source video."""

    @abstractmethod
    async def extract(self, video_url: str, output_path: str) -> AudioExtractResult:
        """Download the video at *video_url* and write the extracted audio to
        *output_path*.

        Args:
            video_url:   Public URL of the source video.
            output_path: Local path where the audio file should be saved.

        Returns:
            AudioExtractResult with metadata about the extracted audio.
        """
        ...


class AudioExtractor(BaseAudioExtractor):
    """Placeholder implementation – replace with ffmpeg / web-tool logic."""

    async def extract(self, video_url: str, output_path: str) -> AudioExtractResult:
        raise NotImplementedError(
            "AudioExtractor.extract() is not yet implemented. "
            "Integrate ffmpeg or a remote audio-extraction service here."
        )
