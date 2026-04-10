"""Talking-Head Video Generation Pipeline

Pipeline stages:
  1. AudioExtractor     – extract audio from source video  (stub)
  2. CopywritingRewriter – ASR transcription + LLM rewrite
  3. VideoGenerator      – generate video via Seedance
  4. TTSSynthesizer      – synthesize speech via TTS
  5. LipSyncAligner      – lip-sync alignment              (stub)
  6. SocialPublisher     – publish to social platforms      (stub)
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import logging
import os
from dataclasses import asdict, dataclass
from typing import Any, Optional

from audio_extractor import DouyinAudioExtractor, AudioExtractResult
from copywriting_rewriter import CopywritingRewriter, CopywritingResult
from video_generator import VideoGenerator, VideoGenerateResult
from tts_synthesizer import CosyvoiceTTSSynthesizer, TTSResult
from lip_sync_aligner import Wav2LipSyncAligner, LipSyncResult
from social_publisher import SocialPublisher, Platform, PublishResult

logging.basicConfig(
    level=getattr(logging, os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _to_yaml_like(data: Any, indent: int = 0) -> str:
    space = "  " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{space}{key}:")
                lines.append(_to_yaml_like(value, indent + 1))
            else:
                lines.append(f"{space}{key}: {value!r}")
        return "\n".join(lines)

    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{space}-")
                lines.append(_to_yaml_like(item, indent + 1))
            else:
                lines.append(f"{space}- {item!r}")
        return "\n".join(lines)

    return f"{space}{data!r}"


@dataclass
class PipelineResult:
    """Aggregated result of the full pipeline run."""
    audio_extract: Optional[AudioExtractResult] = None
    copywriting: Optional[CopywritingResult] = None
    video_generate: Optional[VideoGenerateResult] = None
    tts: Optional[TTSResult] = None
    lip_sync: Optional[LipSyncResult] = None
    publish: Optional[PublishResult] = None


class TalkingHeadPipeline:
    """Orchestrate the six-stage talking-head video generation pipeline."""

    def __init__(self):
        self.output_dir = os.getenv("OUTPUT_DIR", "output")
        self.audio_extractor = DouyinAudioExtractor()
        self.copywriting_rewriter = CopywritingRewriter()
        self.video_generator = VideoGenerator()
        self.tts_synthesizer = CosyvoiceTTSSynthesizer()
        self.lip_sync_aligner = Wav2LipSyncAligner()
        self.social_publisher = SocialPublisher()

        os.makedirs(self.output_dir, exist_ok=True)

    async def run(
        self,
        sharelink: str,
        video_prompt: str,
        clone_audio_path: str,
        first_frame_image: Optional[str] = None,
        publish_platform: Optional[Platform] = None,
        publish_title: str = "",
        publish_description: str = "",
    ) -> PipelineResult:
        result = PipelineResult()

        logger.info("[Step 1/6] Audio Extraction")
        audio_output_path = os.path.join(self.output_dir, "source_audio.wav")
        try:
            logger.debug("开始执行抖音登录校验。")
            await self.audio_extractor.login()
            logger.debug("开始从分享链接提取音频，输出路径：%s", audio_output_path)
            result.audio_extract = await self.audio_extractor.extract(
                sharelink=sharelink,
                output_path=audio_output_path,
            )
            logger.debug("音频提取完成：%s", result.audio_extract.audio_path)
        except NotImplementedError:
            logger.warning(
                "AudioExtractor not implemented; skipping. "
                "Provide audio_chunks directly to Step 2 in production."
            )

        logger.info("[Step 2/6] Copywriting Transcription & Rewrite")
        if result.audio_extract:
            logger.debug("开始ASR转写，输入音频：%s", result.audio_extract.audio_path)
            result.copywriting = await self.copywriting_rewriter.run(
                result.audio_extract.audio_path
            )
            logger.debug("文案改写完成，改写后长度：%d", len(result.copywriting.rewritten_text))
        else:
            logger.warning("No extracted audio; skipping ASR + rewrite.")

        logger.info("[Step 3/6] Video Generation")
        logger.debug("开始提交视频生成任务。")
        result.video_generate = await self.video_generator.generate(
            prompt=video_prompt,
            first_frame_image=first_frame_image,
            duration=11,
        )
        logger.debug("视频生成完成，输出：%s", result.video_generate.video_path)

        logger.info("[Step 4/6] Speech Synthesis")
        tts_text = (
            result.copywriting.rewritten_text
            if result.copywriting
            else video_prompt
        )
        logger.debug("开始TTS合成，文本长度：%d", len(tts_text))
        result.tts = await self.tts_synthesizer.synthesize(clone_audio_path, tts_text)
        logger.debug("语音合成完成：%s", result.tts.audio_path)

        logger.info("[Step 5/6] Lip Sync Alignment")
        lip_sync_output = os.path.join(self.output_dir, "final_video.mp4")
        try:
            logger.debug("开始唇形对齐，目标输出：%s", lip_sync_output)
            result.lip_sync = await self.lip_sync_aligner.align(
                video_path=result.video_generate.video_path,
                audio_path=result.tts.audio_path,
                output_path=lip_sync_output,
            )
            logger.debug("唇形对齐完成：%s", result.lip_sync.output_video_path)
        except NotImplementedError:
            logger.warning("LipSyncAligner not implemented; skipping.")

        logger.info("[Step 6/6] Social Publishing")
        if publish_platform:
            logger.debug("开始发布到平台：%s", publish_platform.value)
            final_video = (
                result.lip_sync.output_video_path
                if result.lip_sync
                else result.video_generate.video_path
            )
            try:
                result.publish = await self.social_publisher.publish(
                    video_path=final_video,
                    title=publish_title,
                    description=publish_description,
                    platform=publish_platform,
                )
                logger.debug("视频发布完成。")
            except NotImplementedError:
                logger.warning("SocialPublisher not implemented; skipping.")
        else:
            logger.debug("未指定发布平台，跳过发布。")

        logger.info("Pipeline complete.")
        return result


async def main():
    pipeline = TalkingHeadPipeline()
    result = await pipeline.run(
        sharelink="1.20 VlP:/ v@s.Eh 01/07 这五堂课，教你及时止损# 情感共鸣 # 人生感悟 # 爱你老已  https://v.douyin.com/3KPZkT9zlVc/ 复制此链接，打开Dou音搜索，直接观看视频！",
        video_prompt="一位年轻男销售面对镜头微笑地说话，配合着自然的手势动作，背景是简洁的办公室环境。",
        clone_audio_path="output/speaker.wav",
        first_frame_image='output/first_frame.png',
        publish_platform=None,
    )
    logger.info("Pipeline result:\n%s", _to_yaml_like(asdict(result)))

if __name__ == "__main__":
    asyncio.run(main())
