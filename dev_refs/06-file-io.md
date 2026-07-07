# 文件 I/O 与数据存储规范 (File I/O & Storage)

> 项目中的文件读写、JSON 处理、路径管理规范。

## JsonStore — 线程安全的 JSON 读写（推荐）

```python
from utils.storage import JsonStore

# 创建存储实例
store = JsonStore("Data/my_data.json")

# 读取（不存在返回空 dict）
data = store.read()  # 或 store.read(default={})

# 写入（原子写入 tmp+rename）
store.write({"key": "value"})

# 原子读-改-写（并发安全）
store.update(lambda d: d.update({"key": "new_value"}))
```

## 核心 JSON 工具函数

```python
from core.config import load_json_file, save_json_file

# 读取（不存在返回默认值）
data = load_json_file("path/to/file.json", default={})

# 写入（原子写入）
save_json_file("path/to/file.json", data)
```

## 路径管理（使用 pathlib）

```python
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 常用路径
DATA_DIR = BASE_DIR / "Data"
KNOWLEDGE_BASE_DIR = BASE_DIR / "KnowledgeBase"
EXPORT_DIR = BASE_DIR / "html_exports" / "quizzes"

# 确保目录存在
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
```

## 文件写入模式

```python
# 文本文件写入
from datetime import datetime

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
filepath = EXPORT_DIR / f"quiz_{timestamp}.md"

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

# Markdown 报告保存
report_path = KNOWLEDGE_BASE_DIR / "深入学习" / f"{topic}_{timestamp}.md"
os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(report_content)
```

## Cookie 文件格式

```json
{
    "SESSDATA": "xxx",
    "bili_jct": "xxx",
    "buvid3": "xxx-infoc",
    "DedeUserID": "12345"
}
```

## 文件命名规范

```python
from utils.helpers import sanitize_filename

# 清理文件名中的非法字符
safe_name = sanitize_filename("Python: 入门/进阶*教程", is_folder=False)
# → "Python 入门进阶教程"（最多100字符）

safe_folder = sanitize_filename("Python/入门", is_folder=True)
# → "Python入门"（最多10字符）
```

## 原子写入模式（重要！）

所有配置和数据文件都使用 **tmp + rename** 模式，防止写入过程中断电导致文件损坏：

```python
import os, json

def atomic_write(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # 原子操作
```

## 导出目录结构

```
html_exports/
├── quizzes/          # 出题考试导出
├── deep_dives/       # 深入了解报告
├── video_html/       # 视频转网页
└── ...
```

## ⚠️ 重要注意事项

1. **编码**: 所有文件读写必须指定 `encoding='utf-8'`
2. **原子写入**: 使用 tmp+replace，不要直接覆盖
3. **路径分隔**: 使用 `Path` / `os.path.join`，不要硬编码 `/` 或 `\`
4. **目录创建**: 写入前确保父目录存在 `os.makedirs(dir, exist_ok=True)`
5. **并发安全**: Web 面板使用 `JsonStore`（带锁），CLI 可用 `load_json_file` / `save_json_file`
