# Web 面板 API 规范 (Flask Web Panel)

> 文件: `web_panel.py` + `web_panel.html`
> Flask 应用，端口 8800，所有 API 返回 JSON。

## 启动方式

```bash
# Windows
python web_panel.py
# 或
启动网页版.bat

# 多账号
BILI_ACCOUNT_NAME=账号2 BILI_ACCOUNT_DATA_DIR=account2/Data python web_panel.py
# 或
启动网页版_账号2.bat
```

## API 路由规范

### 基础结构

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/api/xxx', methods=['POST'])
def api_xxx():
    try:
        body = request.get_json(force=True)
        # ... 处理逻辑
        return jsonify(dict(ok=True, data=result))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500
```

### 返回格式（统一）

```json
// 成功
{"ok": true, "data": {...}, "message": "操作成功"}

// 失败
{"ok": false, "message": "错误描述"}
```

## 现有 API 路由清单

### 机器人控制
| 路由 | 方法 | 用途 |
|------|------|------|
| `/api/bot/start` | POST | 启动机器人 |
| `/api/bot/stop` | POST | 停止机器人 |
| `/api/bot/status` | GET | 机器人状态 |
| `/api/bot/log` | GET | 实时日志 (SSE) |

### 配置管理
| 路由 | 方法 | 用途 |
|------|------|------|
| `/api/config` | GET | 获取全部配置 |
| `/api/config/save` | POST | 保存配置 |
| `/api/config/export` | GET | 导出配置 |
| `/api/config/import` | POST | 导入配置 |
| `/api/config/reset` | POST | 恢复出厂设置 |

### 登录
| 路由 | 方法 | 用途 |
|------|------|------|
| `/api/login/qr` | POST | 生成扫码登录二维码 |
| `/api/login/qr/status` | GET | 查询扫码状态 |
| `/api/login/status` | GET | 当前登录状态 |

### 知识库
| 路由 | 方法 | 用途 |
|------|------|------|
| `/api/kb/stats` | GET | 知识库统计 |
| `/api/kb/list` | GET | 知识库文件列表 |
| `/api/kb/list-files` | GET | 知识库文件详情列表 |
| `/api/kb/read` | GET | 读取知识文件 |
| `/api/kb/delete` | POST | 删除知识文件 |
| `/api/kb/reclassify` | POST | 重新分类 |

### 出题考试（新增）
| 路由 | 方法 | 用途 |
|------|------|------|
| `/api/quiz/generate` | POST | 生成考题 |
| `/api/quiz/options` | GET | 获取出题选项 |

### 深入了解（新增）
| 路由 | 方法 | 用途 |
|------|------|------|
| `/api/deep-dive/run` | POST | 执行深度学习 |

### 视频
| 路由 | 方法 | 用途 |
|------|------|------|
| `/api/video/analyze` | POST | 手动分析视频 |
| `/api/video/to-html` | POST | 视频转网页 |

### 工具
| 路由 | 方法 | 用途 |
|------|------|------|
| `/api/tools/asr/highlight` | GET | ASR 高亮设置 |

## 添加新 API 路由模板

```python
# 在 web_panel.py 中添加（放在 return jsonify 之前）
@app.route('/api/your-feature/action', methods=['POST'])
def api_your_feature_action():
    try:
        body = request.get_json(force=True)
        param1 = body.get('param1', '').strip()
        
        if not param1:
            return jsonify(dict(ok=False, message='参数不能为空')), 400
        
        # 异步调用处理
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from services.your_service import your_function
            result = loop.run_until_complete(your_function(param1))
        finally:
            loop.close()
        
        return jsonify(dict(ok=True, data=result))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500
```

## 前端 JavaScript 调用模板

```javascript
// 通用 API 调用（web_panel.html 内置函数）
async function api(method, url, body) {
    const opts = { method, headers: {} };
    if (body) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    const resp = await fetch(url, opts);
    return resp.json();
}

// 使用示例
async function yourFeature() {
    var msg = document.getElementById('yourMsg');
    msg.innerHTML = '⏳ 处理中...';
    
    try {
        var r = await api('POST', '/api/your-feature/action', {
            param1: document.getElementById('yourInput').value
        });
        if (r.ok) {
            msg.innerHTML = '✅ 成功';
            // 更新 UI
        } else {
            msg.innerHTML = '❌ ' + (r.message || '失败');
        }
    } catch(e) {
        msg.innerHTML = '❌ 请求失败: ' + e.message;
    }
}
```

## 页面结构（web_panel.html）

```
┌─ 登录/密码页面 ──────────────────────┐
├─ 仪表盘 (pg-dash) ───────────────────┤
├─ 功能中心 (pg-tools) ────────────────┤
│  ├─ 视频分析                          │
│  ├─ 视频转网页                        │
│  ├─ 知识辅导                          │
│  ├─ 干货归档                          │
│  ├─ 出题考试 🆕                       │
│  └─ 深入了解 🆕                       │
├─ 配置管理 (pg-config) ───────────────┤
├─ 知识库 (pg-kb) ─────────────────────┤
├─ 日志 (pg-logs) ─────────────────────┤
├─ 登录管理 (pg-login) ────────────────┤
└─ 系统 (pg-system) ───────────────────┘
```

## ⚠️ 重要注意事项

1. **线程安全**: JSON 读写用 `utils/storage.py` 的 `JsonStore`，不要裸用 `json.load/dump`
2. **异步调用**: 在 Flask 路由中调用 async 函数，需要用 `asyncio.new_event_loop()` + `run_until_complete()`
3. **密码安全**: 使用 SHA-256 + PBKDF2 哈希，不要明文存储
4. **CSS 变量**: UI 使用 CSS 变量控制主题色（`--accent`, `--green`, `--red`, `--text`, `--text2` 等）
5. **消息内联**: 每个功能卡片用 `<span id="xxxMsg" class="msg-inline">` 显示状态消息
6. **新增功能**: 在 `rf_tools()` 函数中添加初始化逻辑，在 `pg-tools` div 中添加 UI 卡片
