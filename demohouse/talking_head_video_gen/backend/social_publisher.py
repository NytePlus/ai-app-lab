"""Step 6: Publish the final video to social platforms.

This is a stub – the actual implementation depends on the target platform's
API (e.g. Douyin Open API, WeChat Channels, etc.).
Only the interface is defined here.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Platform(str, Enum):
    DOUYIN = "douyin"
    KUAISHOU = "kuaishou"
    WECHAT_CHANNELS = "wechat_channels"
    BILIBILI = "bilibili"
    XIAOHONGSHU = "xiaohongshu"


@dataclass
class PublishResult:
    platform: Platform
    success: bool
    video_id: str = ""
    url: str = ""
    error_message: str = ""


class BaseSocialPublisher(ABC):
    """Publish a video to a social media platform."""

    @abstractmethod
    async def publish(
        self,
        video_path: str,
        title: str,
        description: str,
        platform: Platform,
        tags: Optional[list[str]] = None,
        cover_image_path: Optional[str] = None,
    ) -> PublishResult:
        """Upload and publish a video.

        Args:
            video_path:       Local path of the final video file.
            title:            Video title.
            description:      Video description / caption.
            platform:         Target social platform.
            tags:             Optional hashtags / topic tags.
            cover_image_path: Optional path to a custom cover image.

        Returns:
            PublishResult indicating success or failure.
        """
        ...


class SocialPublisher(BaseSocialPublisher):
    """Placeholder implementation – replace with real platform SDK calls."""

    async def publish(
        self,
        video_path: str,
        title: str,
        description: str,
        platform: Platform,
        tags: Optional[list[str]] = None,
        cover_image_path: Optional[str] = None,
    ) -> PublishResult:
        raise NotImplementedError(
            f"SocialPublisher.publish() for {platform.value} is not yet implemented. "
            "Integrate the target platform's Open API here."
        )
