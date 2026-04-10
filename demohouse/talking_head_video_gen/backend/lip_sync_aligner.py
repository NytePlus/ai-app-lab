"""Step 5: Align lip movements in a talking-head video to a given audio track.

This is a stub – the actual implementation depends on a Wav2Lip-compatible
service.  Only the interface is defined here.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import requests


@dataclass
class LipSyncResult:
    output_video_path: str


class BaseLipSyncAligner(ABC):
    """Align lip movements in a video to match an audio track."""

    @abstractmethod
    async def align(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
    ) -> LipSyncResult:
        """Apply lip-sync alignment.

        Args:
            video_path:  Path (or URL) of the talking-head video.
            audio_path:  Path (or URL) of the synthesized audio.
            output_path: Where to write the aligned output video.

        Returns:
            LipSyncResult with the path and duration of the output.
        """
        ...


class LipSyncAligner(BaseLipSyncAligner):
    """Call MuseTalk service (`app.py`) to perform lip-sync alignment."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000",
        timeout_seconds: int = 3600,
        synthesize_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.synthesize_params = synthesize_params or {}

    async def align(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
    ) -> LipSyncResult:
        return await asyncio.to_thread(
            self._align_sync,
            video_path,
            audio_path,
            output_path,
        )

    def _align_sync(self, video_path: str, audio_path: str, output_path: str) -> LipSyncResult:
        target_path = Path(output_path).expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        payload: Dict[str, Any] = {
            "video_source": self._to_absolute_if_local(video_path),
            "audio_source": self._to_absolute_if_local(audio_path),
            "output_name": str(target_path),
            "return_mode": "link",
        }
        payload.update(self.synthesize_params)

        synthesize_url = f"{self.base_url}/api/v1/synthesize"
        try:
            resp = requests.post(synthesize_url, json=payload, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to call synthesize endpoint: {exc}") from exc

        if resp.status_code >= 400:
            raise RuntimeError(self._format_http_error("synthesize", resp))

        try:
            result = resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Synthesize response is not valid JSON: {resp.text}") from exc

        download_url = result.get("download_url")
        if not download_url:
            raise RuntimeError(f"Missing 'download_url' in synthesize response: {result}")

        file_url = urljoin(f"{self.base_url}/", str(download_url).lstrip("/"))
        try:
            file_resp = requests.get(file_url, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to download output file: {exc}") from exc

        if file_resp.status_code >= 400:
            raise RuntimeError(self._format_http_error("download", file_resp))

        target_path.write_bytes(file_resp.content)

        return LipSyncResult(
            output_video_path=str(target_path),
        )

    @staticmethod
    def _to_absolute_if_local(path_or_url: str) -> str:
        parsed = urlparse(path_or_url)
        if parsed.scheme in {"http", "https"}:
            return path_or_url
        return str(Path(path_or_url).expanduser().resolve())

    @staticmethod
    def _format_http_error(stage: str, response: requests.Response) -> str:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        return f"{stage} failed with status {response.status_code}: {detail}"
