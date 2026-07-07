import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import web_panel as w
html = w._load_html()
print("len=", len(html))
keys = [
    "UP批量学习", "视频转网页", "自定义知识", "学习工具",
    'id="pg-uplearn"', 'id="pg-video2web"', 'id="pg-customkb"', 'id="pg-learn-tools"',
    "v2wRenderStyles", "ckRefresh", "pollTask",
    "api/action/up-learn", "api/action/video2web", "api/action/quiz",
    "api/kb/custom-list", "api/action/deep-dive",
]
for k in keys:
    print(("FOUND  " if k in html else "MISSING ") + k)
