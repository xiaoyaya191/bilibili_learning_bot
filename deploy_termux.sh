#!/data/data/com.termux/files/usr/bin/bash
# BiliLearn Termux installer. Run with: bash deploy_termux.sh
set -eu

say() { printf '\n[BiliLearn] %s\n' "$*"; }
fail() { printf '\n[BiliLearn] ERROR: %s\n' "$*" >&2; exit 1; }

# The deployment artifact is a bootstrapper. It never assumes the sender's
# Windows checkout exists on the Android device.
REPO_URL="${BILILEARN_REPO_URL:-https://github.com/xiaoyaya191/bilibili_learning_bot.git}"
INSTALL_DIR="${BILILEARN_INSTALL_DIR:-$HOME/bililearn}"
BRANCH="${BILILEARN_BRANCH:-main}"

case "$(uname -o 2>/dev/null || true)" in
  Android*) ;;
  *) fail "This installer is for Termux on Android. Use start.sh on Linux/macOS." ;;
esac

say "Step 1/6: checking Termux environment"
command -v pkg >/dev/null 2>&1 || fail "Termux pkg was not found. Install the official Termux app first."
if ! command -v python >/dev/null 2>&1; then
  say "Python is missing and will be installed during deployment."
fi
# 存储权限：让项目能访问 /sdcard（导出备份、下载产物可选）。
if [ ! -d "$HOME/storage" ]; then
  say "提示：若需要读写手机存储（/sdcard），请先运行一次："
  say "    termux-setup-storage"
  say "然后允许存储权限。跳过此步不会影响核心功能。"
fi

printf 'Environment check passed. Deploy BiliLearn now? [y/N] '
read -r deploy
case "$deploy" in y|Y|yes|YES) ;; *) say "Deployment cancelled. Nothing was changed."; exit 0;; esac

cat <<'NOTICE'

This project operates a Bilibili account and may send messages or comments when
you enable those features. It is for learning and personal use. You are
responsible for account actions and platform rules.
NOTICE

# 多语言同意：兼容 中文 / English / Русский，任意匹配即可继续。
printf 'Type 我同意 / I agree / согласен to continue: '
read -r consent
case "$consent" in
  我同意|i agree|I agree|IAGREE|согласен|Согласен|yes|y|Y|ok|OK|是) ;;
  *) fail "Consent did not match. Installation was not started." ;;
esac

say "Step 2/6: installing required Termux packages"
pkg update -y
pkg upgrade -y
# libyaml 解决 PyYAML 编译问题；clang/make/binutils 供部分原生扩展编译。
pkg install -y python git ffmpeg libjpeg-turbo libyaml libyaml-dev clang make binutils

say "Step 3/6: pulling source from GitHub"
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" fetch origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
elif [ -e "$INSTALL_DIR" ]; then
  fail "Install directory exists but is not a Git checkout: $INSTALL_DIR"
else
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi
ROOT="$INSTALL_DIR"
cd "$ROOT"

say "Step 4/6: preparing Python environment"
python -m pip install --upgrade pip wheel setuptools
# 先单独装 PyYAML（使用系统 libyaml，避免编译失败），其余依赖失败不阻塞核心功能。
python -m pip install PyYAML --no-build-isolation || say "PyYAML 安装跳过，若后续导入报错请运行：pkg install libyaml"
python -m pip install -r requirements.txt || say "部分可选依赖在 Termux 上跳过，不影响网页面板与基本流程。"

say "Step 5/6: writing the launcher"
cat > "$INSTALL_DIR/start_termux.sh" <<'LAUNCHER'
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
export BILI_DISCLAIMER_SKIP=1
export BILI_WEB_AUTO_OPEN=0
export BILI_TRAY_DISABLED=1
export WEB_HOST=127.0.0.1
echo "[BiliLearn] 正在启动网页面板..."
echo "[BiliLearn] 在手机浏览器打开: http://127.0.0.1:$(python -c "import utils.web_launcher as w; print(w.get_web_port())" 2>/dev/null || echo 18083)"
echo "[BiliLearn] Termux 中输入 Ctrl+C 停止。"
python web_panel.py
LAUNCHER
chmod +x "$INSTALL_DIR/start_termux.sh"

say "Step 6/6: starting the local web panel"
export BILI_DISCLAIMER_SKIP=1
export BILI_WEB_AUTO_OPEN=0
export BILI_TRAY_DISABLED=1
export WEB_HOST=127.0.0.1
python web_panel.py