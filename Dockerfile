FROM python:3.11-slim AS builder

WORKDIR /app

# 安装编译依赖（仅构建阶段需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ============================================================
# 运行阶段
# ============================================================
FROM python:3.11-slim

WORKDIR /app

# 安装运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制已安装的 pip 包
COPY --from=builder /root/.local /root/.local
ENV PATH="/root/.local/bin:${PATH}"

# 复制项目文件（.dockerignore 会排除 Data/、KnowledgeBase/ 等）
COPY . .

# 创建运行时目录并设置权限
RUN mkdir -p Data KnowledgeBase highlights html_exports model && \
    chmod -R 755 Data KnowledgeBase highlights html_exports model

# 暴露 Web 控制台端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/')" || exit 1

# 支持通过 BOT_MODE 切换启动模式：
#   web    — Web 管理面板（默认）
#   cli    — CLI 交互式菜单
#   standby — 待机模式（后台监听）
ENV BOT_MODE=web

CMD if [ "$BOT_MODE" = "cli" ]; then \
        python main.py; \
    elif [ "$BOT_MODE" = "standby" ]; then \
        python -c "from brain.standby import standby_loop; import asyncio; asyncio.run(standby_loop())"; \
    else \
        python web_panel.py; \
    fi
