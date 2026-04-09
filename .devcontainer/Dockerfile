FROM python:3.12-slim-bullseye

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# System deps:
# - ffmpeg: used by moviepy[ffmpeg]
# - playwright deps: headless browser runtime libraries
# - git/curl: commonly needed for dev workflows
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
# 2. 证书就位后，再将源替换为国内源（这里换回你最初用的阿里云，它对纯 HTTP 的兼容性更好）
    && (sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true) \
    && (sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list 2>/dev/null || true) \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        ffmpeg \
        # Playwright runtime deps
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libpango-1.0-0 \
        libcairo2 \
        libatspi2.0-0 \
        libgtk-3-0 \
        libwayland-client0 \
        libwayland-cursor0 \
        libwayland-egl1 \
        libx11-xcb1 \
        libxshmfence1 \
        libxext6 \
        libxrender1 \
        libxi6 \
        libxtst6 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 1. 设置 Playwright 的全局浏览器下载路径
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# 2. 只需要安装 uv 即可 (放弃全局安装 playwright)
RUN python -m pip install --upgrade pip \
    && python -m pip install uv

WORKDIR /build

# 3. 优先复制依赖文件，利用 Docker 缓存
COPY uv.lock .
COPY pyproject.toml .
COPY README.md .
COPY arkitect/ arkitect/

# 4. 同步依赖 (会自动在 /build/.venv 创建虚拟环境，其中包含项目所需的 playwright)
# 4. 同步依赖并安装项目
RUN uv sync

# 5. 将虚拟环境的 bin 目录加入系统 PATH
ENV PATH="/build/.venv/bin:$PATH"

# 6. 直接调用虚拟环境中的 playwright 安装浏览器
RUN playwright install chromium

# 7. 最后切换到你的工作代码目录
WORKDIR /workspaces
