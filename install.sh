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

set -u

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
case "$(uname -o 2>/dev/null || true)" in
  Android*) ;;
  *) fail "本脚本仅适用于 Android Termux 环境。" ;;
esac
command -v pkg >/dev/null 2>&1 || fail "未检测到 Termux pkg，请先安装官方 Termux 应用。"
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
# Termux 的 libyaml 已自带开发头文件，没有独立的 libyaml-dev 包，故不再单独安装。
# 改为逐个安装：单个可选依赖失败不阻断整体流程，仅对关键依赖做最终校验。
for _pkg in python git ffmpeg libjpeg-turbo libyaml clang make binutils; do
  pkg install -y "$_pkg" >/dev/null 2>&1 \
    && printf "${c_g}[✓]${c_0} 系统依赖 %s 已安装\n" "$_pkg" \
    || warn "系统依赖 $_pkg 安装失败（可选，可继续）"
done
# 关键依赖校验：python 与 git 必须可用，否则终止
command -v python >/dev/null 2>&1 || fail "未检测到 python，请检查网络后重试。"
command -v git >/dev/null 2>&1 || fail "未检测到 git，请检查网络后重试。"

say "步骤 2/4: 测试 GitHub 镜像连通性..."
BEST=""
for m in "${MIRRORS[@]}"; do
  printf "  测试 %-28s " "$m ..."
  if timeout 8 git ls-remote --heads "$m/$REPO_URL" "$BRANCH" >/dev/null 2>&1; then
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
mkdir -p "$INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
  say "检测到已有仓库，执行更新..."
  git -C "$INSTALL_DIR" fetch origin "$BRANCH" \
    || git -C "$INSTALL_DIR" remote set-url origin "$CLONE_URL"
  git -C "$INSTALL_DIR" checkout "$BRANCH" || true
  git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" \
    || warn "更新失败，保留当前版本继续。"
else
  if git clone --branch "$BRANCH" --depth 1 "$CLONE_URL" "$INSTALL_DIR"; then
    ok "源码拉取完成"
  else
    warn "首选下载源失败，尝试其余镜像..."
    CLONED=1
    for m in "${MIRRORS[@]}" ""; do
      [ "$m" = "$BEST" ] && continue
      TRY_URL="${m:+$m/}$REPO_URL"
      printf "  重试 %s ...\n" "${m:-GitHub 直连}"
      rm -rf "$INSTALL_DIR"
      if git clone --branch "$BRANCH" --depth 1 "$TRY_URL" "$INSTALL_DIR"; then
        ok "源码拉取完成（${m:-直连}）"; CLONED=0; break
      fi
    done
    [ "$CLONED" -eq 0 ] || fail "所有下载源均失败，请检查网络后重新运行本脚本。"
  fi
fi
cd "$INSTALL_DIR" || fail "无法进入安装目录: $INSTALL_DIR"

say "步骤 4/4: 安装 Python 依赖..."
python -m pip install --upgrade pip wheel setuptools \
  || warn "pip 升级失败，继续安装。"
python -m pip install PyYAML --no-build-isolation \
  || warn "PyYAML 安装跳过；若后续导入报错请运行: pkg install libyaml"
python -m pip install -r requirements.txt \
  || warn "部分可选依赖在 Termux 上跳过，不影响网页面板与基本流程。"

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
