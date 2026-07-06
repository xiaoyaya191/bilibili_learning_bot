FROM python:3.11-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 依赖优先使用 Python wheels，避免构建阶段依赖 apt；如需系统 ffmpeg，可在宿主机或派生镜像中安装。

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.11-slim

ARG APP_VERSION=3.0.1
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:${PATH}" \
    BOT_MODE=web \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=7860 \
    NO_PROXY=127.0.0.1,localhost \
    no_proxy=127.0.0.1,localhost \
    APP_VERSION=${APP_VERSION} \
    TZ=Asia/Shanghai \
    BILI_DISCLAIMER_SKIP=1

# python:slim 已包含 ca-certificates；项目依赖 imageio-ffmpeg，可避免系统 apt 源/代理问题。

COPY --from=builder /install /usr/local
COPY . .

RUN mkdir -p Data KnowledgeBase highlights html_exports model qr_codes \
    && chmod -R 755 Data KnowledgeBase highlights html_exports model qr_codes

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/version' % os.getenv('WEB_PORT', '7860'), timeout=5)" || exit 1

CMD if [ "$BOT_MODE" = "cli" ]; then \
        python main.py; \
    elif [ "$BOT_MODE" = "standby" ]; then \
        python -c "from brain.standby import standby_loop; import asyncio; asyncio.run(standby_loop())"; \
    else \
        python web_panel.py; \
    fi
