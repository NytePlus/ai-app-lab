"""Step 4: Synthesize speech from text via TTS.

Approach is taken from ``live_voice_call`` (arkitect AsyncTTSClient).
"""

import os
import logging
import asyncio
import re
import dashscope
from dataclasses import dataclass, field
from dashscope.audio.tts_v2 import VoiceEnrollmentService, SpeechSynthesizer

from arkitect.core.component.tts import AsyncTTSClient, AudioParams, ConnectionParams
from arkitect.core.component.tts.constants import (
    EventSessionFinished,
    EventTTSSentenceEnd,
)
from file_link import local_to_link


logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    audio_path: str | None = None
    format: str = "wav"


class CosyvoiceTTSSynthesizer:
    """Convert text into speech audio using the AliCloud DashScope CosyVoice service."""

    def __init__(
            self,
            api_key: str = "",
            model: str = "cosyvoice-v3.5-plus",
            voice_id: str = "",
            region: str = "cn-beijing"
    ):
        # 1. API Key 配置
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.api_key = self.api_key or os.getenv("TTS_APP_KEY", "")

        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY environment variable not set.")
        dashscope.api_key = self.api_key

        # 2. 地域端点配置 (北京 / 新加坡)
        if region == "ap-southeast-1" or "intl" in region:
            dashscope.base_websocket_api_url = 'wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference'
            dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'
        else:
            dashscope.base_websocket_api_url = 'wss://dashscope.aliyuncs.com/api-ws/v1/inference'
            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

        self.model = model
        self.voice_id = voice_id

        self._synthesizer: SpeechSynthesizer | None = None
        self._enrollment_service: VoiceEnrollmentService | None = None

    async def _init_client(self, clone_audio_path) -> None:
        """异步初始化客户端：如果传入了 voice_id 则直接使用；否则执行复刻流程。"""
        if self.voice_id:
            logger.debug("检测到已有voice_id，直接复用：%s", self.voice_id)
            self._synthesizer = SpeechSynthesizer(model=self.model, voice=self.voice_id)
            return

        if not clone_audio_path:
            raise ValueError("Either 'voice_id' or 'clone_audio_url' must be provided.")

        # --- Step 1: Creating voice enrollment ---
        logger.debug("开始创建音色复刻任务。")
        self._enrollment_service = VoiceEnrollmentService()

        # 将同步的 create_voice 放入线程池执行，防止阻塞 Event Loop
        clone_prefix = self._build_clone_prefix(clone_audio_path)
        clone_audio_url = local_to_link(clone_audio_path)
        self.voice_id = await asyncio.to_thread(
            self._enrollment_service.create_voice,
            target_model=self.model,
            prefix=clone_prefix,
            url=clone_audio_url
        )
        logger.debug("音色复刻任务已提交，voice_id：%s", self.voice_id)

        # --- Step 2: Polling for voice status ---
        logger.debug("开始轮询音色状态。")
        max_attempts = 30
        poll_interval = 10  # 秒

        for attempt in range(max_attempts):
            voice_info = await asyncio.to_thread(
                self._enrollment_service.query_voice,
                voice_id=self.voice_id
            )
            status = voice_info.get("status")
            logger.debug("第 %d/%d 次轮询，音色状态：%s", attempt + 1, max_attempts, status)

            if status == "OK":
                logger.debug("音色已就绪，可用于语音合成：%s", self.voice_id)
                break
            elif status == "UNDEPLOYED":
                raise RuntimeError(f"Voice processing failed with status: {status}. Check audio quality.")

            # 使用 asyncio.sleep 代替 time.sleep，实现非阻塞等待
            await asyncio.sleep(poll_interval)
        else:
            raise RuntimeError("Polling timed out. The voice is not ready after several attempts.")

        # 初始化最终的合成器
        self._synthesizer = SpeechSynthesizer(model=self.model, voice=self.voice_id)

    @staticmethod
    def _build_clone_prefix(clone_audio_path: str) -> str:
        """DashScope requires prefix length <= 10."""
        base = os.path.splitext(os.path.basename(clone_audio_path or ""))[0]
        cleaned = re.sub(r"[^A-Za-z0-9_-]", "", base)
        if not cleaned:
            cleaned = "voice"
        return cleaned[:10]

    async def synthesize(self, clone_audio_path: str, text: str) -> TTSResult:
        """将传入的文本合成为音频。"""
        if self._synthesizer is None:
            await self._init_client(clone_audio_path)
        output_dir = os.getenv("OUTPUT_DIR", "output")
        tts_audio_path = os.path.join(output_dir, "tts_audio.wav")
        if os.path.exists(tts_audio_path):
            logger.debug("检测到已有TTS音频，跳过合成：%s", tts_audio_path)
            return TTSResult(audio_path=tts_audio_path, format="wav")

        logger.debug("开始语音合成，voice_id：%s", self.voice_id)

        try:
            # 将同步的 call() 方法放入线程池执行，返回完整二进制音频数据
            audio_data = await asyncio.to_thread(self._synthesizer.call, text)

            logger.debug("语音合成完成，音频长度=%d字节", len(audio_data))

            with open(tts_audio_path, "wb") as f:
                f.write(audio_data)
            return TTSResult(audio_path=tts_audio_path, format="wav")

        except Exception as e:
            logger.error("Error during speech synthesis: %s", e)
            raise e

    async def close(self) -> None:
        """清理资源（如果有需要的话）。"""
        self._synthesizer = None
        self._enrollment_service = None
        logger.debug("TTSSynthesizer 已关闭。")

class SeedTTSWithoutSpeakerSynthesizer:
    """Convert text into speech audio using the volcengine TTS service."""

    def __init__(
        self,
        app_key: str = "",
        access_key: str = "",
        speaker: str = "",
    ):
        self.app_key = app_key or os.getenv("TTS_APP_KEY", "")
        self.access_key = access_key or os.getenv("TTS_ACCESS_KEY", "")
        self.speaker = speaker or os.getenv("TTS_SPEAKER", "zh_female_sajiaonvyou_moon_bigtts")
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
        logger.debug("TTS synthesis complete, audio length=%d bytes", len(buffer))
        return TTSResult(audio_data=bytes(buffer))
