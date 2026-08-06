[app]
title = BilibiliBot
package.name = bilibilibot
package.domain = org.bilibilibot
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt

version = 3.1.2

requirements = python3,kivy,bilibili-api-python,pydantic,httpx,colorama,qrcode,Pillow,pystray,Flask,flask-cors,requests,imageio-ffmpeg,yt-dlp,python-docx,reportlab,funasr,torch,torchaudio,sentence-transformers,numpy

orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 33
android.ndk = 25b
android.sdk = 24
package.type = debug
log_level = 2

[buildozer]
log_level = 2
warn_on_root = 1
