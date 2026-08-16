[app]
title = BilibiliBot
package.name = bililibot
package.domain = org.bilibilibot
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,html,css,js,json,sh,txt,md
version = 3.1.2

# 包含了核心组件以及常规项目所需的完整第三方库
requirements = python3,kivy,pyjnius,openssl,ffmpeg,pillow,requests,urllib3,jinja2,colorama,flask,flask-cors,httpx,pydantic,qrcode,imageio-ffmpeg,yt-dlp,python-docx,reportlab,bilibili-api-python

orientation = portrait
fullscreen = 0
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO,MANAGE_EXTERNAL_STORAGE


android.api = 33
android.minapi = 21
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
