# B站 AI 管理系统
FROM python:3.11-slim

LABEL description="B站 AI Learning Bot - Web Panel"

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 复制代码
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 创建数据目录
RUN mkdir -p /app/Data

# web_panel.py 默认端口 8080
EXPOSE 8080

# 默认命令：启动 web_panel
CMD ["python", "web_panel.py"]
