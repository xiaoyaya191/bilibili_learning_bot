# B站 API 调用规范 (Bilibili API Patterns)

> 项目通过 `api/client.py` (`BiliClient`) 封装了所有 B站 API 调用。
> 关键特性: WBI 签名、HTTP/2 连接复用、限速节流。

## BiliClient 初始化

```python
from api.client import BiliClient

# 创建客户端（自动从 Data/bilibili_cookies.json 加载凭证）
bili = BiliClient()
bili._load_credential()  # 加载 cookie
await bili.init_user_info()  # 初始化用户信息
```

## 核心 API 端点

### 1. 获取视频信息 (view)

```python
# 端点: GET https://api.bilibili.com/x/web-interface/view
# 参数: bvid=BV号 (需要 WBI 签名)
# 返回: {code, data: {aid, cid, title, desc, pic, duration, owner, stat}}

# 通过 BiliClient
meta = await bili.get_video_meta("BV1xx411c7mD")
# 带缓存（5分钟 TTL），避免重复请求
```

### 2. 获取字幕 (player/wbi/v2)

```python
# 端点: GET https://api.bilibili.com/x/player/wbi/v2
# 参数: bvid=BV号, cid=分P的cid (需要 WBI 签名)
# 返回: {code, data: {subtitle: {subtitles: [{subtitle_url, lan, lan_doc}]}}}

# 通过 api/subtitles.py
from api.subtitles import fetch_bilibili_subtitles
success, content, video_desc, ai_verified = await fetch_bilibili_subtitles(
    bvid="BV1xx411c7mD",
    cookies_obj=cookies,
    title="视频标题"
)
```

### 3. 搜索视频 (search/type)

```python
# 端点: GET https://api.bilibili.com/x/web-interface/search/type
# 参数: keyword=关键词, search_type=video, page=1

async with httpx.AsyncClient(http2=True) as client:
    resp = await client.get(
        "https://api.bilibili.com/x/web-interface/search/type",
        params={"keyword": "Python教程", "search_type": "video", "page": 1},
        headers={"User-Agent": "Mozilla/5.0 ...", "Referer": "https://www.bilibili.com"}
    )
    data = resp.json()
    # data["data"]["result"] -> 视频列表
```

### 4. 获取弹幕 (dm/web/seg.so)

```python
# 端点: GET https://api.bilibili.com/x/v2/dm/web/seg.so
# 参数: oid=cid, type=1, segment_index=N (需要 WBI 签名)
# 返回: protobuf 格式，需解码
```

### 5. 推荐流 (index/top/feed/rcmd)

```python
# 端点: GET https://api.bilibili.com/x/web-interface/index/top/feed/rcmd
# 需要登录 cookie
```

### 6. @我通知 (msg/at)

```python
# 端点: GET https://api.bilibili.com/x/msg/at
# 用于 standby 通知模式
```

## WBI 签名算法

```python
import hashlib, time

# 1. 从 /x/web-interface/nav 获取 img_key 和 sub_key
#    wbi_img.img_url → 提取文件名(不含扩展名) → img_key
#    wbi_img.sub_url → 提取文件名(不含扩展名) → sub_key

# 2. 计算签名
def wbi_sign(params: dict, img_key: str, sub_key: str) -> dict:
    mixin = img_key + sub_key
    wts = int(time.time())
    signed = dict(params)
    signed['wts'] = wts
    
    # 按键排序
    sorted_items = sorted(signed.items(), key=lambda x: x[0])
    query_str = '&'.join(f'{k}={v}' for k, v in sorted_items)
    
    # MD5 签名
    w_rid = hashlib.md5((query_str + mixin).encode()).hexdigest()
    signed['w_rid'] = w_rid
    return signed

# 3. 密钥缓存（1小时有效）
# 每次请求前检查缓存是否过期，过期则重新获取
```

## HTTP/2 连接复用

```python
# BiliClient 使用共享的 httpx.AsyncClient（HTTP/2）
# 避免每次请求新建 TCP+TLS 连接

async def _get_http_client(self):
    if self._http_client is None:
        self._http_client = httpx.AsyncClient(http2=True, timeout=30.0)
    return self._http_client

# 使用时
client = await self._get_http_client()
resp = await client.get(url, params=params, headers=headers)
```

## 限速节流

```python
from api.throttle import _bili_throttle

# 每次 B站 API 调用前等待
await _bili_throttle()
# 内部实现: asyncio.sleep(random.uniform(0.8, 2.5))
# 防止请求过快被 B站 限流
```

## Cookie 管理

```python
# 从文件加载
cookie_file = "Data/bilibili_cookies.json"
if os.path.exists(cookie_file):
    with open(cookie_file, 'r', encoding='utf-8') as f:
        cookies = json.load(f)
# cookies 结构: {"SESSDATA": "...", "bili_jct": "...", "buvid3": "...", "DedeUserID": "..."}

# 作为请求参数传递
resp = await client.get(url, cookies=cookies, headers=headers)
```

## ⚠️ 重要注意事项

1. **WBI 签名**: 大多数 B站 API 需要 WBI 签名，未签名的请求会返回错误
2. **buvid3 格式**: 必须是 `UUID+infoc` 格式，否则 B站 永久返回 -799
3. **Referer**: 请求 B站 API 时必须带 `Referer: https://www.bilibili.com`
4. **User-Agent**: 使用移动端 UA 可以获得更好的兼容性
5. **限速**: 连续请求间隔 1-3 秒，避免触发风控
6. **字幕降级**: 优先用 `wbi/v2`，失败后用 `player/v2` 回退
