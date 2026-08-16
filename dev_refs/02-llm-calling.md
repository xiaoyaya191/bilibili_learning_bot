# LLM/AI 调用规范 (LLM Calling Patterns)

> 项目使用 OpenAI 兼容 API，支持多后端、多模型降级、备用提供商。

## 方式1: 共享 AI 调用层（新服务推荐 ⭐）

适用于独立服务模块（如 `services/quiz_generator.py`, `services/deep_dive.py`）。
**所有 services/ 下的新模块请统一使用 `services/_services_ai.py`**。

### 核心入口：`call_ai()`

```python
from services._services_ai import call_ai, _live_config

# 1. 检查配置
live = _live_config()
if not live.get("api_key"):
    print("请先配置 unified_api_key")
    return

# 2. 一键调用（自动 openai → httpx 双后端降级 + 3次重试）
result_text = await call_ai(
    messages=[
        {"role": "system", "content": "你是AI助手"},
        {"role": "user", "content": "你好"}
    ],
    temperature=0.7,
    max_tokens=2000,
    timeout=120,
    verbose=True,   # 控制是否输出重试/降级日志
)
print(result_text)
```

### _services_ai.py 内部架构（Claude 风格）

模仿 `brain/_brain_ai.py` 的设计：

| 函数 | 作用 |
|------|------|
| `_live_config()` | 实时读取 API 配置（env 变量优先，config.json 兜底） |
| `_call_ai_via_openai()` | 主通道：openai 库 |
| `_call_ai_via_httpx()` | 备用通道：httpx 直连（手动 UTF-8 序列化，修复 Windows 编码问题） |
| `call_ai()` | 统一入口：双后端降级 + 最多 3 次重试 |

### 关键特性

- **实时配置**：每次调用从 `core.config.config` 字典重读，用户菜单修改后即时生效
- **双后端**：openai 库优先 → httpx 直连降级，不依赖单一通道
- **UTF-8 修复**：httpx 后端手动序列化 JSON 为 UTF-8 字节，避免 Windows 下 ASCII 编码错误
- **静默模式**：`verbose=False` 时只输出 debug 信息，适合内部步骤调用

## 方式2: Brain 多级降级调用（高级）

适用于 Brain 内部，具有完整的容错机制。

### 实时读取配置

```python
def _live_config(self):
    """每次调用都实时从 config 字典重新读取，确保用户修改后即时生效。"""
    from core.config import config as _cfg
    api = _cfg.get("api", {})
    
    def _or_env(cfg_key, env_name):
        return api.get(cfg_key, "") or os.getenv(env_name, "")
    
    return {
        "api_key": _or_env("unified_api_key", "BILI_AI_API_KEY"),
        "base_url": _or_env("unified_base_url", "BILI_AI_BASE_URL"),
        "model_brain": _or_env("model_brain", "BILI_AI_MODEL_BRAIN"),
        "model_vision": _or_env("model_vision", "BILI_AI_MODEL_VISION"),
        # ... 备用提供商配置
    }
```

### 调用方式

```python
# 通过 openai 库（优先）
async def _call_ai_via_openai(self, **kwargs):
    live = self._live_config()
    api_key = kwargs.pop("_override_api_key", None) or live["api_key"]
    base_url = kwargs.pop("_override_base_url", None) or live["base_url"]
    
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=float(timeout))
    return client.chat.completions.create(**kwargs)

# 通过 httpx 直接 POST（备选）
async def _call_ai_via_httpx(self, **kwargs):
    live = self._live_config()
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json; charset=utf-8",
    }
    # [重要] 使用 content=json_bytes 而非 json=payload
    # 避免 Windows 环境下 httpx 对中文 ASCII 编码导致 UnicodeEncodeError
    body_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    async with httpx.AsyncClient(timeout=float(timeout)) as client:
        resp = await client.post(url, headers=headers, content=body_bytes)
```

### 多级降级策略

```
第1次: openai库 + 主模型
  ↓ 失败
第2次: openai库 + fallback_models.chat
  ↓ 失败
第3次: httpx直连 + 主模型
  ↓ 失败
第4次: httpx直连 + fallback_models.chat
  ↓ 失败
第5次: 切换到备用提供商(fallback_provider)
  ↓ 连续5次失败 → 60秒熔断
  ↓ 每300秒尝试恢复主API
```

## 方式3: httpx 异步调用（不依赖 openai 库）

```python
import httpx

async def call_llm(messages, model="gpt-4.1-mini"):
    from core.config import config
    api_key = config.get("api", {}).get("unified_api_key", "")
    base_url = config.get("api", {}).get("unified_base_url", "")
    
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, content=body_bytes)
        data = resp.json()
        return data["choices"][0]["message"]["content"]
```

## ⚠️ 重要注意事项

1. **中文编码**: 使用 `content=json_bytes`（先 encode 再传），不要用 `json=payload`，否则 Windows 上中文可能乱码
2. **实时配置**: 不要缓存 API key/model，每次调用时从 `config` 字典重新读取
3. **超时设置**: 默认 120 秒，视觉模型可能需要更长（180s）
4. **错误处理**: 始终包裹 try/except，失败时返回空或默认值
5. **JSON 提取**: AI 返回的 JSON 可能被 markdown 包裹，需要用正则提取 `{...}` 块
