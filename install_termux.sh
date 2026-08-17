#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  bilibili_learning_bot v3.1.3 - Termux (Android) 安装脚本
# ============================================================
#  用法: bash install_termux.sh     （在已拉取/解压的项目目录内运行）
#  功能: 自动安装系统依赖 + Python 依赖，解决 PyYAML 编译问题，
#        并生成 start_termux.sh 启动脚本。
#  全新设备快速部署: 推荐直接运行  bash deploy_termux.sh
#        （该脚本会从 GitHub 拉取源码并完成全部配置）
# ============================================================

set -e

fail() { echo ""; echo "❌ 错误: $*" >&2; exit 1; }

echo ""
echo "========================================"
echo " bilibili_learning_bot v3.1.3 安装脚本"
echo " 环境: Termux (Android)"
echo "========================================"
echo ""

# 确认当前目录为项目根目录（应包含 main.py / web_panel.py）
if [ ! -f "main.py" ] || [ ! -f "web_panel.py" ]; then
  fail "未在项目根目录运行。请先 cd 到项目目录（应包含 main.py 与 web_panel.py）。"
fi

# ---------- 可选存储权限 ----------
if [ ! -d "$HOME/storage" ]; then
  echo "[提示] 如需读写手机存储（/sdcard），请先运行: termux-setup-storage"
  echo "       允许存储权限后重新运行本脚本即可。此步为可选。"
fi

# ---------- 多语言同意（与 CLI / deploy_termux.sh 一致）----------
echo ""
echo "本项目会按配置操作你的 Bilibili 账号，仅供学习与个人使用。"
echo "使用即视为同意免责声明。"
printf "输入 我同意 / I agree / согласен 以继续: "
read -r consent
case "$consent" in
  我同意|"i agree"|"I agree"|IAGREE|согласен|Согласен|yes|y|Y|ok|OK|是) ;;
  *) fail "未通过同意确认。安装已取消。" ;;
esac

# ---------- Step 1: 更新 Termux 包管理器 ----------
echo ""
echo "[1/4] 更新 Termux 包列表..."
pkg update -y
pkg upgrade -y

# ---------- Step 2: 安装系统依赖 ----------
echo ""
echo "[2/4] 安装系统编译依赖 (libyaml 解决 PyYAML 编译问题)..."
pkg install -y python coreutils libyaml clang make binutils

# ---------- Step 3: 升级 pip ----------
echo ""
echo "[3/4] 升级 pip..."
pip install --upgrade pip setuptools wheel

# ---------- Step 4: 安装 Python 依赖 ----------
echo ""
echo "[4/4] 安装 Python 项目依赖..."

# 先单独安装 PyYAML (使用系统 libyaml，避免编译失败)
echo "  -> 安装 PyYAML (使用系统 libyaml)..."
if ! pip install PyYAML --no-build-isolation; then
  echo "  [警告] PyYAML 安装失败。若后续导入报错，请重新运行: pkg install libyaml"
fi

# 安装其余依赖（可选桌面/系统模块失败不阻塞网页面板）
echo "  -> 安装项目依赖..."
pip install -r requirements.txt || echo "  [警告] 部分可选依赖在 Termux 上跳过，不影响网页面板与基本流程。"

# ---------- 生成启动脚本 ----------
echo ""
echo "  -> 生成 start_termux.sh 启动脚本..."
cat > start_termux.sh <<'LAUNCHER'
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
chmod +x start_termux.sh

echo ""
echo "========================================"
echo " ✅ 安装完成!"
echo "========================================"
echo ""
echo "启动网页面板: bash start_termux.sh"
echo "（或命令行模式: python main.py）"
echo ""
