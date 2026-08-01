# -*- mode: python ; coding: utf-8 -*-

# This is a local web application. ML/ASR runtimes are intentionally excluded:
# their native dependency trees are optional and must not block the web app
# from launching when no local ASR engine has been installed.
from PyInstaller.utils.hooks import copy_metadata

datas = [
    ('VERSION', '.'),
    ('config.example.json', '.'),
    ('web_panel.html', '.'),
    ('app-icons', 'app-icons'),
    ('templates', 'templates'),
    ('assets', 'assets'),
]
# Werkzeug asks importlib.metadata for its installed distribution version while
# Flask starts the development server. PyInstaller includes its code but does
# not reliably include .dist-info under Python 3.13, so ship both metadata
# directories explicitly.
datas += copy_metadata('flask') + copy_metadata('werkzeug')
binaries = []
hiddenimports = [
    # Used from request handlers and tray callbacks. Keeping these explicit
    # makes their frozen import behavior independent of static-analysis quirks.
    'pystray._win32',
    'bilibili_api.login_v2',
    # bilibili-api selects its transport with importlib at runtime. Include
    # every bundled client implementation; otherwise QR login and video
    # analysis fail in a frozen build with HTTPXClient missing.
    'bilibili_api.clients',
    'bilibili_api.clients.HTTPXClient',
    'bilibili_api.clients.CurlCFFIClient',
    'bilibili_api.clients.AioHTTPClient',
    'bilibili_api.favorite_list',
    'bilibili_api.search',
    'bilibili_api.session',
    # QR rendering is guarded by an optional import in web_panel.py. Declare
    # the full runtime chain so recipients do not need a local Python install.
    'qrcode',
    'qrcode.image.pil',
    'PIL',
    'PIL.Image',
    'PIL.PngImagePlugin',
    'bilibili_api.utils.network',
    # These modes are launched internally by the frozen desktop executable.
    'main',
    'brain.monitor',
    'brain.standby',
]
optional_ml_excludes = [
    'faiss', 'funasr', 'huggingface_hub', 'jieba', 'llvmlite', 'modelscope',
    'numba', 'onnxruntime', 'pandas', 'pyarrow', 'scipy', 'sentence_transformers',
    'sklearn', 'torch', 'torchaudio', 'transformers',
]


a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=optional_ml_excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BiliLearn Web',
    icon='app-icons/BiliLearn.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BiliLearn Web',
)
