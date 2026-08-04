#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  bilibili_learning_bot - Termux 全离线安装
#  前置：已在 arm/termux-debs/ 放好 .deb 闭包，
#        已在 arm/wheelhouse/ 放好 ARM64 Python 轮子。
#  用法:
#    bash arm/install_offline.sh          # 离线安装依赖
#    bash arm/install_offline.sh web      # 离线安装并启动 Web 面板
#    bash arm/install_offline.sh bot      # 离线安装并启动机器人
# ============================================================
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEBS="$ROOT/arm/termux-debs"
ORDER="$DEBS/termux-debs-order.txt"
MODE="${1:-install}"

if [ -z "$PREFIX" ] || ! command -v dpkg >/dev/null 2>&1; then

# ---------- 0. 日志 ----------
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/offline-install-$(date +%Y%m%d_%H%M%S).log"
if [ -z "$BILILEARN_TEE_DONE" ]; then
  export BILILEARN_TEE_DONE=1
  echo "日志文件: $LOG_FILE"
  exec bash "$0" "$@" 2>&1 | tee -a "$LOG_FILE"
fi
  echo "[ERROR] 只能在 Termux 内运行（需要 \$PREFIX 和 dpkg）"
  exit 1
fi

if [ ! -f "$ORDER" ] || [ ! -d "$DEBS" ]; then
  echo "[ERROR] 缺少本地 .deb 闭包：$DEBS"
  echo "        请先在电脑上运行 python arm/build_termux_offline.py"
  exit 1
fi

echo "========================================"
echo " Termux 全离线安装"
echo " DEBS: $DEBS"
echo " MODE: $MODE"
echo "========================================"

echo "[1/3] 安装本地 Termux .deb（依赖顺序安装）..."
SKIP_COUNT=0
INSTALL_COUNT=0
while IFS= read -r deb; do
  [ -z "$deb" ] && continue
  deb="${deb//$'\r'/}"  # 防止 Windows CRLF 残留
  pkg="$(dpkg-deb -f "$DEBS/$deb" Package 2>/dev/null || true)"
  ver="$(dpkg-deb -f "$DEBS/$deb" Version 2>/dev/null || true)"
  installed="$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || true)"
  if [ -n "$installed" ] && dpkg --compare-versions "$installed" ge "$ver" 2>/dev/null; then
    echo "  skip $deb（已安装 $installed >= $ver）"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi
  echo "  $deb 需要从 $ver 升级，先从清华源安装依赖..."
  deps="$(dpkg-deb -f "$DEBS/$deb" Depends 2>/dev/null | tr ',' '\n' | sed -E 's/\([^)]*\)//g; s/\|[^,]*//g; s/[[:space:]]+//g' | grep -E '^[A-Za-z0-9+.-]+$' | sort -u | tr '\n' ' ')"
  if [ -n "$deps" ]; then
    if [ -n "$PREFIX" ] && command -v pkg >/dev/null 2>&1; then
      pkg install -y $deps
    elif command -v apt-get >/dev/null 2>&1; then
      apt-get install -y $deps
    fi
  fi
  echo "  dpkg -i $deb"
  dpkg -i --force-overwrite "$DEBS/$deb"
  INSTALL_COUNT=$((INSTALL_COUNT + 1))
done < "$ORDER"
echo "      安装 $INSTALL_COUNT 个，跳过 $SKIP_COUNT 个已存在包"

echo "[2/3] 创建 .venv 并离线安装 Python 轮子..."
TERMUX_OFFLINE=1 bash "$ROOT/arm/install_arm.sh"

echo "[3/3] 离线安装完成"
case "$MODE" in
  web)
    cd "$ROOT"
    exec .venv/bin/python web_panel.py
    ;;
  bot)
    cd "$ROOT"
    exec .venv/bin/python main.py
    ;;
  *)
    echo ""
    echo "启动方式:"
    echo "  bash arm/install_offline.sh web   # Web 面板 http://localhost:18083"
    echo "  bash arm/install_offline.sh bot   # 机器人交互菜单"
    echo ""
    ;;
esac
