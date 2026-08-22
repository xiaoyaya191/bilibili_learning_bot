# -*- mode: python ; coding: utf-8 -*-

# This is a local web application. ML/ASR runtimes are intentionally excluded:
# their native dependency trees are optional and must not block the web app
# from launching when no local ASR engine has been installed.
from PyInstaller.utils.hooks import copy_metadata

datas = [
    ('VERSION', '.'),
    ('config.example.json', '.'),
    ('web_panel.html', '.'),
    ('project_intro.html', '.'),
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
    'httpx',
    # httpx HTTP/2 栈：api/client.py 在 h2 可用时启用 http2=True，
    # 冻结构建下必须显式携带，否则全部请求回退且元数据失败。
    'h2',
    'hpack',
    'hyperframe',
    'aiohttp',
    'colorama',
    'flask_cors',
    'imageio_ffmpeg',
    'python_docx',
    'reportlab',
    # 学习小目标：web_panel 路由与 brain 主循环均在函数体内延迟 import，
    # 静态分析可能漏掉，显式声明确保冻结构建可用。
    'services.mini_goal',
    # 拟人随机搜索：brain 主循环函数体内延迟 import，静态分析漏掉，显式声明。
    'services.human_search',
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

# ── Windows 版本资源：让 EXE 文件属性显示产品名/版本/版权/原始文件名 ──
# 版本号读取仓库根目录 VERSION（x.y.z → 文件版本 x.y.z.0），构建时生成
# version_info.txt 供 PyInstaller 打包，避免手工维护第二份版本号。


def _version_tuple(raw):
    parts = []
    for piece in str(raw).strip().split('.'):
        digits = ''.join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


_app_version = '3.1.3'
try:
    with open('VERSION', 'r', encoding='utf-8') as _vf:
        _app_version = _vf.read().strip() or '3.1.3'
except OSError:
    pass
_vers = _version_tuple(_app_version)
_version_info = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_vers},
    prodvers={_vers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', 'xiaoyaya team'),
        StringStruct('FileDescription', 'BiliLearn Web 客户端'),
        StringStruct('FileVersion', '{_vers[0]}.{_vers[1]}.{_vers[2]}.{_vers[3]}'),
        StringStruct('InternalName', 'BiliLearn Web'),
        StringStruct('OriginalFilename', 'BiliLearn Web.exe'),
        StringStruct('ProductName', 'BiliLearn Web'),
        StringStruct('ProductVersion', '{_app_version}'),
        StringStruct('LegalCopyright', '版权所有(C) 2026 xiaoyaya team'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
with open('version_info.txt', 'w', encoding='utf-8') as _vf:
    _vf.write(_version_info)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BiliLearn Web',
    icon='app-icons/BiliLearn.ico',
    version='version_info.txt',
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
