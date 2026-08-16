# 网络搜索 API (Web Search)

> 文件: `knowledge/web_search.py`
> 多引擎联网搜索 + AI 知识验证。

## web_search() — 多引擎搜索

```python
from knowledge.web_search import web_search

# 搜索（返回标题+摘要+URL列表）
results = await web_search("向量数据库", limit=8)
# 返回: [
#   {"title": "向量数据库介绍", "snippet": "...", "url": "https://..."},
#   ...
# ]

# 非异步调用方式
import asyncio
loop = asyncio.new_event_loop()
results = loop.run_until_complete(web_search("Python教程", limit=5))
loop.close()
```

### 搜索引擎降级顺序

```
1. Bing (www.bing.com/search)
   ↓ 失败/无结果
2. 搜狗 (m.sogou.com/web/sl)
   ↓ 失败/无结果
3. DuckDuckGo (lite.duckduckgo.com/lite)
   ↓ 失败/无结果
4. Wikipedia (en.wikipedia.org/w/api.php)
```

### 搜索结果格式

```python
[
    {
        "title": "结果标题（最多120字）",
        "snippet": "摘要文本（最多300字）",
        "url": "https://原始链接"
    },
    ...
]
```

## verify_knowledge_with_ai() — AI 知识验证

```python
from knowledge.web_search import verify_knowledge_with_ai

# 验证知识文件内容的真实性
result = await verify_knowledge_with_ai(
    knowledge_content="知识文件的完整Markdown内容",
    video_title="视频标题",
    web_results=search_results  # 可选，联网搜索结果
)
# 返回: {
#   "overall_reliable": True/False,
#   "overall_score": 0.85,        # 0-1 可靠性评分
#   "issues": [{"claim": "...", "verdict": "存疑/错误/过时"}],
#   "supplements": ["补充信息1", ...],
#   "recommend_rewrite": False,
#   "rewrite_reason": "",
#   "corrected_content": None
# }
```

## backup_and_rewrite_knowledge() — 备份并重写知识文件

```python
from knowledge.web_search import backup_and_rewrite_knowledge

# 备份原文件（添加"备份_"前缀），写入修正内容
backup_and_rewrite_knowledge(
    file_path="/path/to/knowledge.md",
    corrected_content="修正后的Markdown",
    verify_result=verify_result
)
```

## 在服务中复用搜索

```python
# 方式1: 直接导入（异步）
from knowledge.web_search import web_search

async def my_search_function():
    results = await web_search("关键词", limit=5)
    return results

# 方式2: 同步包装
def my_sync_search(query, limit=5):
    import asyncio
    from knowledge.web_search import web_search
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(web_search(query, limit))
    finally:
        loop.close()
```

## ⚠️ 重要注意事项

1. **超时**: 每次搜索请求 timeout=12s，Wikipedia 15s
2. **引擎降级**: 一个引擎失败自动尝试下一个，不会因为某个搜索引擎挂了而整体失败
3. **HTML 解析**: 各引擎返回的 HTML 结构不同，分别用正则解析
4. **User-Agent**: 必须设置移动端 UA，否则部分引擎可能拒绝服务
5. **不要在循环中频繁调用**: 每次搜索都是网络请求，注意节流
