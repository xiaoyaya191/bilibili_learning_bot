#!/data/data/com.termux/files/usr/bin/bash
# ============================================
#  bilibili_learning_bot 启动脚本 (Termux)
# ============================================

set -e

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── 工作目录 ──
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}   bilibili_learning_bot v3.0.0${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# ── 检查 Python ──
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[ERROR] 未找到 python3，请先安装: pkg install python${NC}"
    exit 1
fi

PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}[OK]${NC} Python: $PY_VER"

# ── 检查/安装依赖 ──
check_and_install() {
    local pkg=$1
    local import_name=$2
    if ! python3 -c "import $import_name" 2>/dev/null; then
        echo -e "${YELLOW}[INSTALL] 安装 $pkg ...${NC}"
        pip3 install "$pkg" --quiet
    fi
}

echo -e "${CYAN}[CHECK] 检查依赖...${NC}"
check_and_install "flask" "flask"
check_and_install "flask-cors" "flask_cors"
check_and_install "openai" "openai"
check_and_install "httpx" "httpx"
check_and_install "qrcode" "qrcode"
check_and_install "Pillow" "PIL"
check_and_install "colorama" "colorama"
check_and_install "bilibili-api" "bilibili_api"
echo -e "${GREEN}[OK] 依赖检查完成${NC}"
echo ""

# ── 菜单 ──
echo -e "${YELLOW}请选择启动模式:${NC}"
echo "  1) 机器人菜单 (main.py - 交互式)"
echo "  2) Web 管理面板 (web_panel.py - 端口7860)"
echo "  3) 后台运行 Web 面板"
echo "  4) 安装/更新全部依赖"
echo "  0) 退出"
echo ""
read -r -p "输入选项 [1-4]: " choice

case "$choice" in
    1)
        echo -e "${GREEN}启动机器人菜单...${NC}"
        exec python3 main.py
        ;;
    2)
        echo -e "${GREEN}启动 Web 管理面板 (http://localhost:7860)${NC}"
        exec python3 web_panel.py
        ;;
    3)
        LOGFILE="$SCRIPT_DIR/bot_web.log"
        echo -e "${GREEN}后台启动 Web 面板，日志: $LOGFILE${NC}"
        nohup python3 web_panel.py > "$LOGFILE" 2>&1 &
        PID=$!
        echo "PID: $PID"
        echo "$PID" > "$SCRIPT_DIR/bot.pid"
        echo -e "${GREEN}[OK] 已后台启动，访问 http://localhost:7860${NC}"
        echo -e "${YELLOW}停止命令: kill \$(cat bot.pid)${NC}"
        ;;
    4)
        echo -e "${CYAN}安装全部依赖...${NC}"
        pip3 install -r requirements.txt
        echo -e "${GREEN}[OK] 依赖安装完成${NC}"
        ;;
    0)
        echo "退出"
        exit 0
        ;;
    *)
        echo -e "${RED}无效选项${NC}"
        exit 1
        ;;
esac
