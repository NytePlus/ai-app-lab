"""Step 1: Extract audio track from a video URL.

This is a stub – the actual implementation depends on the chosen web tool /
ffmpeg service. Only the interface is defined here.
"""

import asyncio
import json
import logging
import os
import re
import time
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

@dataclass
class AudioExtractResult:
    audio_path: str
    sample_rate: int = 16000
    format: str = "wav"


class BaseAudioExtractor(ABC):
    """Extract the audio track from a source video."""

    @abstractmethod
    async def extract(self, video_url: str, output_path: str) -> AudioExtractResult:
        pass


class DouyinAudioExtractor:
    """基于 Playwright 自动登录和下载的抖音音频/视频提取器"""

    def __init__(
            self,
            state_path: str = "output/douyin_state.json",
            temp_path: str = "output/temp.mp4",
            ffmpeg_executable: str = "demohouse/talking_head_video_gen/backend/ffmpeg/ffmpeg-master-latest-win64-gpl-shared/bin/ffmpeg.exe"
    ):
        self.state_path = state_path
        self.temp_path = temp_path
        self.ffmpeg_executable = ffmpeg_executable

    async def login(self):
        if os.path.exists(self.state_path):
            logger.debug("检测到登录状态文件，跳过扫码登录：%s", self.state_path)
            return
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

            page.set_default_timeout(0)
            await page.goto("https://www.douyin.com/", wait_until="domcontentloaded")

            logger.debug("等待扫码登录中（系统将自动检测登录状态）。")

            logged_in = False
            max_retries = 120
            for i in range(max_retries):
                try:
                    current_cookies = await context.cookies()
                    if any(c['name'] == 'login_time' for c in current_cookies):
                        logger.debug("检测到登录标志，登录成功。")
                        logged_in = True
                        break

                    print("正在等待扫码... (%ss)", i, end="\r", flush=True)
                    await asyncio.sleep(1)
                except Exception:
                    await asyncio.sleep(1)
                    continue

            if not logged_in:
                await browser.close()
                raise TimeoutError("登录超时，请重试。")

            # ==========================================
            # 核心新增：保存 Playwright 原生状态
            # ==========================================
            await context.storage_state(path=self.state_path)
            logger.debug("浏览器状态(含 LocalStorage)已保存：%s", self.state_path)

            await browser.close()

    async def extract(self, sharelink: str, output_path: str):
        import os

        def extract_url_from_sharelink(sharelink: str) -> str:
            pattern = r"https://v\.douyin\.com/[a-zA-Z0-9]+/"
            match = re.search(pattern, sharelink)

            if match:
                video_url = match.group(0)
                return video_url
            logger.warning("无法从分享链接中提取视频URL，请检查链接格式。")
            return None
        video_url = extract_url_from_sharelink(sharelink)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)  # 调试时用 False，稳定后改 True

            # ==========================================
            # 核心修改：判断状态文件是否存在，存在则加载
            # ==========================================
            if os.path.exists(self.state_path):
                logger.debug("加载登录状态文件：%s", self.state_path)
                context = await browser.new_context(storage_state=self.state_path)
            else:
                logger.debug("未找到状态文件，将以未登录状态访问（可能触发验证码）。")
                context = await browser.new_context()

            page = await context.new_page()
            real_play_url = None

            async def handle_response(response):
                nonlocal real_play_url
                if "aweme/v1/web/aweme/detail/" in response.url and response.status == 200:
                    try:
                        json_data = await response.json()
                        aweme_detail = json_data.get("aweme_detail", {})
                        play_addr = aweme_detail.get("video", {}).get("play_addr", {})
                        url_list = play_addr.get("url_list", [])

                        for url in url_list:
                            if "https://www.douyin.com/aweme/v1/play" in url:
                                real_play_url = url
                                logger.debug("成功拦截到视频真实地址。")
                                break
                    except Exception as e:
                        pass  # 忽略解析错误

            page.on("response", handle_response)

            logger.debug("正在访问页面：%s", video_url)
            await page.goto(video_url, wait_until="domcontentloaded")

            # 等待网络请求被拦截
            for _ in range(100):
                if real_play_url:
                    break
                await asyncio.sleep(1)

            if not real_play_url:
                logger.warning("未能抓取到视频地址。")
                await browser.close()
                return

            # 执行下载逻辑
            response = await context.request.get(real_play_url)
            body = await response.body()
            with open(self.temp_path, "wb") as f:
                f.write(body)
            logger.debug("视频下载成功：%s", self.temp_path)

            try:
                ffmpeg_cmd = [
                    self.ffmpeg_executable,
                    "-i", self.temp_path,
                    "-loglevel", "error",
                    "-vn",
                    "-acodec", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    "-y",
                    output_path
                ]

                # 执行命令，捕获输出以防报错
                process = subprocess.run(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                if process.returncode != 0:
                    logger.error("FFmpeg 转换失败：%s", process.stderr)
                    raise Exception("音频提取失败")

                logger.debug("音频提取并转换成功：%s", output_path)

            finally:
                # 无论成功还是失败，务必清理临时文件释放磁盘空间
                if os.path.exists(self.temp_path):
                    os.remove(self.temp_path)

        await browser.close()

        # 4. 返回符合约定的结果对象
        return AudioExtractResult(
            audio_path=output_path,
            sample_rate=16000,
            format="wav"
        )