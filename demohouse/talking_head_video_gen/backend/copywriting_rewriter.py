"""Step 2: Transcribe audio via ASR, then rewrite the transcript with an LLM.

ASR approach is taken from ``live_voice_call`` (arkitect AsyncASRClient).
LLM approach is taken from ``ad_video_gen`` / ``live_voice_call``
(arkitect BaseChatLanguageModel).
"""

import logging
from dataclasses import dataclass, field
from typing import AsyncIterable, List

from arkitect.core.component.asr import AsyncASRClient
from arkitect.core.component.llm import BaseChatLanguageModel
from arkitect.types.llm.model import ArkMessage
from langchain.prompts.chat import BaseChatPromptTemplate
from langchain_core.messages import BaseMessage, SystemMessage

import config

logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = """\
你是一位专业的视频文案改写专家。用户会给你一段从原始视频中提取的文案（可能含有口语化表达、\
语气词、重复、错别字等），请你：
1. 修正语音识别可能产生的错误；
2. 保持原文核心语义不变；
3. 改写为更流畅、更适合口播的短视频文案；
4. 输出仅包含改写后的文案，不要输出任何解释。
"""


class RewritePrompt(BaseChatPromptTemplate):
    input_variables: List[str] = ["messages"]

    def format_messages(self, **kwargs) -> List[BaseMessage]:
        messages: list = kwargs.pop("messages")
        return [SystemMessage(content=REWRITE_SYSTEM_PROMPT)] + messages


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
    ):
        self.asr_app_key = asr_app_key or config.ASR_APP_KEY
        self.asr_access_key = asr_access_key or config.ASR_ACCESS_KEY
        self.llm_endpoint_id = llm_endpoint_id or config.LLM_ENDPOINT_ID
        self._asr_client: AsyncASRClient | None = None

    async def _init_asr(self) -> None:
        self._asr_client = AsyncASRClient(
            app_key=self.asr_app_key,
            access_key=self.asr_access_key,
        )
        await self._asr_client.init()

    async def transcribe(self, audio_chunks: AsyncIterable[bytes]) -> str:
        """Run ASR on a stream of raw audio chunks and return full text."""
        if self._asr_client is None:
            await self._init_asr()

        buffer = ""
        async for response in self._asr_client.stream_asr(audio_chunks):
            if response.result and response.result.text:
                buffer = response.result.text

        await self._asr_client.close()
        logger.info("ASR transcription complete: %s", buffer[:120])
        return buffer

    async def rewrite(self, transcript: str) -> str:
        """Ask the LLM to clean up and rewrite the transcript."""
        messages = [ArkMessage(role="user", content=transcript)]
        llm = BaseChatLanguageModel(
            template=RewritePrompt(),
            messages=messages,
            endpoint_id=self.llm_endpoint_id,
        )

        result_parts: list[str] = []
        async for chunk in llm.astream():
            if chunk.choices and chunk.choices[0].delta:
                result_parts.append(chunk.choices[0].delta.content)

        rewritten = "".join(result_parts)
        logger.info("LLM rewrite complete: %s", rewritten[:120])
        return rewritten

    async def run(self, audio_chunks: AsyncIterable[bytes]) -> CopywritingResult:
        """Full step: ASR ➜ LLM rewrite."""
        original = await self.transcribe(audio_chunks)
        rewritten = await self.rewrite(original)
        return CopywritingResult(original_text=original, rewritten_text=rewritten)
