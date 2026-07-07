"""统一网络代理配置。"""
from __future__ import annotations

import os
from typing import Any


def get_proxy_url(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or {}
    network = cfg.get("network", {}) if isinstance(cfg, dict) else {}
    proxy_cfg = network.get("proxy", {}) if isinstance(network, dict) else {}
    if isinstance(proxy_cfg, dict) and proxy_cfg.get("enabled", False):
        url = str(proxy_cfg.get("url") or "").strip()
        if url:
            return url
    return str(os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "").strip()


def httpx_client_kwargs(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    proxy = get_proxy_url(cfg)
    return {"proxy": proxy} if proxy else {}


def requests_proxy_dict(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    proxy = get_proxy_url(cfg)
    return {"http": proxy, "https": proxy} if proxy else {}


def yt_dlp_proxy(cfg: dict[str, Any] | None = None) -> str:
    return get_proxy_url(cfg)


def apply_proxy_env(cfg: dict[str, Any] | None = None) -> str:
    proxy = get_proxy_url(cfg)
    if proxy:
        os.environ.setdefault("HTTP_PROXY", proxy)
        os.environ.setdefault("HTTPS_PROXY", proxy)
    return proxy
