#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  bilibili_learning_bot - ARM64 安装/运行脚本
#  用法:
#    bash arm/install_arm.sh              # 创建 .venv 并安装依赖
#    bash arm/install_arm.sh web          # 安装后启动 Web 面板
#    bash arm/install_arm.sh bot          # 安装后启动机器人菜单
#    bash arm/install_arm.sh pack         # 安装后把 .venv + wheelhouse 打包
# ============================================================
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MIRROR="${PYPI_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
MODE="${1:-install}"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
WHEELHOUSE="$ROOT/arm/wheelhouse"

# ---------- 0. 日志 ----------
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/arm-install-$(date +%Y%m%d_%H%M%S).log"
if [ -z "$BILILEARN_TEE_DONE" ]; then
  export BILILEARN_TEE_DONE=1
  echo "日志文件: $LOG_FILE"
  exec bash "$0" "$@" 2>&1 | tee -a "$LOG_FILE"
fi

echo "========================================"
echo " bilibili_learning_bot ARM64 安装"
echo " ROOT: $ROOT"
echo " VENV: $VENV"
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
if [ "$TERMUX_OFFLINE" = "1" ]; then
  echo "[1/5] 离线模式：跳过 pkg/apt，改用本地 .deb（install_offline.sh）"
elif [ -n "$PREFIX" ] && command -v pkg >/dev/null 2>&1; then
  echo "[1/5] Termux 系统依赖..."
  pkg install -y python python-pip ffmpeg libyaml clang make
elif command -v apt-get >/dev/null 2>&1; then
  echo "[1/5] Debian/Ubuntu 系统依赖..."
  apt-get update -y
  apt-get install -y python3 python3-pip python3-venv ffmpeg libyaml-dev build-essential
else
  echo "[1/5] 未检测到 pkg/apt，跳过系统依赖安装"
  echo "       请手动安装 python3、pip、ffmpeg、libyaml"
fi

# ---------- 3. 创建虚拟环境 ----------
if [ ! -x "$PY" ]; then
  echo "[2/5] 创建虚拟环境 .venv ..."
  if python -m venv "$VENV"; then
    :
  else
    echo "      python -m venv 失败，改用 virtualenv..."
    if [ -d "$WHEELHOUSE" ] && [ -n "$(ls -A "$WHEELHOUSE")" ]; then
      python -m pip install --upgrade --no-index --find-links "$WHEELHOUSE" virtualenv
    else
      python -m pip install --upgrade virtualenv -i "$MIRROR"
    fi
    python -m virtualenv "$VENV"
  fi
else
  echo "[2/5] 虚拟环境已存在，跳过创建"
fi

echo "      补齐 setuptools/wheel/packaging（不降级 pip）..."
if [ -d "$WHEELHOUSE" ] && [ -n "$(ls -A "$WHEELHOUSE")" ]; then
  "$PY" -m pip install --upgrade --no-index --find-links "$WHEELHOUSE" setuptools wheel packaging
else
  "$PY" -m pip install --upgrade setuptools wheel packaging -i "$MIRROR"
fi

# ---------- 4. 项目依赖 ----------
if [ -d "$WHEELHOUSE" ] && [ -n "$(ls -A "$WHEELHOUSE")" ]; then
  echo "[3/5] 使用仓库内置 ARM64 轮子离线安装..."
  "$PY" "$ROOT/arm/install_offline_deps.py"
else
  echo "[3/5] 未找到内置 wheelhouse，使用清华源在线安装..."
  "$PY" -m pip install --no-build-isolation -r "$ROOT/arm/requirements-arm64.txt" -i "$MIRROR"
fi

# ---------- 5. 启动 / 打包 ----------
case "$MODE" in
  web)
    echo "[4/5] 依赖安装完成"
    cd "$ROOT"
    exec "$PY" web_panel.py
    ;;
  bot)
    echo "[4/5] 依赖安装完成"
    cd "$ROOT"
    exec "$PY" main.py
    ;;
  pack)
    echo "[4/5] 依赖安装完成"
    STAMP="$(date +%Y%m%d_%H%M%S)"
    OUT="$ROOT/arm/bilibili_learning_bot_arm64_${STAMP}.tar.gz"
    echo "[5/5] 打包 .venv + wheelhouse -> $OUT ..."
    tar -czf "$OUT" \
      --exclude='.venv/lib/python*/site-packages/**/__pycache__' \
      --exclude='.venv/lib/python*/site-packages/**/*.pyc' \
      -C "$ROOT" .venv arm/wheelhouse
    SIZE="$(du -h "$OUT" | cut -f1)"
    echo "      打包完成: $OUT ($SIZE)"
    echo "      还原: tar -xzf $(basename "$OUT") -C $(dirname "$ROOT")"
    ;;
  *)
    echo "[4/5] 依赖安装完成"
    echo ""
    echo "启动方式:"
    echo "  bash arm/install_arm.sh web   # Web 面板 http://localhost:18083"
    echo "  bash arm/install_arm.sh bot   # 机器人交互菜单"
    echo "  bash arm/install_arm.sh pack  # 打包 .venv + wheelhouse"
    echo ""
    ;;
esac
