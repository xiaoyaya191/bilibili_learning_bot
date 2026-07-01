#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  bilibili_learning_bot 3.0.1 - Termux (Android) 安装脚本
# ============================================================
#  用法: bash install_termux.sh
#  功能: 自动安装系统依赖 + Python 依赖，解决 PyYAML 编译问题
# ============================================================

set -e

echo "========================================"
echo " bilibili_learning_bot v3.0.1 安装脚本"
echo " 环境: Termux (Android)"
echo "========================================"
echo ""

# ---------- Step 1: 更新 Termux 包管理器 ----------
echo "[1/4] 更新 Termux 包列表..."
pkg update -y
pkg upgrade -y

# ---------- Step 2: 安装系统依赖 ----------
echo ""
echo "[2/4] 安装系统编译依赖 (libyaml 解决 PyYAML 编译问题)..."
pkg install -y python python-pip libyaml libyaml-dev clang make binutils

# ---------- Step 3: 升级 pip ----------
echo ""
echo "[3/4] 升级 pip..."
pip install --upgrade pip setuptools wheel

# ---------- Step 4: 安装 Python 依赖 ----------
echo ""
echo "[4/4] 安装 Python 项目依赖..."

# 先单独安装 PyYAML (指定使用系统 libyaml，避免编译失败)
echo "  -> 安装 PyYAML (使用系统 libyaml)..."
pip install PyYAML --no-build-isolation

# 安装其余依赖
echo "  -> 安装项目依赖..."
pip install -r requirements.txt

echo ""
echo "========================================"
echo " ✅ 安装完成!"
echo "========================================"
echo ""
echo "运行方式: python main.py"
echo ""
