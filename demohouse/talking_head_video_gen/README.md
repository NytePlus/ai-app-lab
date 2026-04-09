# Talking Head Video Generation

从一段源视频出发，自动完成 **音频提取 → 文案转写改写 → 视频生成 → 语音合成 → 唇形对齐 → 社交发布** 全流程。

## Pipeline 六步骤

| # | 步骤 | 类 | 状态 |
|---|------|----|------|
| 1 | 音频提取（web tool / ffmpeg） | `AudioExtractor` | 接口已定义，待实现 |
| 2 | 文案提取 + 改写（ASR + LLM） | `CopywritingRewriter` | ✅ 已实现 |
| 3 | 视频生成（Seedance） | `VideoGenerator` | ✅ 已实现 |
| 4 | 语音合成（TTS） | `TTSSynthesizer` | ✅ 已实现 |
| 5 | 语音唇形对齐（Wav2Lip） | `LipSyncAligner` | 接口已定义，待实现 |
| 6 | 社交平台发布 | `SocialPublisher` | 接口已定义，待实现 |

## 目录结构

```
backend/
├── config.py               # 环境变量 / 配置常量
├── main.py                 # Pipeline 编排入口
├── audio_extractor.py      # Step 1 — 音频提取 (stub)
├── copywriting_rewriter.py # Step 2 — ASR 转写 + LLM 改写
├── video_generator.py      # Step 3 — Seedance 视频生成
├── tts_synthesizer.py      # Step 4 — TTS 语音合成
├── lip_sync_aligner.py     # Step 5 — 唇形对齐 (stub)
├── social_publisher.py     # Step 6 — 社交平台发布 (stub)
└── requirements.txt
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `ASR_APP_KEY` / `ASR_ACCESS_KEY` | 火山语音识别凭证 |
| `TTS_APP_KEY` / `TTS_ACCESS_KEY` | 火山语音合成凭证 |
| `TTS_SPEAKER` | TTS 发音人（默认 `zh_female_sajiaonvyou_moon_bigtts`） |
| `LLM_ENDPOINT_ID` | 火山方舟 LLM endpoint |
| `VIDEO_API_KEY` | Seedance 视频生成 API Key |
| `VIDEO_API_BASE` | Seedance API 地址 |
| `VIDEO_MODEL` | 视频模型名称 |

## 快速运行

```bash
cd backend
pip install -r requirements.txt
# 设置环境变量后
python main.py
```
