[app]
# (str) Title of your application
title = BilibiliBot

# (str) Package name
package.name = bililibot

# (str) Package domain (needed for android/ios packaging)
package.domain = org.bilibilibot

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (process empty to include all files)
source.include_exts = py,png,jpg,kv,atlas,html,css,js,json,sh,txt,md

# (str) Application versioning (method 1)
version = 3.1.2

# (list) Application requirements
# 注意：只填纯 Python 基础库，复杂的第三方依赖让系统自带的 Python 环境自动处理
requirements = python3,kivy,pyjnius,openssl,ffmpeg,pillow,requests,urllib3,jinja2,colorama,flask,flask-cors,httpx,pydantic,qrcode,imageio-ffmpeg,yt-dlp,python-docx,reportlab,bilibili-api-python
# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
android.permissions = INTERNET,READ_EXTERNAL_STORAGE
# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK will support.
android.minapi = 21

# (str) Android architecture to build for
android.archs = arm64-v8a

[buildozer]
# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = false, 1 = true)
warn_on_root = 1
