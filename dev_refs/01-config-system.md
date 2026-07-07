# 配置系统 (Config System)

> 文件: `core/config.py`
> 这是整个项目的配置中心，所有模块都从这里读取配置。

## 配置存储位置

| 文件 | 路径 | 用途 |
|------|------|------|
| `config.json` | `Data/config.json` | 主配置文件 |
| `bilibili_cookies.json` | `Data/bilibili_cookies.json` | B站登录Cookie |

## 配置加载方式

```python
# 方式1: 直接从 config 字典读取（推荐，实时生效）
from core.config import config
api_key = config.get("api", {}).get("unified_api_key", "")

# 方式2: 通过模块级变量（动态 __getattr__，每次读取实时获取）
from core.config import UNIFIED_API_KEY, UNIFIED_BASE_URL, MODEL_BRAIN

# 方式3: 通过 get_config_or_env（优先环境变量）
from core.config import get_config_or_env
val = get_config_or_env("api", "unified_api_key", "BILI_AI_API_KEY")
```

## API 配置项

```json
{
  "api": {
    "unified_api_key": "sk-xxx",      // 主 API Key
    "unified_base_url": "https://api.openai.com/v1",  // 主 API 地址
    "model_brain": "gpt-4.1-mini",    // 思考模型
    "model_vision": "gpt-4o",         // 视觉模型
    "model_html": "gpt-4.1-mini",     // HTML 生成模型
    "vision_api_key": "",             // 视觉专用 Key（空=用 unified）
    "vision_base_url": ""             // 视觉专用 URL（空=用 unified）
  },
  "fallback_provider": {             // 备用 API 提供商
    "enabled": false,
    "name": "备用API",
    "api_key": "",
    "base_url": "",
    "models": {"chat": "", "vision": ""}
  },
  "fallback_models": {               // 模型降级列表
    "chat": "", "vision": "", "fast": ""
  }
}
```

## 保存配置（原子写入）

```python
from core.config import save_config, config

# 修改配置
config["api"]["model_brain"] = "gpt-4.1"

# 保存（自动原子写入 tmp + rename）
save_config(config)
```

## 路径常量

```python
from core.config import (
    BASE_DIR,          # 项目根目录
    DATA_DIR,          # Data/ 数据目录
    CONFIG_FILE,       # Data/config.json
    COOKIE_FILE,       # Data/bilibili_cookies.json
    KNOWLEDGE_BASE_DIR, # KnowledgeBase/ 知识库目录
    HIGHLIGHTS_DIR,    # highlights/ 归档目录
)
```

## 环境变量支持

| 环境变量 | 对应配置 | 用途 |
|----------|----------|------|
| `BILI_AI_API_KEY` | `api.unified_api_key` | API Key |
| `BILI_AI_BASE_URL` | `api.unified_base_url` | API 地址 |
| `BILI_AI_MODEL_BRAIN` | `api.model_brain` | 思考模型 |
| `BILI_AI_MODEL_VISION` | `api.model_vision` | 视觉模型 |
| `BILI_AI_MODEL_HTML` | `api.model_html` | HTML模型 |
| `BILI_ACCOUNT_DATA_DIR` | - | 多账号数据目录（Web面板） |
| `BILI_ACCOUNT_NAME` | - | 账号显示名称（Web面板） |
| `BILI_CIPHER_KEY` | - | 敏感词加密密钥 |

## JSON 文件工具函数

```python
from core.config import load_json_file, save_json_file

# 读取（不存在返回默认值）
data = load_json_file("/path/to/file.json", default={})

# 写入（原子写入 tmp+replace）
save_json_file("/path/to/file.json", data)
```

## 日志函数

```python
from core.config import log

log("消息内容", "INFO")     # 白色
log("成功", "SUCCESS")      # 绿色
log("警告", "WARN")         # 黄色
log("错误", "ERROR")        # 红色
log("调试", "DEBUG")        # 青色
```

## 敏感信息脱敏

```python
from core.config import mask_secret

# 输出: "sk-abc...xyz1"
print(mask_secret("sk-abc123def456xyz1"))
# 输出: "***********"
print(mask_secret("shortkey"))
```
