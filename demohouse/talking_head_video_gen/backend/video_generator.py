"""Step 3: Generate a video clip via Seedance HTTP API.

Approach is taken from ``ad_video_gen`` director-agent's
``video_generate_http.py``.
"""

import asyncio
import logging
import os
import aiohttp
import requests
from dataclasses import dataclass

from file_link import local_to_link

logger = logging.getLogger(__name__)


@dataclass
class VideoGenerateResult:
    task_id: str
    video_path: str


class VideoGenerator:
    """Submit a Seedance video-generation task and poll until completion."""

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        poll_interval: int = 0,
    ):
        output_dir = os.getenv("OUTPUT_DIR", "output")
        self.api_key = api_key or os.getenv("VIDEO_API_KEY", "")
        self.api_base = (api_base or os.getenv("VIDEO_API_BASE", "")).rstrip("/")
        self.model = model or os.getenv("VIDEO_MODEL", "")
        self.poll_interval = poll_interval or int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
        self.video_path = os.path.join(output_dir, "gen_video.mp4")

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _create_task(
        self,
        prompt: str,
        first_frame_image_url: str | None = None,
        duration: int = 5,
    ) -> str:
        """Create a video generation task and return the task id."""
        content: list[dict] = [{"type": "text", "text": prompt}]
        if first_frame_image_url:
            content.append(
                {"type": "image_url", "image_url": {"url": first_frame_image_url}}
            )

        body = {
            "model": self.model,
            "content": content,
            "duration": duration,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_base}/contents/generations/tasks",
                json=body,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                task_id = data["id"]
                logger.debug("视频生成任务已创建，任务ID：%s", task_id)
                return task_id

    async def _poll_task(self, task_id: str) -> str:
        """Poll until the task succeeds and return the video URL."""
        async with aiohttp.ClientSession() as session:
            while True:
                async with session.get(
                    f"{self.api_base}/contents/generations/tasks/{task_id}",
                    headers=self._headers(),
                ) as resp:
                    resp.raise_for_status()
                    result = await resp.json()
                    status = result["status"]

                    if status == "succeeded":
                        video_url = result["content"]["video_url"]
                        logger.debug("视频任务完成，下载地址：%s", video_url)
                        return video_url
                    elif status == "failed":
                        error = result.get("error", "unknown error")
                        raise RuntimeError(
                            f"Video generation task {task_id} failed: {error}"
                        )
                    else:
                        logger.debug(
                            "任务轮询中，当前状态：%s，%d秒后重试。",
                            status, self.poll_interval,
                        )
                        await asyncio.sleep(self.poll_interval)

    async def generate(
        self,
        prompt: str,
        first_frame_image: str | None = None,
        duration: int = 5,
    ) -> VideoGenerateResult:
        """End-to-end: create task ➜ poll ➜ return result."""
        if os.path.exists(self.video_path):
            logger.debug("检测到已存在视频，跳过生成：%s", self.video_path)
            return VideoGenerateResult(task_id="existing_file", video_path=self.video_path)
        task_id = await self._create_task(prompt, local_to_link(first_frame_image), duration)
        video_url = await self._poll_task(task_id)
        response = requests.get(video_url, stream=True)
        response.raise_for_status()

        with open(self.video_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        logger.debug("视频下载并保存完成：%s", self.video_path)
        return VideoGenerateResult(task_id=task_id, video_path=self.video_path)
