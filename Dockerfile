FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（ffmpeg 用于视频抽帧）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 暴露 Web 控制台端口
EXPOSE 8080

# 启动 Web 控制台
CMD ["python", "web_panel.py"]
