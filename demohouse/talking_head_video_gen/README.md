# Talking Head Video Generation

一个面向短视频生产的自动化流水线：输入抖音分享链接，输出可直接发布的口播视频。

当前后端已支持从原视频抽取信息、生成新文案与语音，并完成视频生成与唇形驱动；发布端保留为可扩展接口。

## Pipeline 六步骤

| # | Step | Class | 状态 |
|---|------|-------|------|
| 1 | Audio Extraction | `DouyinAudioExtractor` | ✅ 已实现（抓取视频并提取 WAV 音频） |
| 2 | Copywriting Rewrite | `CopywritingRewriter` | ✅ 已实现（ASR + `client.responses.create`） |
| 3 | Video Generation | `VideoGenerator` | ✅ 已实现（Seedance 异步任务） |
| 4 | Speech Synthesis | `CosyvoiceTTSSynthesizer` | ✅ 已实现（音色复刻 + TTS） |
| 5 | Lip Sync Alignment | `Wav2LipSyncAligner` / `MuseTalkSyncAligner` | ✅ 已实现（sync.so / MuseTalk） |
| 6 | Social Publishing | `SocialPublisher` | ⏳ 预留接口 |

## 核心目录

```text
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

`CopywritingRewriter` 处理逻辑：
1. `ASRClient` 转写源音频得到原文；
2. `AsyncOpenAI.responses.create` 按系统提示词进行改写；
3. 优先读取 `response.output_text`，缺失时回退解析 `response.output`。

## 环境变量

必填（按你当前流程）：

| 变量 | 说明 |
|------|------|
| `ASR_APP_KEY` / `ASR_ACCESS_KEY` | ASR 凭证 |
| `LLM_API_KEY` / `LLM_API_BASE` / `LLM_MODEL` | 文案改写模型配置 |
| `VIDEO_API_KEY` / `VIDEO_API_BASE` / `VIDEO_MODEL` | 视频生成模型配置 |
| `DASHSCOPE_API_KEY` | TTS 鉴权（CosyVoice） |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | 本地文件上传 OSS（用于 ASR / LipSync 输入链接） |

可选：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OUTPUT_DIR` | `output` | 输出目录 |
| `POLL_INTERVAL_SECONDS` | `10` | 视频任务轮询间隔 |
| `CLONE_AUDIO_PATH` | `output/speaker_audio.wav` | TTS 参考音频 |
| `SYNC_API_KEY` | - | 使用 `Wav2LipSyncAligner` 时需要 |
| `FFMPEG_EXECUTABLE` | `ffmpeg` | 音频 20 秒裁剪可执行路径 |

## 快速运行

```bash
cd backend
# 设置环境变量后
python main.py
```

# 🐞 网络爬虫排查复盘文档：从 DNS 劫持到 IPv6 冲突

**项目背景**：使用 Python + Playwright 提取抖音 (`douyin.com`) 视频媒体流。
**核心痛点**：底层网络请求反复报错，常规代码层面的修复无效。
**环境特征**：本地 Windows 系统、开启/关闭科学上网软件（海外节点）。

---

## 阶段一：有代理阶段 (科学上网开启)

在此阶段，电脑开启了代理软件（如 TUN 虚拟网卡模式），网络出口 IP 位于海外（新加坡）。

### 🚩 异常 1：`ENOTFOUND www.douyin.com`
* **现象描述**：Playwright 在使用 `context.request.get()` 请求媒体流时，直接抛出域名找不到的错误，但外部浏览器（如 Firefox）可以正常访问。
* **根本原因**：
  * Playwright 的 `request` 接口底层调用的是 Node.js 的 C++ 网络库（libuv），它非常“死板”，无法像现代浏览器那样完美兼容代理软件的虚拟网卡机制。
  * Node.js 发出的 DNS 查询包被代理软件错误路由或拦截，导致 DNS 解析彻底失败。
* **解决策略**：
  * **方案 A（绕过 Node.js）**：放弃 Playwright 发请求，改用 Python 原生的 `httpx` 或 `aiohttp`，并开启 `trust_env=True` 适应系统代理。
  * **方案 B（强行注入）**：在 Playwright 创建 context 时，强行写死代理地址，避开本地 DNS 解析：`proxy={"server": "http://127.0.0.1:7890"}`。

### 🚩 异常 2：`Client network socket disconnected before secure TLS connection was established`
* **现象描述**：成功解决 `ENOTFOUND` 并拿到 CDN 真实视频地址（如 `v26.douyinvod.com`）后，在下载瞬间连接被强行切断。
* **根本原因**：
  1. **CDN 防盗链**：请求头中缺少来源标识。
  2. **Geo-blocking (地域封锁)**：这是最致命的一环。抖音国内 CDN 检测到发起 TLS 握手的 IP 属于**海外（新加坡）**。为了防止跨境盗刷，服务器在握手阶段直接重置了 TCP 连接（RST），不返回任何 HTTP 错误码。
* **解决策略**：
  * 代码层：强制补充 `Referer: https://www.douyin.com/` 和真实的 `User-Agent`，并开启 `ignore_https_errors=True`。
  * 网络层：**必须将代理节点切换至中国大陆**，或完全关闭代理使用国内直连。

---

## 阶段二：关闭代理阶段 (国内直连)

为了解决 CDN 的地域封锁，关闭了代理软件，试图使用国内物理网络直接下载。

### 🚩 异常 3：`ERR_NAME_NOT_RESOLVED`
* **现象描述**：关闭代理后，Playwright 连主站都打不开了，报错域名无法解析。在系统终端执行 `ping v.douyin.com` 提示“找不到主机”。
* **初步排查**：
  * 检查代码：去除了强行注入的 `proxy={"server": "127.0.0.1:7890"}` 参数。
  * 清除缓存：执行了 `ipconfig /flushdns`，但毫无作用。

### 🚩 终极异常：IPv6 黑洞导致全局 DNS 失明
* **深度诊断**：
  * 在终端执行 `nslookup v.douyin.com`，发现系统并没有向常规的 IPv4 DNS（如 223.5.5.5 或路由器 IP）发起查询，而是向一个 **IPv6 地址 (`2001:da8...`)** 发起了请求，并连续返回 `timeout`（超时）。
* **根本原因**：
  * **Windows 优先级机制**：Windows 系统默认情况下，IPv6 的优先级高于 IPv4。
  * **代理软件后遗症/运营商问题**：关闭代理软件后，网络协议栈出现了异常，或者运营商下发的 IPv6 DNS 本身处于宕机状态。系统死死卡在 IPv6 的超时等待中，拒绝切换到畅通的 IPv4 通道，导致系统级“网络失明”。
* **最终解决策略 (物理超度)**：
  1. 打开 `ncpa.cpl`（网络连接属性）。
  2. 找到当前网卡，**取消勾选 [Internet 协议版本 6 (TCP/IPv6)]**。
  3. 执行 `ipconfig /flushdns` 刷新缓存。
  4. 验证：`nslookup` 秒回正确的 IPv4 地址，代码畅通无阻，视频成功下载。

---

## 📝 核心经验总结 (Takeaways)

1. **分离抓取与下载**：Playwright (基于浏览器内核) 非常适合用来绕过 JS 逆向提取 `play_url`，但它内置的 `request.get` 极易受代理环境干扰。**获取到直链后，交由带有防盗链头的 Python `httpx` 进行流式下载**，是业界最稳妥的架构。
2. **警惕海外节点**：国内互联网大厂的视频和图片 CDN 普遍存在极其严格的 IP 地域限制，表现通常为莫名其妙的 SSL/TLS 握手失败。
3. **遇到玄学断网，先斩 IPv6**：在日常开发、Docker 部署或爬虫调试中，如果物理网络畅通但疯狂报错 DNS 找不到，**关闭 IPv6 是成功率最高、成本最低的抢救手段**。