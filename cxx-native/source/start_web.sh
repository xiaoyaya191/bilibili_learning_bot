#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Users/12063/Documents/Codex/2026-08-04/https-github-com-xiaoyaya191-bilibili-learning/repo/cxx
pkill -f 'bili -data' 2>/dev/null || true
nohup ./build/bili -data /mnt/c/Users/12063/AppData/Local/BiliLearn -web 8080 > /tmp/bili_web.log 2>&1 &
sleep 1
ss -ltn | grep 8080 || true
echo 'web server started'
echo 'LAN URL: http://192.168.3.41:8080'
