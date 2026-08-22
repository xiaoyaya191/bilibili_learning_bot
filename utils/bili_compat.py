"""utils/bili_compat.py — B 站请求编码兼容补丁（brotli 全链路防护）。

问题链条：
1. aiohttp 在 Brotli 可导入时会主动声明 `Accept-Encoding: gzip, deflate, br`；
2. B 站 CDN 对部分接口（推荐流 / @我检查 / 评论区）可能无视声明直接返回 br 压缩响应；
3. 部分运行环境里 brotli 扩展（.pyd）与 Python 版本不匹配（如 cp311 vs 3.13）导致
   `HAS_BROTLI=False`，aiohttp 解不开 br 响应体，抛出
   "Can not decode content-encoding: brotli (br)"，上层日志显示为 400/获取推荐失败。

修复策略（三层防护，全部幂等）：
A. bilibili_api 全局 HEADERS 注入 `Accept-Encoding: gzip, deflate`（不主动要 br）；
B. aiohttp 默认 Accept-Encoding 生成函数去掉 br/zstd；
C. 兜底：aiohttp `DeflateBuffer` 遇到 br 且 Brotli 不可用时不再抛异常，
   退化为原样字节透传（不解码也不崩，业务层可正常拿到状态码并重试）。
"""

_patched = False

_SAFE_ACCEPT_ENCODING = "gzip, deflate"


def _patch_bili_api_headers_dict() -> bool:
    """注入 Accept-Encoding: gzip, deflate 到 bilibili_api 全局请求头。"""
    try:
        from bilibili_api.utils import network as _bili_network
        headers = getattr(_bili_network, "HEADERS", None)
        if isinstance(headers, dict):
            headers["Accept-Encoding"] = _SAFE_ACCEPT_ENCODING
            return True
    except Exception:  # bilibili_api 未安装或内部结构变化：不影响其他功能
        pass
    return False


def _patch_aiohttp_default_encoding() -> bool:
    """aiohttp 默认 Accept-Encoding 永远不带 br/zstd。"""
    try:
        from aiohttp import client_reqrep as _reqrep

        if getattr(_reqrep, "_bili_safe_encoding_patched", False):
            return True

        def _safe_accept_encoding() -> str:
            return _SAFE_ACCEPT_ENCODING

        _reqrep._gen_default_accept_encoding = _safe_accept_encoding
        _reqrep._bili_safe_encoding_patched = True
        return True
    except Exception:
        return False


def _patch_aiohttp_br_fallback() -> bool:
    """Brotli 不可用时，br 响应退化为原样透传而不是抛异常。"""
    try:
        from aiohttp import http_parser as _parser

        if getattr(_parser, "_bili_br_fallback_patched", False):
            return True

        _orig_init = _parser.DeflateBuffer.__init__

        def _tolerant_init(self, out, encoding, max_decompress_size=16 * 1024 * 1024):
            if isinstance(encoding, str) and encoding.lower() == "br":
                try:
                    from aiohttp.compression_utils import HAS_BROTLI

                    if not HAS_BROTLI:
                        # 无 Brotli 解码器：原样透传，避免整个请求链路崩溃
                        encoding = None
                except Exception:
                    encoding = None
            return _orig_init(
                self, out, encoding, max_decompress_size=max_decompress_size
            )

        _parser.DeflateBuffer.__init__ = _tolerant_init
        _parser._bili_br_fallback_patched = True
        return True
    except Exception:
        return False


def patch_bili_api_headers() -> bool:
    """应用全部编码兼容补丁（幂等，可重复调用）。"""
    global _patched
    if _patched:
        return True
    ok = _patch_bili_api_headers_dict()
    _patch_aiohttp_default_encoding()
    _patch_aiohttp_br_fallback()
    _patched = True
    return ok
