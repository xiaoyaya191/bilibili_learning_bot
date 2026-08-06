#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
export LD_LIBRARY_PATH="$PWD/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export BILI_CA_BUNDLE="${BILI_CA_BUNDLE:-$PWD/cacert.pem}"
DATA="${BILI_USER_DATA_DIR:-$HOME/BiliLearn}"
echo "[OK] data dir: $DATA"
echo "[OK] libs: $(ls "$PWD"/lib/*.so* | wc -l)"
exec ./bili-termux-arm64 -data "$DATA" -web 8080 -html web_panel.html "$@"
