"""FastAPI endpoints for step-by-step talking-head pipeline execution."""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, TypeVar
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from audio_extractor import DouyinAudioExtractor
from copywriting_rewriter import CopywritingRewriter
from lip_sync_aligner import Wav2LipSyncAligner
from social_publisher import Platform, SocialPublisher
from tts_synthesizer import CosyvoiceTTSSynthesizer
from video_generator import VideoGenerator


OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output")).expanduser().resolve()
UPLOAD_DIR = OUTPUT_DIR / "uploads"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="Talking Head Pipeline API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/api/artifacts", StaticFiles(directory=str(OUTPUT_DIR)), name="artifacts")


class SessionState(BaseModel):
    session_id: str
    sharelink: str = ""
    source_audio_path: str = ""
    source_audio_url: str = ""
    original_text: str = ""
    rewritten_text: str = ""
    first_frame_path: str = ""
    first_frame_url: str = ""
    speaker_audio_path: str = ""
    speaker_audio_url: str = ""
    generated_video_path: str = ""
    generated_video_url: str = ""
    tts_audio_path: str = ""
    tts_audio_url: str = ""
    final_video_path: str = ""
    final_video_url: str = ""
    selected_platforms: List[str] = Field(default_factory=list)
    notice: str = ""


class SessionCreateResponse(BaseModel):
    session_id: str


class Step1Request(BaseModel):
    session_id: str
    sharelink: str


class Step2TranscribeRewriteRequest(BaseModel):
    session_id: str
    audio_path: str = ""


class Step2RewriteRequest(BaseModel):
    session_id: str
    transcript: str


class Step3GenerateRequest(BaseModel):
    session_id: str
    prompt: str = ""
    first_frame_path: str = ""
    duration: int = 11
    force: bool = False


class Step4TTSRequest(BaseModel):
    session_id: str
    text: str = ""
    clone_audio_path: str = ""
    force: bool = False


class Step5AlignRequest(BaseModel):
    session_id: str
    video_path: str = ""
    audio_path: str = ""


class Step6PublishRequest(BaseModel):
    session_id: str
    platforms: List[str] = Field(default_factory=list)
    title: str = ""
    description: str = ""


_sessions: Dict[str, SessionState] = {}
_audio_extractor = DouyinAudioExtractor()
_copywriting_rewriter = CopywritingRewriter()
_video_generator = VideoGenerator()
_lip_sync_aligner = Wav2LipSyncAligner()
_social_publisher = SocialPublisher()
_tts_synthesizer: Optional[CosyvoiceTTSSynthesizer] = None
_T = TypeVar("_T")


def _get_tts_synthesizer() -> CosyvoiceTTSSynthesizer:
    global _tts_synthesizer
    if _tts_synthesizer is None:
        _tts_synthesizer = CosyvoiceTTSSynthesizer()
    return _tts_synthesizer


async def _run_with_windows_proactor(coro: Any) -> Any:
    """Run coroutine in a dedicated Proactor loop on Windows.

    Playwright requires subprocess support, which is unavailable on Windows
    SelectorEventLoop (common with dev reload setups).
    """
    if os.name != "nt":
        return await coro

    def _runner() -> Any:
        loop = asyncio.ProactorEventLoop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    return await asyncio.to_thread(_runner)


def _artifact_url(path: str) -> str:
    if not path:
        return ""
    abs_path = Path(path).expanduser().resolve()
    try:
        rel = abs_path.relative_to(OUTPUT_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Artifact path must be inside OUTPUT_DIR: {abs_path}") from exc
    return f"/api/artifacts/{rel.as_posix()}"


def _get_session(session_id: str) -> SessionState:
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
    return session


@app.post("/api/session", response_model=SessionCreateResponse)
async def create_session() -> SessionCreateResponse:
    session_id = uuid4().hex
    _sessions[session_id] = SessionState(session_id=session_id)
    return SessionCreateResponse(session_id=session_id)


@app.get("/api/session/{session_id}", response_model=SessionState)
async def get_session(session_id: str) -> SessionState:
    return _get_session(session_id)


@app.post("/api/upload/{session_id}")
async def upload_asset(
    session_id: str,
    kind: str = Form(...),
    file: UploadFile = File(...),
) -> Dict[str, str]:
    session = _get_session(session_id)
    if kind not in {"first_frame", "speaker_audio"}:
        raise HTTPException(status_code=400, detail="kind must be one of: first_frame, speaker_audio")

    suffix = Path(file.filename or "").suffix or ".bin"
    save_path = UPLOAD_DIR / f"{session_id}_{kind}{suffix}"
    with save_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    url = _artifact_url(str(save_path))
    if kind == "first_frame":
        session.first_frame_path = str(save_path)
        session.first_frame_url = url
    else:
        session.speaker_audio_path = str(save_path)
        session.speaker_audio_url = url

    return {"path": str(save_path), "url": url}


@app.post("/api/step1/extract", response_model=SessionState)
async def step1_extract(req: Step1Request) -> SessionState:
    session = _get_session(req.session_id)
    session.sharelink = req.sharelink

    out_path = OUTPUT_DIR / f"{session.session_id}_source_audio.wav"
    try:
        await _run_with_windows_proactor(_audio_extractor.login())
        result = await _run_with_windows_proactor(
            _audio_extractor.extract(sharelink=req.sharelink, output_path=str(out_path))
        )
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Playwright subprocess is not available in current event loop on Windows. "
                "Please run server without incompatible reload loop settings."
            ),
        ) from exc

    session.source_audio_path = str(Path(result.audio_path).expanduser().resolve())
    session.source_audio_url = _artifact_url(session.source_audio_path)
    return session


@app.post("/api/step2/transcribe-rewrite", response_model=SessionState)
async def step2_transcribe_rewrite(req: Step2TranscribeRewriteRequest) -> SessionState:
    session = _get_session(req.session_id)
    audio_path = req.audio_path or session.source_audio_path
    if not audio_path:
        raise HTTPException(status_code=400, detail="Missing audio_path. Run step1 first or provide audio_path.")

    original = await _copywriting_rewriter.transcribe(audio_path)
    rewritten = await _copywriting_rewriter.rewrite(original)
    session.original_text = original
    session.rewritten_text = rewritten
    return session


@app.post("/api/step2/rewrite", response_model=SessionState)
async def step2_rewrite(req: Step2RewriteRequest) -> SessionState:
    session = _get_session(req.session_id)
    session.original_text = req.transcript
    session.rewritten_text = await _copywriting_rewriter.rewrite(req.transcript)
    return session


@app.post("/api/step3/generate", response_model=SessionState)
async def step3_generate(req: Step3GenerateRequest) -> SessionState:
    session = _get_session(req.session_id)
    session.notice = ""
    prompt = req.prompt or session.rewritten_text or session.original_text
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing prompt. Please provide prompt or complete step2 first.")

    first_frame_path = req.first_frame_path or session.first_frame_path
    if not first_frame_path:
        session.notice = "未上传正面图片，请先上传正面图片后重试。"
        return session
    if req.force and Path(_video_generator.video_path).exists():
        Path(_video_generator.video_path).unlink(missing_ok=True)

    result = await _video_generator.generate(
        prompt=prompt,
        first_frame_image=first_frame_path or None,
        duration=req.duration,
    )
    session.generated_video_path = str(Path(result.video_path).expanduser().resolve())
    session.generated_video_url = _artifact_url(session.generated_video_path)
    return session


@app.post("/api/step4/tts", response_model=SessionState)
async def step4_tts(req: Step4TTSRequest) -> SessionState:
    session = _get_session(req.session_id)
    session.notice = ""
    text = req.text or session.rewritten_text or session.original_text
    if not text:
        raise HTTPException(status_code=400, detail="Missing text. Please provide text or complete step2 first.")

    clone_audio_path = req.clone_audio_path or session.speaker_audio_path
    if not clone_audio_path:
        session.notice = "未上传录音文件，请先上传录音后重试。"
        return session

    if req.force:
        tts_path = OUTPUT_DIR / "tts_audio.wav"
        tts_path.unlink(missing_ok=True)

    synth = _get_tts_synthesizer()
    try:
        result = await synth.synthesize(clone_audio_path=clone_audio_path, text=text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TTS 生成失败: {exc}") from exc
    if not result.audio_path:
        raise HTTPException(status_code=500, detail="TTS returned empty audio_path")

    session.tts_audio_path = str(Path(result.audio_path).expanduser().resolve())
    session.tts_audio_url = _artifact_url(session.tts_audio_path)
    return session


@app.post("/api/step5/align", response_model=SessionState)
async def step5_align(req: Step5AlignRequest) -> SessionState:
    session = _get_session(req.session_id)
    video_path = req.video_path or session.generated_video_path
    audio_path = req.audio_path or session.tts_audio_path
    if not video_path or not audio_path:
        raise HTTPException(status_code=400, detail="Missing video/audio. Complete step3 and step4 first.")

    out_path = OUTPUT_DIR / f"{session.session_id}_final_video.mp4"
    result = await _lip_sync_aligner.align(video_path=video_path, audio_path=audio_path, output_path=str(out_path))

    session.final_video_path = str(Path(result.output_video_path).expanduser().resolve())
    session.final_video_url = _artifact_url(session.final_video_path)
    return session


@app.post("/api/step6/publish")
async def step6_publish(req: Step6PublishRequest) -> Dict[str, Any]:
    session = _get_session(req.session_id)
    video_path = session.final_video_path or session.generated_video_path
    if not video_path:
        raise HTTPException(status_code=400, detail="Missing final video. Complete step5 first.")

    results: List[Dict[str, Any]] = []
    session.selected_platforms = req.platforms
    for platform_name in req.platforms:
        try:
            platform = Platform(platform_name)
            publish_result = await _social_publisher.publish(
                video_path=video_path,
                title=req.title,
                description=req.description,
                platform=platform,
            )
            results.append(
                {
                    "platform": platform_name,
                    "success": publish_result.success,
                    "url": publish_result.url,
                    "video_id": publish_result.video_id,
                    "error_message": publish_result.error_message,
                }
            )
        except NotImplementedError as exc:
            results.append({"platform": platform_name, "success": False, "error_message": str(exc)})
        except ValueError:
            results.append({"platform": platform_name, "success": False, "error_message": "Unknown platform"})

    return {"session_id": session.session_id, "results": results}

