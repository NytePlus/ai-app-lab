"""Step 2: Transcribe audio via ASR, then rewrite the transcript with an LLM.

ASR approach is taken from ``https://www.volcengine.com/docs/6561/1354868?lang=zh`` (ASRClient).
LLM rewrite uses the OpenAI-compatible ``responses.create`` API.
"""

import logging
import os
from dataclasses import dataclass

from asr_client import ASRClient
from openai import AsyncOpenAI


logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = """\
你是一位专业的视频文案改写专家。用户会给你一段从原始视频中提取的文案（可能含有口语化表达、\
语气词、重复、错别字等），请你：
1. 修正语音识别可能产生的错误；
2. 保持原文核心语义不变，但看不出来是原文
3. 换一种表述方式，有新意，适合用在视频文案里；
4. 输出仅包含改写后的文案，不要输出任何解释。
"""


@dataclass
class CopywritingResult:
    original_text: str
    rewritten_text: str


class CopywritingRewriter:
    """ASR transcription followed by LLM-powered rewrite."""

    def __init__(
        self,
        asr_app_key: str = "",
        asr_access_key: str = "",
        llm_endpoint_id: str = "",
        obs_key_id: str = "",
        obs_key_secret: str = "",
        llm_api_key: str = "",
        llm_base_url: str = "",
        model: str = "",
    ):
        self.asr_app_key = asr_app_key or os.getenv("ASR_APP_KEY", "")
        self.asr_access_key = asr_access_key or os.getenv("ASR_ACCESS_KEY", "")
        self.llm_endpoint_id = llm_endpoint_id or os.getenv("LLM_ENDPOINT_ID", "")
        self.model = model or os.getenv("LLM_MODEL", "doubao-seed-1-6-251015")
        self.obs_key_id = obs_key_id or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
        self.obs_key_secret = obs_key_secret or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
        self.llm_api_key = llm_api_key or os.getenv("LLM_API_KEY", "")
        self.llm_base_url = (llm_base_url or os.getenv("LLM_API_BASE", "")).rstrip("/")
        self._asr_client = None
        self._llm_client = AsyncOpenAI(
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
        )

    async def _init_asr(self) -> None:
        self._asr_client = ASRClient(
            app_key=self.asr_app_key,
            access_key=self.asr_access_key,
            obs_key_id=self.obs_key_id,
            obs_key_secret=self.obs_key_secret,
        )

    async def transcribe(self, audio_url: str) -> str:
        """Run ASR on a stream of raw audio chunks and return full text."""
        if self._asr_client is None:
            await self._init_asr()

        result = await self._asr_client.asr(
            audio_url,
            audio_format="wav",
        )
        logger.debug("ASR转写完成，文本长度：%d", len(result["text"]))
        return result["text"]

    @staticmethod
    def _extract_output_text(response) -> str:
        text = (getattr(response, "output_text", "") or "").strip()
        if text:
            return text

        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                part = getattr(content, "text", "") or ""
                if part:
                    parts.append(part)
        return "".join(parts).strip()

    async def rewrite(self, transcript: str) -> str:
        """Ask the LLM to clean up and rewrite the transcript."""
        logger.debug("开始请求LLM改写，输入长度：%d", len(transcript))
        response = await self._llm_client.responses.create(
            model=self.model,
            instructions=REWRITE_SYSTEM_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": transcript}],
                }
            ],
            extra_body={"thinking": {"type": "disabled"}},
        )

        rewritten = self._extract_output_text(response)
        logger.debug("LLM改写完成，输出长度：%d", len(rewritten))
        return rewritten

    async def run(self, audio_url: str) -> CopywritingResult:
        """Full step: ASR ➜ LLM rewrite."""
        original = await self.transcribe(audio_url)
        rewritten = await self.rewrite(original)
        return CopywritingResult(original_text=original, rewritten_text=rewritten)
