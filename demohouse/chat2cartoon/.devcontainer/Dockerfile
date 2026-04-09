FROM python:3.11-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
# 2. 证书就位后，再将源替换为国内源（这里换回你最初用的阿里云，它对纯 HTTP 的兼容性更好）
    && (sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true) \
    && (sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list 2>/dev/null || true) \
# 3. 使用国内源极速更新并安装全部编译依赖
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        gnupg \
        gcc \
        g++ \
        python3-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Poetry (backend uses poetry run)
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir poetry==1.6.1