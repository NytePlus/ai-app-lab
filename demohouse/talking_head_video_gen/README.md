# Talking Head Video Generation

从一段源视频出发，自动完成 **音频提取 → 文案转写改写 → 视频生成 → 语音合成 → 唇形对齐 → 社交发布** 全流程。

## Pipeline 六步骤

| # | 步骤 | 类 | 状态 |
|---|------|----|------|
| 1 | 音频提取（web tool / ffmpeg） | `AudioExtractor` | 接口已定义，待实现 |
| 2 | 文案提取 + 改写（ASR + LLM） | `CopywritingRewriter` | ✅ 已实现（`client.responses.create`） |
| 3 | 视频生成（Seedance） | `VideoGenerator` | ✅ 已实现 |
| 4 | 语音合成（TTS） | `TTSSynthesizer` | ✅ 已实现 |
| 5 | 语音唇形对齐（Wav2Lip） | `LipSyncAligner` | 接口已定义，待实现 |
| 6 | 社交平台发布 | `SocialPublisher` | 接口已定义，待实现 |

## 目录结构

```
backend/
├── main.py                 # Pipeline 编排入口
├── audio_extractor.py      # Step 1 - 音频提取 (stub)
├── copywriting_rewriter.py # Step 2 - ASR 转写 + LLM 改写（responses.create）
├── video_generator.py      # Step 3 - Seedance 视频生成
├── tts_synthesizer.py      # Step 4 - TTS 语音合成
├── lip_sync_aligner.py     # Step 5 - 唇形对齐 (stub)
├── social_publisher.py     # Step 6 - 社交平台发布 (stub)
└── requirements.txt
```

## Step 2（文案改写）说明

`CopywritingRewriter` 当前流程：
1. 用 `ASRClient` 获取转写文本；
2. 用 OpenAI-compatible `AsyncOpenAI` 客户端调用 `client.responses.create`；
3. 通过 `instructions` 注入改写规则，`input` 传入原始转写；
4. 输出优先读取 `response.output_text`，空时自动从 `response.output` 做兜底拼接。

## 环境变量

| 变量 | 说明 |
|------|------|
| `ASR_APP_KEY` / `ASR_ACCESS_KEY` | 火山语音识别凭证 |
| `TTS_APP_KEY` / `TTS_ACCESS_KEY` | 火山语音合成凭证 |
| `TTS_SPEAKER` | TTS 发音人（默认 `zh_female_sajiaonvyou_moon_bigtts`） |
| `LLM_API_KEY` | 文案改写 API Key |
| `LLM_API_BASE` | 文案改写 API Base（如 `https://ark.cn-beijing.volces.com/api/v3`） |
| `LLM_ENDPOINT_ID` | 文案改写 endpoint id（可选） |
| `LLM_MODEL` | 文案改写模型（responses API 的 `model`） |
| `VIDEO_API_KEY` / `VIDEO_API_BASE` | Seedance 视频生成接口凭证与地址 |
| `VIDEO_MODEL` | 视频生成模型 |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | 音频上传（OBS/OSS）凭证 |
| `POLL_INTERVAL_SECONDS` | Step 3 任务轮询间隔秒数（默认 `10`） |
| `OUTPUT_DIR` | 流程输出目录（默认 `output`） |
| `CLONE_AUDIO_PATH` | 复刻音色参考音频路径（默认 `output/speaker_audio.wav`） |

> 当前后端模块直接读取环境变量，不再依赖 `backend/config.py`。

## 快速运行

```bash
cd backend
pip install -r requirements.txt
# 设置环境变量后
python main.py
```
