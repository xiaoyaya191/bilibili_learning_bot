#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  bilibili_learning_bot - ARM64 安装/运行脚本
#  用法:
#    bash arm/install_arm.sh          # 只安装依赖
#    bash arm/install_arm.sh web      # 安装后启动 Web 面板
#    bash arm/install_arm.sh bot      # 安装后启动机器人菜单
# ============================================================
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MIRROR="${PYPI_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
MODE="${1:-install}"

echo "========================================"
echo " bilibili_learning_bot ARM64 安装"
echo " ROOT: $ROOT"
echo " MODE: $MODE"
echo "========================================"

# ---------- 1. 检测架构 ----------
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) ;;
  *)
    echo "[WARN] 当前架构是 $ARCH，本脚本为 aarch64/arm64 准备"
    echo "       如果只是测试，请确保依赖有对应架构的 wheel"
    ;;
esac

# ---------- 2. 系统依赖 ----------
if [ -n "$PREFIX" ] && command -v pkg >/dev/null 2>&1; then
  echo "[1/4] Termux 系统依赖..."
  pkg install -y python python-pip ffmpeg libyaml clang make
elif command -v apt-get >/dev/null 2>&1; then
  echo "[1/4] Debian/Ubuntu 系统依赖..."
  apt-get update -y
  apt-get install -y python3 python3-pip ffmpeg libyaml-dev build-essential
else
  echo "[1/4] 未检测到 pkg/apt，跳过系统依赖安装"
  echo "       请手动安装 python3、pip、ffmpeg、libyaml"
fi

# ---------- 3. pip 基础 ----------
echo "[2/4] 升级 pip/setuptools/wheel..."
python -m pip install --upgrade pip setuptools wheel

# ---------- 4. 项目依赖 ----------
WHEELHOUSE="$ROOT/arm/wheelhouse"
if [ -d "$WHEELHOUSE" ] && [ -n "$(ls -A "$WHEELHOUSE")" ]; then
  echo "[3/4] 使用仓库内置 ARM64 轮子离线安装..."
  python -m pip install --no-index --find-links "$WHEELHOUSE" \
    -r "$ROOT/arm/requirements-arm64-resolved.txt"
else
  echo "[3/4] 未找到内置 wheelhouse，使用清华源在线安装..."
  python -m pip install -r "$ROOT/arm/requirements-arm64.txt" -i "$MIRROR"
fi

# ---------- 5. 启动 ----------
echo "[4/4] 依赖安装完成"
case "$MODE" in
  web)
    cd "$ROOT"
    exec python web_panel.py
    ;;
  bot)
    cd "$ROOT"
    exec python main.py
    ;;
  *)
    echo ""
    echo "启动方式:"
    echo "  bash arm/install_arm.sh web   # Web 面板 http://localhost:18083"
    echo "  bash arm/install_arm.sh bot   # 机器人交互菜单"
    echo ""
    ;;
esac
