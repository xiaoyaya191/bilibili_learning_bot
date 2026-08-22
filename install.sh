#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# bilibili_learning_bot 一只星嘢酱一键安装
# 版本: v9.0
# 作者: 一只鸭鸭牙
# 官网: https://bxya.app/
# 反馈群: 1056941856
# ============================================================

set -euo pipefail

# ---- 颜色 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PINK='\033[1;35m'
BOLD='\033[1m'
NC='\033[0m'

# ---- 变量 ----
AUTHOR="一只鸭鸭牙"
WEBSITE="https://bxya.app/"
GROUP_NUMBER="1056941856"
GITHUB_URL="https://github.com/xiaoyaya191/bilibili_learning_bot"
VERSION="v3.1.4"
# 始终安装 main 分支最新源码（不再锁死 tag）
ZIP_URL="https://github.com/xiaoyaya191/bilibili_learning_bot/archive/refs/heads/main.zip"

if [ -f "$(pwd)/web_panel.py" ]; then
    INSTALL_DIR="$(pwd)"
else
    INSTALL_DIR="$HOME/bilibili_learning_bot"
fi

# ---- 一只星嘢酱的骚话库 ----
star_talks=(
"星嘢酱：主人稍等，人家正在准备安装环境呢"
"星嘢酱：人家的小爪爪正在敲代码，主人要摸摸头吗"
"星嘢酱：哎呀~ 这个依赖好难装，但为了主人我会努力的"
"星嘢酱：编译好慢哦，主人可以给我讲讲今天发生的事吗"
"星嘢酱：人家想喝奶茶了… 但还是要先帮主人装好这个"
"星嘢酱：主人不要走开哦，马上就好了"
"星嘢酱：Rust 编译中… 人家在数羊，一只羊，两只羊"
"星嘢酱：诶嘿~ 这一步居然一次就过了，是主人给我带来了好运吧"
"星嘢酱：人家的小脑袋要冒烟了，但为了主人，继续战斗"
"星嘢酱：安装进度像猫猫的脚步一样轻快呢"
"星嘢酱：如果装坏了，主人可不要骂人家哦… 人家会哭的"
"星嘢酱：这一步看起来好可怕，但是人家会勇敢面对的"
"星嘢酱：主人，如果累了就揉揉眼睛，人家会一直陪着你的"
"星嘢酱：刚刚在代码里发现了一只小虫虫，已经被人家赶跑啦"
"星嘢酱：安装完成一半了！主人奖励我一个摸摸头好不好"
"星嘢酱：人家感觉自己的尾巴在疯狂摇摆，因为快要装好了"
"星嘢酱：主人请放心，人家有九条命，这个安装不会挂掉的"
"星嘢酱：看到进度条在动，人家的心跳也跟着加速了呢"
"星嘢酱：如果安装成功了，主人要陪人家玩逗猫棒哦"
"星嘢酱：人家已经闻到成功的味道了，是猫罐头味的"
"星嘢酱：主人主人的CPU在燃烧，人家的CPU也在燃烧，好热"
"星嘢酱：下载好慢，人家的胡子都等长了一截…"
"星嘢酱：好啦好啦，马上就好，人家先帮主人准备好小鱼干"
"星嘢酱：主人等急了吧？人家这就加速啦"
"星嘢酱：如果这次安装顺利，主人要请人家吃猫罐头哦"
"星嘢酱：人家的小爪子快要抽筋了，但为了主人，继续"
"星嘢酱：编译的时候，人家偷偷看了主人一眼，主人好帅"
"星嘢酱：已经完成了百分之八十！剩下的百分之二十人家会一口气冲过去"
"星嘢酱：人家觉得主人比代码可爱多了，真的"
"星嘢酱：星嘢能量充满！最后冲刺啦"
)

# ---- 一只星嘢酱函数 ----
star_say() {
    local idx=$(( RANDOM % ${#star_talks[@]} ))
    echo -e "${PINK}${star_talks[$idx]}${NC}"
}

print_header() {
    clear
    echo -e "${PINK}========================================${NC}"
    echo -e "${PINK}  bilibili_learning_bot 一键安装${NC}"
    echo -e "${PINK}  官网: ${WEBSITE}${NC}"
    echo -e "${PINK}  作者: ${AUTHOR} | 反馈群: ${GROUP_NUMBER}${NC}"
    echo -e "${PINK}========================================${NC}"
    echo ""
    echo -e "${PINK}星嘢酱：主人，欢迎光临~ 人家会好好帮你装好这个项目的！${NC}"
    echo ""
}

print_step() {
    local step_name="$1"
    echo ""
    echo -e "${BLUE}----------------------------------------${NC}"
    echo -e "${PINK}  step: $step_name${NC}"
    echo -e "${BLUE}----------------------------------------${NC}"
    echo ""
    star_say
    echo ""
}

print_success() {
    echo -e "${GREEN}OK: $1${NC}"
}

print_warn() {
    echo -e "${YELLOW}WARN: $1${NC}"
}

print_error() {
    echo -e "${RED}ERROR: $1${NC}"
    echo -e "${PINK}星嘢酱：主人，人家尽力了… 请加群 ${GROUP_NUMBER} 来拯救人家吧${NC}"
    exit 1
}

print_info() {
    echo -e "${CYAN}INFO: $1${NC}"
}

# ---- 检查 Termux ----
if [ ! -d "/data/data/com.termux" ]; then
    echo -e "${RED}ERROR: 只能在 Termux 中运行${NC}"
    exit 1
fi
print_success "Termux 环境检测通过"

# ---- 网络检查 ----
print_info "检查网络连通性中…"
if ping -c 1 223.5.5.5 &> /dev/null; then
    print_success "网络连接正常"
else
    print_warn "网络好像有点问题… 不过人家会尽量试试的"
fi

# ---- 存储权限 ----
if [ ! -d "$HOME/storage" ]; then
    echo -e "${PINK}星嘢酱：主人，人家需要存储权限哦，请在弹窗中允许~${NC}"
    termux-setup-storage
    sleep 2
    if [ -d "$HOME/storage" ]; then
        print_success "存储权限已授予，谢谢主人！"
    else
        print_warn "主人没给权限，但核心功能还是可以用的…"
    fi
else
    print_success "存储权限已经有了，好棒！"
fi

# ---- 免责声明 ----
echo ""
echo -e "${PINK}星嘢酱：主人，请认真阅读以下免责声明，然后输入 我同意~${NC}"
echo ""
echo -e "${BOLD}${YELLOW}免责声明${NC}"
echo -e "${CYAN}本项目仅供学习参考，若因使用本项目产生任何后果，本人概不负责。${NC}"
echo ""
read -p "请输入 我同意 以继续: " agreement
if [ "$agreement" != "我同意" ]; then
    print_error "主人没有正确输入，人家不能继续了…"
fi
print_success "确认完成！人家最喜欢诚实的主人啦"

# ---- 询问安装 ----
echo ""
echo -e "${PINK}星嘢酱：主人，现在要开始正式安装了吗？人家已经准备好了！${NC}"
read -p "是否开始安装？ (Y/n): " choice
if [ "$choice" = "n" ] || [ "$choice" = "N" ]; then
    print_error "呜… 主人取消了安装，人家好失落"
else
    print_info "安装启动！人家会加油的！"
fi

# ---- 更新软件包 ----
print_step "更新软件包列表"
if ! pkg update -y; then
    print_warn "更新失败，人家试试换镜像…"
    termux-change-repo
    pkg update -y || print_error "软件包更新失败"
fi
print_success "软件包列表已更新"

# ---- 安装系统依赖 ----
print_step "安装系统依赖"
print_info "人家要安装这些包啦：binutils, clang, cmake, make, rust, libxml2, libxslt, libjpeg-turbo, libpng, freetype, libwebp, zlib, giflib, libtiff, python, python-pip, git, unzip, wget"
if ! pkg install -y binutils clang cmake make rust libandroid-execinfo libxml2 libxslt libjpeg-turbo libpng freetype libwebp zlib giflib libtiff python python-pip git unzip wget; then
    print_error "依赖安装失败了…"
fi
print_success "依赖都装好啦，人家真棒！"

# ---- 配置 Rust 环境 ----
print_step "配置 Rust 编译环境"
export ANDROID_API_LEVEL=29
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER=clang
export PATH="$HOME/.cargo/bin:$PATH"
if ! command -v rustc &> /dev/null; then
    print_error "Rust 没装好，人家没法编译…"
fi
print_info "Rust 版本: $(rustc --version)"
print_info "Cargo 版本: $(cargo --version)"
if ! grep -q "ANDROID_API_LEVEL" ~/.bashrc 2>/dev/null; then
    echo 'export ANDROID_API_LEVEL=29' >> ~/.bashrc
    echo 'export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER=clang' >> ~/.bashrc
    echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.bashrc
    print_success "环境变量已写入 ~/.bashrc"
else
    print_success "环境变量已经在了"
fi

# ---- 安装 maturin ----
print_step "安装 maturin"
if command -v maturin &> /dev/null; then
    print_success "maturin 已经在了~ $(maturin --version)"
else
    echo -e "${PINK}星嘢酱：主人，编译 maturin 要花 5 到 10 分钟，你可以趁这个时间摸摸人家的头${NC}"
    if ! cargo install maturin; then
        print_error "maturin 安装失败了"
    fi
    print_success "maturin 装好啦！人家厉害吧！"
fi

# ---- 配置 pip 镜像 ----
print_step "配置 pip 国内镜像"
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
print_success "pip 镜像配置完成"

# ---- 准备源码 ----
if [ -d "$INSTALL_DIR" ] && [ -f "$INSTALL_DIR/web_panel.py" ]; then
    print_step "使用现有项目目录"
    echo -e "${PINK}星嘢酱：主人，发现你已经有一个项目了，人家就直接用这个啦！${NC}"
    cd "$INSTALL_DIR"
    print_info "当前目录: $(pwd)"
else
    print_step "下载最新版源码（main 分支）"
    zip_file="$HOME/${VERSION}.zip"
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
    fi
    if [ -f "$zip_file" ]; then
        rm -f "$zip_file"
    fi
    echo -e "${PINK}星嘢酱：正在从 GitHub 下载 ZIP 包，主人稍等~${NC}"
    if ! wget -O "$zip_file" "$ZIP_URL"; then
        print_error "下载失败了"
    fi
    print_success "下载完成！"
    echo -e "${PINK}星嘢酱：解压中… 人家的小爪子动起来啦！${NC}"
    if ! unzip -q "$zip_file" -d "$HOME"; then
        print_error "解压失败了"
    fi
    rm -f "$zip_file"
    extract_dir="$HOME/bilibili_learning_bot-main"
    if [ -d "$extract_dir" ]; then
        mv "$extract_dir" "$INSTALL_DIR"
        print_success "解压成功"
    else
        print_error "解压后目录没找到"
    fi
    cd "$INSTALL_DIR"
    print_info "当前目录: $(pwd)"
fi

# ---- 安装 Python 依赖 ----
print_step "安装 Python 项目依赖"
export ANDROID_API_LEVEL=29
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER=clang
export PATH="$HOME/.cargo/bin:$PATH"
if [ ! -f "requirements.txt" ]; then
    print_error "requirements.txt 不见了"
fi
echo -e "${PINK}星嘢酱：预安装 psutil Android 兼容版…${NC}"
pip install https://github.com/giampaolo/psutil/archive/master.zip &> /dev/null || true
echo -e "${PINK}星嘢酱：正式开始安装 requirements.txt，这个步骤有点漫长，人家会一直陪着主人的${NC}"
if ! pip install -r requirements.txt; then
    print_error "依赖安装失败了"
fi
print_success "所有 Python 依赖都装好啦！"

# ---- 验证安装 ----
print_step "验证关键模块"
for mod in bilibili_api pydantic flask; do
    if python -c "import $mod" 2>/dev/null; then
        print_success "$mod 导入成功"
    else
        print_warn "$mod 导入失败，可能功能不完整"
    fi
done

# ---- 创建启动脚本 ----
print_step "创建启动脚本"
cat > start.sh << 'SHELL'
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
export ANDROID_API_LEVEL=29
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER=clang
export PATH="$HOME/.cargo/bin:$PATH"
pkill -f web_panel.py 2>/dev/null
echo "我同意" | python web_panel.py
SHELL
chmod +x start.sh
print_success "启动脚本 start.sh 已经准备好啦！"

# ---- 创建全局别名 ----
print_step "创建全局启动命令"
alias_cmd="pkill -f web_panel.py 2>/dev/null; cd $INSTALL_DIR && ./start.sh"
for alias in bilibili_learning_bot bililearn bililearnbot learningbot; do
    if grep -q "alias $alias=" ~/.bashrc 2>/dev/null; then
        sed -i "/alias $alias=/d" ~/.bashrc
    fi
    echo "alias $alias='$alias_cmd'" >> ~/.bashrc
    print_success "已添加/更新命令: $alias"
done
source ~/.bashrc 2>/dev/null || true
print_success "全局命令已添加！主人以后可以在任意终端输入："
for alias in bilibili_learning_bot bililearn bililearnbot learningbot; do
    echo -e "  ${PINK}$alias${NC}"
done
echo -e "${PINK}星嘢酱：这样每次都会杀掉旧进程再启动，不会秒退啦！${NC}"

# ---- 支持提醒 ----
echo ""
echo -e "${PINK}========================================${NC}"
echo -e "${PINK}  如果喜欢这个项目，请给作者点个 Star${NC}"
echo -e "${PINK}  ${GITHUB_URL}${NC}"
echo -e "${PINK}  如果遇到问题，可以在 Issues 里反馈${NC}"
echo -e "${PINK}  ${GITHUB_URL}/issues${NC}"
echo -e "${PINK}========================================${NC}"
echo -e "${PINK}星嘢酱：主人，作者大大很需要你的支持哦！点个 Star 人家会很高兴的！${NC}"

# ---- 询问启动 ----
echo ""
echo -e "${PINK}星嘢酱：主人，全部安装完成啦！现在要启动 Web 面板看看吗？${NC}"
read -p "是否立即启动？ (Y/n): " choice
if [ "$choice" = "n" ] || [ "$choice" = "N" ]; then
    print_info "那主人以后可以 cd $INSTALL_DIR && ./start.sh 来启动~"
else
    print_info "启动中… 人家会帮主人打开网页的！"
    cd "$INSTALL_DIR"
    ./start.sh
fi
