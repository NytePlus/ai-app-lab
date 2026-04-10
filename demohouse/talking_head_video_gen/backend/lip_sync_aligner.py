"""Step 5: Align lip movements in a talking-head video to a given audio track."""

import asyncio
import json
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import requests

from file_link import local_to_link

try:
    from sync import Sync
    from sync.common import Audio, GenerationOptions, Video
    from sync.core.api_error import ApiError
except Exception:  # pragma: no cover - optional dependency in local envs
    Sync = None
    Audio = None
    GenerationOptions = None
    Video = None
    ApiError = Exception


logger = logging.getLogger(__name__)


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


class MuseTalkSyncAligner(BaseLipSyncAligner):
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


class Wav2LipSyncAligner(BaseLipSyncAligner):
    """Call sync.so lip-sync API and save the generated video to local output path."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "https://api.sync.so",
        model: str = "lipsync-2",
        sync_mode: str = "cut_off",
        max_audio_seconds: int = 20,
        ffmpeg_executable: str = "",
        poll_interval_seconds: int = 10,
        timeout_seconds: int = 3600,
    ) -> None:
        self.api_key = api_key or os.getenv("SYNC_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.sync_mode = sync_mode
        self.max_audio_seconds = max_audio_seconds
        self.ffmpeg_executable = ffmpeg_executable or os.getenv("FFMPEG_EXECUTABLE", "ffmpeg")
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds

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
        if Sync is None:
            raise RuntimeError("sync SDK is not installed. Please install package 'sync'.")
        if not self.api_key:
            raise RuntimeError("Missing SYNC_API_KEY for Wav2LipSyncAligner.")

        target_path = Path(output_path).expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        video_url = self._to_url_if_local(video_path)
        audio_source = self._prepare_audio_for_sync(audio_path)
        audio_url = self._to_url_if_local(audio_source)

        client = Sync(base_url=self.base_url, api_key=self.api_key).generations
        try:
            response = client.create(
                input=[Video(url=video_url), Audio(url=audio_url)],
                model=self.model,
                options=GenerationOptions(sync_mode=self.sync_mode),
                output_file_name=target_path.stem,
            )
        except ApiError as exc:
            raise RuntimeError(
                f"create generation request failed with status code {exc.status_code} and error {exc.body}"
            ) from exc

        job_id = response.id
        logger.debug("Sync lip-sync任务已提交，job_id=%s", job_id)
        output_url = self._poll_generation_output_url(client, job_id)

        self._download_file(output_url, target_path)
        return LipSyncResult(output_video_path=str(target_path))

    def _prepare_audio_for_sync(self, audio_path: str) -> str:
        parsed = urlparse(audio_path)
        if parsed.scheme in {"http", "https"}:
            logger.debug("输入音频为URL，跳过本地裁剪：%s", audio_path)
            return audio_path

        local_audio = Path(audio_path).expanduser().resolve()
        trimmed_audio = local_audio.with_name(f"{local_audio.stem}_20s{local_audio.suffix}")
        self._trim_audio_with_ffmpeg(local_audio, trimmed_audio, self.max_audio_seconds)
        return str(trimmed_audio)

    def _trim_audio_with_ffmpeg(self, source_path: Path, target_path: Path, max_seconds: int) -> None:
        command = [
            self.ffmpeg_executable,
            "-y",
            "-i",
            str(source_path),
            "-t",
            str(max_seconds),
            str(target_path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError as exc:
            raise RuntimeError(f"ffmpeg执行失败，请检查FFMPEG_EXECUTABLE配置: {exc}") from exc

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg音频裁剪失败: {result.stderr}")

        logger.debug("音频已用ffmpeg裁剪为最多%ss：%s", max_seconds, target_path)

    def _poll_generation_output_url(self, client: Any, job_id: str) -> str:
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            generation = client.get(job_id)
            status = getattr(generation, "status", "")
            if status == "COMPLETED":
                output_url = getattr(generation, "output_url", "")
                if not output_url:
                    raise RuntimeError(f"sync generation {job_id} completed but missing output_url")
                logger.debug("Sync lip-sync任务完成，输出地址：%s", output_url)
                return output_url
            if status == "FAILED":
                raise RuntimeError(f"sync generation {job_id} failed")

            logger.debug("Sync lip-sync轮询中，job_id=%s, status=%s", job_id, status)
            time.sleep(self.poll_interval_seconds)

        raise TimeoutError(f"sync generation {job_id} timed out after {self.timeout_seconds}s")

    def _download_file(self, url: str, target_path: Path) -> None:
        try:
            response = requests.get(url, stream=True, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to download sync output video: {exc}") from exc

        with target_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    @staticmethod
    def _to_url_if_local(path_or_url: str) -> str:
        parsed = urlparse(path_or_url)
        if parsed.scheme in {"http", "https"}:
            return path_or_url
        return local_to_link(str(Path(path_or_url).expanduser().resolve()))
