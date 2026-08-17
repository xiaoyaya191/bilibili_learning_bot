#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  BiliLearn v3.1.3 — 手机端(Termux) 一键安装脚本（单文件）
# ============================================================
#  用法（手机 Termux 中运行）:
#    bash install.sh
#
#  流程:
#    1. 询问是否安装
#    2. 选择安装路径（回车默认 ~/bililearn）
#    3. 显示与网页端同款的免责声明，输入「我同意」后才能继续
#    4. 自动测速 GitHub 镜像并拉取源码（直连兜底）
#    5. 安装依赖并生成启动脚本
#    6. 注册全局命令: bililearn / abiligent / bilibili_learning_bot
#       （装完在 Termux 输入任一命令即可直接启动网页端）
#  ============================================================

set -Eeuo pipefail

REPO_URL="${BILILEARN_REPO_URL:-https://github.com/xiaoyaya191/bilibili_learning_bot.git}"
BRANCH="${BILILEARN_BRANCH:-main}"
DEFAULT_DIR="$HOME/bililearn"
INSTALL_DIR=""

# GitHub 加速镜像（逐个测速，全部失败回退直连）
MIRRORS=(
  "https://ghfast.top"
  "https://ghproxy.cn"
  "https://gh-proxy.com"
  "https://ghproxy.net"
  "https://cf.ghproxy.cc"
)

c_g="\033[32m"; c_r="\033[31m"; c_y="\033[33m"; c_b="\033[36m"; c_0="\033[0m"
say()   { printf "\n${c_b}[BiliLearn]${c_0} %s\n" "$*"; }
ok()    { printf "${c_g}[✓]${c_0} %s\n" "$*"; }
warn()  { printf "${c_y}[!]${c_0} %s\n" "$*"; }
fail()  { printf "\n${c_r}[✗] 错误: %s${c_0}\n" "$*" >&2; exit 1; }

run_with_timeout() {
  if command -v timeout >/dev/null 2>&1; then
    timeout "$@"
  else
    "$@"
  fi
}

check_python_imports() {
  local missing=""
  local module
  for module in flask flask_cors httpx qrcode PIL colorama bilibili_api requests psutil; do
    if ! python -c "import ${module}" >/dev/null 2>&1; then
      missing="${missing} ${module}"
    fi
  done
  if [ -n "$missing" ]; then
    fail "核心 Python 依赖缺失:${missing}。请查看上方 pip 错误后重试。"
  fi
}

printf "\n"
echo   "=============================================="
echo   "        BiliLearn v3.1.3 · 手机端安装器"
echo   "      (bilibili_learning_bot · Termux)"
echo   "=============================================="
echo   ""
echo   " 本脚本将完成以下步骤:"
echo   "   ① 确认安装        ② 选择安装路径"
echo   "   ③ 免责声明确认    ④ 镜像拉取源码"
echo   "   ⑤ 安装依赖        ⑥ 生成启动脚本"
echo   ""

# ---------- 环境 ----------
if [ -z "${PREFIX:-}" ] || [ ! -x "${PREFIX}/bin/pkg" ]; then
  fail "未检测到 Termux 环境。请使用官方 Termux，并在 Termux 中运行 bash install.sh。"
fi
ok "Termux 环境检查通过"

if [ ! -d "$HOME/storage" ]; then
  warn "如需读写手机存储(/sdcard)，请先运行一次: termux-setup-storage"
  warn "此步为可选，跳过不影响核心功能。"
fi

# ---------- ① 询问是否安装 ----------
printf "\n是否现在安装 BiliLearn? [y/N] "
read -r answer
case "$answer" in
  y|Y|yes|YES|是) ;;
  *) say "已取消安装，未做任何更改。"; exit 0 ;;
esac

# ---------- ② 选择安装路径 ----------
while :; do
  printf "\n选择安装路径（回车使用默认 ${DEFAULT_DIR}）:\n"
  printf "路径: "
  read -r dir_input
  if [ -z "$dir_input" ]; then
    INSTALL_DIR="$DEFAULT_DIR"
  else
    INSTALL_DIR="${dir_input/#\~/$HOME}"
  fi
  case "$INSTALL_DIR" in
    /*) ;;
    *) INSTALL_DIR="$PWD/$INSTALL_DIR" ;;
  esac
  printf "\n安装路径: ${c_g}%s${c_0}\n" "$INSTALL_DIR"
  if [ -e "$INSTALL_DIR" ] && [ ! -d "$INSTALL_DIR/.git" ]; then
    warn "该路径已存在且不是 Git 仓库，请换一个路径。"
    continue
  fi
  printf "确认使用此路径? [Y/n] "
  read -r dir_confirm
  case "$dir_confirm" in n|N|no|NO) continue ;; esac
  break
done

# ---------- ③ 免责声明（与网页端同款，输入「我同意」才能继续） ----------
printf "\n"
echo   "──────────────────────────────────────────"
echo   "           免责声明 / DISCLAIMER"
echo   "           请阅读并确认以下声明"
echo   "──────────────────────────────────────────"
echo   ""
echo   "        本项目仅供学习参考，"
echo   "  若因使用本项目产生任何后果，本人一概不负责。"
echo   ""
echo   "  This project is for learning purposes only."
echo   "  Any consequences are solely your own responsibility."
echo   ""
echo   "──────────────────────────────────────────"
printf "请输入：我同意\n"
while :; do
  printf "> "
  read -r consent
  case "$consent" in
    我同意|"I agree"|"i agree"|IAGREE|"согласен"|"Согласен")
      ok "已确认，继续安装..."
      break
      ;;
    q|Q|quit|exit)
      fail "已退出安装，未下载任何内容。"
      ;;
    *)
      printf "${c_r}✗ 请输入\"我同意\"${c_0}（输入 q 取消安装）\n"
      ;;
  esac
done

# ---------- ④ 安装系统依赖 + 测速镜像并拉取 ----------
say "步骤 1/4: 安装系统依赖..."
pkg update -y || warn "pkg update 失败，继续尝试..."
# coreutils provides timeout, which is used for mirror checks below.
if ! pkg install -y python git coreutils; then
  fail "关键 Termux 依赖安装失败（python/git/coreutils）。请检查网络和软件源后重试。"
fi
# Optional packages improve video analysis and native Python package builds.
for _pkg in ffmpeg libjpeg-turbo libyaml clang make binutils; do
  if pkg install -y "$_pkg"; then
    printf "${c_g}[✓]${c_0} 系统依赖 %s 已安装\n" "$_pkg"
  else
    warn "系统依赖 $_pkg 安装失败，继续安装核心功能。"
  fi
done
# 关键依赖校验：python 与 git 必须可用，否则终止
command -v python >/dev/null 2>&1 || fail "未检测到 python，请检查网络后重试。"
command -v git >/dev/null 2>&1 || fail "未检测到 git，请检查网络后重试。"

say "步骤 2/4: 测试 GitHub 镜像连通性..."
BEST=""
for m in "${MIRRORS[@]}"; do
  printf "  测试 %-28s " "$m ..."
  if run_with_timeout 8 git ls-remote --heads "$m/$REPO_URL" "$BRANCH" >/dev/null 2>&1; then
    printf "${c_g}可用${c_0}\n"
    BEST="$m"
    break
  else
    printf "${c_r}超时/不可用${c_0}\n"
  fi
done
if [ -n "$BEST" ]; then
  ok "使用镜像: $BEST"
  CLONE_URL="$BEST/$REPO_URL"
else
  warn "所有镜像均不可用，回退 GitHub 直连（国内网络可能较慢）。"
  CLONE_URL="$REPO_URL"
fi

say "步骤 3/4: 拉取源码到: $INSTALL_DIR"

clone_to_staging() {
  local url="$1"
  local staging_dir="${INSTALL_DIR}.download.$$"

  rm -rf "$staging_dir"
  if git clone --branch "$BRANCH" --depth 1 "$url" "$staging_dir"; then
    if mv "$staging_dir" "$INSTALL_DIR"; then
      return 0
    fi
  fi
  rm -rf "$staging_dir"
  return 1
}

if [ -d "$INSTALL_DIR/.git" ]; then
  if ! git -C "$INSTALL_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    fail "安装目录包含损坏的 Git 仓库: $INSTALL_DIR。请换一个目录或先备份后修复。"
  fi
  say "检测到已有仓库，执行更新..."
  if git -C "$INSTALL_DIR" remote get-url origin >/dev/null 2>&1; then
    git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
  else
    git -C "$INSTALL_DIR" remote add origin "$REPO_URL"
  fi
  if git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"; then
    if git -C "$INSTALL_DIR" show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git -C "$INSTALL_DIR" checkout "$BRANCH"
    else
      git -C "$INSTALL_DIR" checkout -b "$BRANCH" --track "origin/$BRANCH"
    fi
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" \
      || warn "已有目录存在本地改动，未强制覆盖，保留当前版本。"
  else
    warn "仓库更新失败，保留已有版本继续；如版本不完整请换一个安装目录重试。"
  fi
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  if clone_to_staging "$CLONE_URL"; then
    ok "源码拉取完成"
  else
    warn "首选下载源失败，尝试其余镜像..."
    CLONED=1
    for m in "${MIRRORS[@]}" ""; do
      [ "$m" = "$BEST" ] && continue
      TRY_URL="${m:+$m/}$REPO_URL"
      printf "  重试 %s ...\n" "${m:-GitHub 直连}"
      if clone_to_staging "$TRY_URL"; then
        ok "源码拉取完成（${m:-直连}）"; CLONED=0; break
      fi
    done
    [ "$CLONED" -eq 0 ] || fail "所有下载源均失败，请检查网络后重新运行本脚本。"
  fi
fi
cd "$INSTALL_DIR" || fail "无法进入安装目录: $INSTALL_DIR"

say "步骤 4/4: 安装 Python 依赖..."
python -m pip --version >/dev/null 2>&1 \
  || fail "当前 Python 没有可用 pip，请先执行: pkg install python"
python -m pip install --upgrade pip wheel setuptools \
  || warn "pip 升级失败，继续安装。"
python -m pip install PyYAML --no-build-isolation \
  || warn "PyYAML 安装跳过；若后续导入报错请运行: pkg install libyaml"
if ! python -m pip install -r requirements.txt; then
  warn "部分 Python 依赖在 Termux 上安装失败，开始检查网页面板所需的核心依赖。"
fi
check_python_imports

# ---------- 生成启动脚本 ----------
cat > "$INSTALL_DIR/start_termux.sh" <<'LAUNCHER'
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
export BILI_DISCLAIMER_SKIP=1
export BILI_WEB_AUTO_OPEN=0
export BILI_TRAY_DISABLED=1
export WEB_HOST=127.0.0.1
PORT="$(python -c "import utils.web_launcher as w; print(w.get_web_port())" 2>/dev/null || echo 18083)"
echo "[BiliLearn] 正在启动网页面板..."
echo "[BiliLearn] 在手机浏览器打开: http://127.0.0.1:${PORT}"
echo "[BiliLearn] Termux 中输入 Ctrl+C 停止。"
python web_panel.py
LAUNCHER
chmod +x "$INSTALL_DIR/start_termux.sh"

# ---------- 注册全局命令：abiligent / bilibili_learning_bot / bililearn ----------
# 三个命令等价，任一均可直接启动网页端（写入 $PREFIX/bin，Termux 默认在 PATH 中）
BIN_DIR="${PREFIX:-/data/data/com.termux/files/usr}/bin"
if [ -d "$BIN_DIR" ] && [ -w "$BIN_DIR" ]; then
  cat > "$BIN_DIR/bililearn" <<CMD
#!/data/data/com.termux/files/usr/bin/bash
exec bash "$INSTALL_DIR/start_termux.sh"
CMD
  chmod +x "$BIN_DIR/bililearn"
  # 另外两个名字做成软链接，节省空间且行为一致
  ln -sf "$BIN_DIR/bililearn" "$BIN_DIR/abiligent"
  ln -sf "$BIN_DIR/bililearn" "$BIN_DIR/bilibili_learning_bot"
  ok "全局命令已注册: bililearn / abiligent / bilibili_learning_bot"
else
  warn "无法写入 $BIN_DIR，改为写入 ~/.bashrc 别名"
  for cmd in bililearn abiligent bilibili_learning_bot; do
    grep -q "alias $cmd=" "$HOME/.bashrc" 2>/dev/null \
      || echo "alias $cmd='bash $INSTALL_DIR/start_termux.sh'" >> "$HOME/.bashrc"
  done
  ok "别名已写入 ~/.bashrc（新开 Termux 会话后生效）"
fi

# ---------- 完成 ----------
printf "\n"
echo   "=============================================="
printf " ${c_g}✅ 安装完成!${c_0}\n"
echo   "=============================================="
printf " 安装位置: %s\n" "$INSTALL_DIR"
echo   ""
echo   " 启动网页面板（任选其一）:"
printf "   ${c_g}bililearn${c_0}   (或 ${c_g}abiligent${c_0} / ${c_g}bilibili_learning_bot${c_0})\n"
printf "   bash \"${c_g}%s/start_termux.sh${c_0}\"\n" "$INSTALL_DIR"
echo   ""
printf " 是否立即启动网页面板? [y/N] "
read -r launch_now
case "$launch_now" in
  y|Y|yes|YES|是)
    export BILI_DISCLAIMER_SKIP=1 BILI_WEB_AUTO_OPEN=0 BILI_TRAY_DISABLED=1 WEB_HOST=127.0.0.1
    python web_panel.py
    ;;
  *)
    say "以后随时运行: bash \"$INSTALL_DIR/start_termux.sh\""
    ;;
esac
