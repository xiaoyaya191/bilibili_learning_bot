#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

VERSION="3.1.5"
REPO_URL="${BILILEARN_REPO_URL:-https://github.com/xiaoyaya191/bilibili_learning_bot.git}"
INSTALL_DIR="${BILILEARN_INSTALL_DIR:-$PWD}"
if [ ! -f "$INSTALL_DIR/web_panel.py" ]; then INSTALL_DIR="${HOME}/bililearn"; fi
TEST_MODE="${BILILEARN_TEST_MODE:-0}"

say() { printf '\n[星嘢酱] %s\n' "$*"; }
warn() { printf '[星嘢酱] 喵呜，%s\n' "$*" >&2; }
die() { printf '\n[星嘢酱] 安装暂停：%s\n' "$*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "找不到命令 $1，请先安装 Termux 基础包。"; }
run_pkg() { [ "$TEST_MODE" = 1 ] && return 0; pkg "$@"; }
run_pip() {
  if python -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
    python -m pip install --break-system-packages "$@"
  else
    python -m pip install "$@"
  fi
}

case "$(uname -o 2>/dev/null || true)" in
  Android*) : ;;
  *) [ "$TEST_MODE" = 1 ] || die "这个脚本只在 Termux 里运行；Ubuntu/Linux 请使用 start.sh。" ;;
esac
need_cmd python
need_cmd git
need_cmd pkg

if [ "$TEST_MODE" != 1 ]; then
  say "主人，先更新 Termux 软件源，再准备编译工具喵~"
  run_pkg update -y
  run_pkg upgrade -y
  run_pkg install -y python git ffmpeg libjpeg-turbo libyaml clang make binutils
fi

if [ ! -f "$INSTALL_DIR/web_panel.py" ]; then
  say "发现当前目录没有项目，人家会把源码放到 $INSTALL_DIR。"
  if [ -e "$INSTALL_DIR" ]; then die "目标目录已存在但不是 BiliLearn 项目：$INSTALL_DIR"; fi
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" || die "源码下载失败，请检查网络或设置 BILILEARN_REPO_URL。"
fi
cd "$INSTALL_DIR"
[ -f requirements.txt ] || die "项目目录缺少 requirements.txt。"

say "正在准备 Python 依赖，主人可以放心摸摸头~"
if [ "$TEST_MODE" != 1 ]; then
  run_pip install --upgrade pip setuptools wheel
  run_pip install PyYAML --no-build-isolation || warn "PyYAML 预安装失败，继续尝试完整依赖。"
  run_pip install -r requirements.txt || die "Python 依赖安装失败；请把上方完整日志发给人家。"
fi

cat > start_termux.sh <<'LAUNCHER'
#!/data/data/com.termux/files/usr/bin/bash
set -e
cd "$(dirname "$0")"
export BILI_DISCLAIMER_SKIP=1 BILI_WEB_AUTO_OPEN=0 BILI_TRAY_DISABLED=1 WEB_HOST=127.0.0.1
echo "[BiliLearn] 网页面板：http://127.0.0.1:18083"
exec python web_panel.py
LAUNCHER
chmod +x start_termux.sh

say "安装完成啦，主人！运行下面这句启动网页面板："
printf '  cd %q && ./start_termux.sh\n' "$INSTALL_DIR"
printf '  %s\n' "猫猫提示：手机浏览器打开 http://127.0.0.1:18083"
