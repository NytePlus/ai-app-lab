"""Talking-Head Video Generation Pipeline

Pipeline stages:
  1. AudioExtractor     – extract audio from source video  (stub)
  2. CopywritingRewriter – ASR transcription + LLM rewrite
  3. VideoGenerator      – generate video via Seedance
  4. TTSSynthesizer      – synthesize speech via TTS
  5. LipSyncAligner      – lip-sync alignment              (stub)
  6. SocialPublisher     – publish to social platforms      (stub)
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import config
from audio_extractor import AudioExtractor, AudioExtractResult
from copywriting_rewriter import CopywritingRewriter, CopywritingResult
from video_generator import VideoGenerator, VideoGenerateResult
from tts_synthesizer import TTSSynthesizer, TTSResult
from lip_sync_aligner import LipSyncAligner, LipSyncResult
from social_publisher import SocialPublisher, Platform, PublishResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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
        self.audio_extractor = AudioExtractor()
        self.copywriting_rewriter = CopywritingRewriter()
        self.video_generator = VideoGenerator()
        self.tts_synthesizer = TTSSynthesizer()
        self.lip_sync_aligner = LipSyncAligner()
        self.social_publisher = SocialPublisher()

        os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    async def run(
        self,
        source_video_url: str,
        video_prompt: str,
        first_frame_image: Optional[str] = None,
        publish_platform: Optional[Platform] = None,
        publish_title: str = "",
        publish_description: str = "",
    ) -> PipelineResult:
        result = PipelineResult()

        # ── Step 1: Extract audio ───────────────────────────────────
        logger.info("Step 1/6 – Extracting audio from source video…")
        audio_output_path = os.path.join(config.OUTPUT_DIR, "source_audio.wav")
        try:
            result.audio_extract = await self.audio_extractor.extract(
                video_url=source_video_url,
                output_path=audio_output_path,
            )
        except NotImplementedError:
            logger.warning(
                "AudioExtractor not implemented; skipping. "
                "Provide audio_chunks directly to Step 2 in production."
            )

        # ── Step 2: ASR + LLM rewrite ──────────────────────────────
        logger.info("Step 2/6 – Transcribing & rewriting copywriting…")
        if result.audio_extract:
            async def _file_chunks(path: str, chunk_size: int = 3200):
                with open(path, "rb") as f:
                    while chunk := f.read(chunk_size):
                        yield chunk

            result.copywriting = await self.copywriting_rewriter.run(
                _file_chunks(result.audio_extract.audio_path)
            )
        else:
            logger.warning("No extracted audio; skipping ASR + rewrite.")

        # ── Step 3: Generate video via Seedance ─────────────────────
        logger.info("Step 3/6 – Generating video via Seedance…")
        result.video_generate = await self.video_generator.generate(
            prompt=video_prompt,
            first_frame_image=first_frame_image,
        )

        # ── Step 4: TTS synthesis ───────────────────────────────────
        logger.info("Step 4/6 – Synthesizing speech via TTS…")
        tts_text = (
            result.copywriting.rewritten_text
            if result.copywriting
            else video_prompt
        )
        result.tts = await self.tts_synthesizer.synthesize(tts_text)

        tts_audio_path = os.path.join(config.OUTPUT_DIR, "tts_audio.pcm")
        with open(tts_audio_path, "wb") as f:
            f.write(result.tts.audio_data)
        logger.info("TTS audio saved to %s", tts_audio_path)

        # ── Step 5: Lip-sync alignment ──────────────────────────────
        logger.info("Step 5/6 – Aligning lip-sync…")
        lip_sync_output = os.path.join(config.OUTPUT_DIR, "final_video.mp4")
        try:
            result.lip_sync = await self.lip_sync_aligner.align(
                video_path=result.video_generate.video_url,
                audio_path=tts_audio_path,
                output_path=lip_sync_output,
            )
        except NotImplementedError:
            logger.warning("LipSyncAligner not implemented; skipping.")

        # ── Step 6: Publish ─────────────────────────────────────────
        if publish_platform:
            logger.info("Step 6/6 – Publishing to %s…", publish_platform.value)
            final_video = (
                result.lip_sync.output_video_path
                if result.lip_sync
                else result.video_generate.video_url
            )
            try:
                result.publish = await self.social_publisher.publish(
                    video_path=final_video,
                    title=publish_title,
                    description=publish_description,
                    platform=publish_platform,
                )
            except NotImplementedError:
                logger.warning("SocialPublisher not implemented; skipping.")
        else:
            logger.info("Step 6/6 – No publish platform specified; skipping.")

        logger.info("Pipeline complete.")
        return result


async def main():
    pipeline = TalkingHeadPipeline()
    result = await pipeline.run(
        source_video_url="https://example.com/source_video.mp4",
        video_prompt="一位年轻女性面对镜头微笑播报新闻",
        first_frame_image=None,
        publish_platform=None,
    )
    logger.info("Pipeline result: %s", result)


if __name__ == "__main__":
    asyncio.run(main())
