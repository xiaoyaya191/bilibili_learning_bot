#!/data/data/com.termux/files/usr/bin/bash
# Build bili_native on Termux with bionic + system .so libs.
set -euo pipefail

echo "[1/3] Installing dependencies..."
pkg install -y curl libcurl openssl zlib ffmpeg cmake make clang pkg-config ca-certificates

echo "[2/3] Configuring..."
cd "$(dirname "$0")"
rm -rf build-termux
cmake -S . -B build-termux \
  -DCMAKE_BUILD_TYPE=Release \
  -DBILI_DISABLE_BUNDLED_FFMPEG=ON

echo "[3/3] Building..."
cmake --build build-termux -j"$(nproc)"

echo "[OK] binary: build-termux/bili"
echo "Run: ./build-termux/bili -data \$HOME/BiliLearn -web 8080 -html web_panel.html"
