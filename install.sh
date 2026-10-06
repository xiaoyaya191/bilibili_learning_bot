#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

VERSION="3.1.6"
REPO_URL="${BILILEARN_REPO_URL:-https://github.com/xiaoyaya191/bilibili_learning_bot.git}"
INSTALL_DIR="${BILILEARN_INSTALL_DIR:-${HOME}/bililearn}"
BRANCH="${BILILEARN_BRANCH:-main}"
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

printf '环境检查通过。现在部署 BiliLearn %s 吗？[y/N] ' "$VERSION"
read -r deploy_answer
case "$deploy_answer" in
  y|Y) ;;
  *) say "已取消部署，没有修改任何文件。"; exit 0 ;;
esac

cat <<'NOTICE'

本项目会在你主动启用相应功能后操作 B 站账号、生成内容或发送互动。
你需要自行遵守平台规则，并承担使用本项目产生的全部后果。
NOTICE
printf '确认理解并继续，请准确输入：我同意\n> '
read -r consent_answer
[ "$consent_answer" = "我同意" ] || die "未输入准确的“我同意”，安装没有开始。"

if [ "$TEST_MODE" != 1 ]; then
  say "主人，先更新 Termux 软件源，再准备编译工具喵~"
  run_pkg update -y
  run_pkg upgrade -y
  run_pkg install -y python git ffmpeg libjpeg-turbo libyaml clang make binutils
fi

say "正在从 GitHub 获取 BiliLearn $VERSION 源码。"
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" fetch origin "$BRANCH" || die "源码更新失败，请检查网络和分支名。"
  git -C "$INSTALL_DIR" checkout "$BRANCH" || die "无法切换到分支 $BRANCH。"
  git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" || die "本地源码有分叉或修改，未覆盖任何文件；请先备份后手动处理。"
elif [ -e "$INSTALL_DIR" ]; then
  die "目标目录已存在但不是 Git 仓库：$INSTALL_DIR。为避免覆盖数据，请设置新的 BILILEARN_INSTALL_DIR。"
else
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" || die "源码下载失败，请检查网络、仓库地址或分支名。"
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
echo "[BiliLearn] 正在启动 3.1.6 网页面板，实际地址见下方启动信息。"
exec python web_panel.py
LAUNCHER
chmod +x start_termux.sh

say "安装完成啦，主人！运行下面这句启动网页面板："
printf '  cd %q && ./start_termux.sh\n' "$INSTALL_DIR"
printf '  %s\n' "默认地址：http://127.0.0.1:18083；若端口被占用，以启动信息显示的地址为准。"
