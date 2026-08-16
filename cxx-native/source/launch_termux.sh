#!/data/data/com.termux/files/usr/bin/bash
# Build (if needed) and start the panel on Termux.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x build-termux/bili ]; then
  bash termux_build.sh
fi
DATA="${BILI_USER_DATA_DIR:-$HOME/BiliLearn}"
exec ./build-termux/bili -data "$DATA" -web 8080 -html web_panel.html "$@"
