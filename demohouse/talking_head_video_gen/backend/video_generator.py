"""Step 3: Generate a video clip via Seedance HTTP API.

Approach is taken from ``ad_video_gen`` director-agent's
``video_generate_http.py``.
"""

import asyncio
import logging
from dataclasses import dataclass

import aiohttp

import config

logger = logging.getLogger(__name__)


@dataclass
class VideoGenerateResult:
    task_id: str
    video_url: str


class VideoGenerator:
    """Submit a Seedance video-generation task and poll until completion."""

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        poll_interval: int = 0,
    ):
        self.api_key = api_key or config.VIDEO_API_KEY
        self.api_base = (api_base or config.VIDEO_API_BASE).rstrip("/")
        self.model = model or config.VIDEO_MODEL
        self.poll_interval = poll_interval or config.POLL_INTERVAL_SECONDS

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _create_task(
        self,
        prompt: str,
        first_frame_image: str | None = None,
        duration: int = 5,
    ) -> str:
        """Create a video generation task and return the task id."""
        content: list[dict] = [{"type": "text", "text": prompt}]
        if first_frame_image:
            content.append(
                {"type": "image_url", "image_url": {"url": first_frame_image}}
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
                logger.info("Created video task %s", task_id)
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
                        logger.info("Video task %s succeeded: %s", task_id, video_url)
                        return video_url
                    elif status == "failed":
                        error = result.get("error", "unknown error")
                        raise RuntimeError(
                            f"Video generation task {task_id} failed: {error}"
                        )
                    else:
                        logger.debug(
                            "Task %s status=%s, retrying in %ds…",
                            task_id, status, self.poll_interval,
                        )
                        await asyncio.sleep(self.poll_interval)

    async def generate(
        self,
        prompt: str,
        first_frame_image: str | None = None,
        duration: int = 5,
    ) -> VideoGenerateResult:
        """End-to-end: create task ➜ poll ➜ return result."""
        task_id = await self._create_task(prompt, first_frame_image, duration)
        video_url = await self._poll_task(task_id)
        return VideoGenerateResult(task_id=task_id, video_url=video_url)
