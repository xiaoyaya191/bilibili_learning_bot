"""Opt-in OpenAI-compatible endpoint routing, shared by account workers."""
import asyncio
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from services.token_observability import observed_post
from services.model_providers import provider_post

from core.user_data import DATA_DIR

DEFAULTS = {
    "enabled": False, "include_primary": True, "strategy": "round_robin",
    "rounds": 2, "attempt_limit": 20, "total_timeout_seconds": 300,
    "retry_delay_seconds": 1, "backoff_multiplier": 2, "max_delay_seconds": 15,
    "failure_threshold": 2, "cooldown_seconds": 60,
    "respect_retry_after": True, "retry_network_errors": True,
    "retry_statuses": [408, 429, 500, 502, 503, 504],
    "failover_statuses": [401, 402, 403, 404, 408, 429, 500, 502, 503, 504],
    "endpoints": [],
}
ENDPOINT_DEFAULTS = {
    "id": "", "name": "", "enabled": True, "base_url": "", "api_key": "",
    "model_chat": "", "model_vision": "", "supports_vision": False,
    "supports_tools": True, "weight": 1, "attempts": 1,
    "timeout_seconds": 120, "headers": {},
}


class PoolError(RuntimeError):
    pass


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("API接口池设置包含未知字段")
    result = dict(deepcopy(DEFAULTS), **value)
    for key in ("enabled", "include_primary", "respect_retry_after", "retry_network_errors"):
        if type(result[key]) is not bool:
            raise ValueError(key + " 必须是开关")
    ranges = {"rounds": (1, 10), "attempt_limit": (1, 1000), "total_timeout_seconds": (1, 3600),
              "retry_delay_seconds": (0, 60), "backoff_multiplier": (1, 10),
              "max_delay_seconds": (0, 300), "failure_threshold": (1, 100), "cooldown_seconds": (0, 86400)}
    integer_keys = {"rounds", "attempt_limit", "failure_threshold"}
    for key, (minimum, maximum) in ranges.items():
        number = result[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(key + " 超出范围")
        if key in integer_keys and type(number) is not int:
            raise ValueError(key + " 必须为整数")
    if result["strategy"] not in ("failover", "round_robin", "weighted", "random"):
        raise ValueError("请选择优先故障切换、顺序轮询、加权轮询或随机")
    for key in ("retry_statuses", "failover_statuses"):
        codes = result[key]
        if not isinstance(codes, list) or len(codes) > 100 or any(type(code) is not int or not 400 <= code <= 599 for code in codes):
            raise ValueError(key + " 必须是400-599状态码列表")
        if any(code in codes for code in (400, 422)):
            raise ValueError("400/422请求或安全拒绝不能自动重放到其他接口")
    if not isinstance(result["endpoints"], list) or len(result["endpoints"]) > 100:
        raise ValueError("最多支持100个自定义API接口")
    endpoints = []
    identifiers = set()
    for original in result["endpoints"]:
        if not isinstance(original, dict) or set(original) - set(ENDPOINT_DEFAULTS):
            raise ValueError("API接口包含未知字段")
        item = dict(deepcopy(ENDPOINT_DEFAULTS), **original)
        if not isinstance(item["id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", item["id"]) or item["id"] == "primary" or item["id"] in identifiers:
            raise ValueError("接口ID必须唯一，限字母数字_-，不能为primary")
        identifiers.add(item["id"])
        for key in ("name", "base_url", "api_key", "model_chat", "model_vision"):
            if not isinstance(item[key], str) or len(item[key]) > 2000:
                raise ValueError(key + " 内容无效")
            item[key] = item[key].strip()
        parsed = urlsplit(item["base_url"])
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("接口地址必须为HTTP(S)基础地址，不包含账号、查询串或片段")
        try:
            parsed.port
        except ValueError:
            raise ValueError("接口端口无效") from None
        for key in ("enabled", "supports_vision", "supports_tools"):
            if type(item[key]) is not bool:
                raise ValueError(key + " 必须是开关")
        for key, maximum in (("weight", 100), ("attempts", 5)):
            if type(item[key]) is not int or not 1 <= item[key] <= maximum:
                raise ValueError(key + " 超出范围")
        if type(item["timeout_seconds"]) not in (int, float) or not 1 <= item["timeout_seconds"] <= 1800:
            raise ValueError("接口超时范围1-1800秒")
        if not isinstance(item["headers"], dict) or len(item["headers"]) > 20:
            raise ValueError("自定义请求头最多20项")
        for key, header in item["headers"].items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key) or key.lower() in ("authorization", "host", "content-length", "content-type"):
                raise ValueError("请求头名称无效或为保留字段")
            if not isinstance(header, str) or len(header) > 2000 or any(ord(char) < 32 or ord(char) > 126 for char in header):
                raise ValueError("请求头值必须为可打印ASCII")
        if any(ord(char) < 32 or ord(char) > 126 for char in item["api_key"]):
            raise ValueError("API Key 必须为可打印ASCII，不能包含脱敏占位符")
        endpoints.append(item)
    result["endpoints"] = endpoints
    return result


def settings(config_data=None):
    if config_data is None:
        from core.config import load_config
        config_data = load_config()
    return validate_settings(config_data.get("api_pool", {}))


def merge_secret_endpoints(incoming, existing):
    """Resolve masked secrets by stable ID, never by list position."""
    if not isinstance(incoming, dict) or ("endpoints" in incoming and not isinstance(incoming["endpoints"], list)):
        raise ValueError("接口池及接口列表格式无效")
    result = deepcopy(incoming)
    previous = {item.get("id"): item for item in existing.get("endpoints", [])}
    for item in result.get("endpoints", []):
        if not isinstance(item, dict):
            raise ValueError("API接口必须是对象")
        old = previous.get(item.get("id"), {})
        if item.get("api_key") == "[已隐藏]":
            item["api_key"] = old.get("api_key", "")
        if item.get("headers") == "[已隐藏]":
            item["headers"] = old.get("headers", {})
    return result


def public_settings(value):
    result = deepcopy(value)
    for item in result["endpoints"]:
        item["api_key"] = "[已隐藏]" if item["api_key"] else ""
        item["headers"] = "[已隐藏]" if item["headers"] else {}
    return result


def has_images(messages):
    return any(isinstance(message.get("content"), list) and any(isinstance(part, dict) and part.get("type") in ("image_url", "input_image") for part in message["content"]) for message in messages)


def _identity(endpoint):
    data = {key: endpoint[key] for key in ("id", "base_url", "api_key", "model_chat", "model_vision", "headers")}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _retry_after(response):
    value = response.headers.get("Retry-After", "")
    try:
        number = float(value)
        return max(0, number) if math.isfinite(number) else 0
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


class EndpointPool:
    def __init__(self, data_dir=None):
        self.path = Path(data_dir or DATA_DIR) / "ai_endpoint_pool.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as database:
            database.execute("CREATE TABLE IF NOT EXISTS health (identity TEXT PRIMARY KEY, endpoint_id TEXT, failures INTEGER, until REAL, calls INTEGER, successes INTEGER, last_status TEXT, updated REAL)")
            database.execute("CREATE TABLE IF NOT EXISTS cursors (scope TEXT PRIMARY KEY, position INTEGER)")

    @contextmanager
    def connection(self):
        database = sqlite3.connect(self.path, timeout=10)
        database.row_factory = sqlite3.Row
        try:
            with database:
                yield database
        finally:
            database.close()

    def order(self, endpoints, preferences, scope):
        with self.connection() as database:
            database.execute("BEGIN IMMEDIATE")
            available = []
            for endpoint in endpoints:
                row = database.execute("SELECT until FROM health WHERE identity=?", (_identity(endpoint),)).fetchone()
                if row is None or row["until"] <= time.time():
                    available.append(endpoint)
            if not available:
                return []
            strategy = preferences["strategy"]
            if strategy == "random":
                random.shuffle(available)
            elif strategy in ("round_robin", "weighted"):
                ring = [endpoint for endpoint in available for _repeat in range(endpoint["weight"] if strategy == "weighted" else 1)]
                row = database.execute("SELECT position FROM cursors WHERE scope=?", (scope,)).fetchone()
                position = row["position"] if row else 0
                first = ring[position % len(ring)]
                database.execute("INSERT INTO cursors VALUES (?,?) ON CONFLICT(scope) DO UPDATE SET position=excluded.position", (scope, position + 1))
                offset = available.index(first)
                available = available[offset:] + available[:offset]
            return available

    def record(self, endpoint, *, success, status, preferences, retry_after=0):
        identity = _identity(endpoint)
        with self.connection() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute("SELECT * FROM health WHERE identity=?", (identity,)).fetchone()
            failures = 0 if success else (row["failures"] if row else 0) + 1
            until = 0
            if not success and (failures >= preferences["failure_threshold"] or status in (401, 402, 403, 429)):
                until = time.time() + preferences["cooldown_seconds"]
            if not success and preferences["respect_retry_after"]:
                until = max(until, time.time() + min(86400, retry_after))
            calls = (row["calls"] if row else 0) + 1
            successes = (row["successes"] if row else 0) + int(success)
            database.execute("INSERT OR REPLACE INTO health VALUES (?,?,?,?,?,?,?,?)", (identity, endpoint["id"], failures, until, calls, successes, str(status), time.time()))
            return until > time.time()

    def status(self, endpoints):
        with self.connection() as database:
            result = []
            for endpoint in endpoints:
                row = database.execute("SELECT * FROM health WHERE identity=?", (_identity(endpoint),)).fetchone()
                result.append({"id": endpoint["id"], "name": endpoint["name"], "calls": row["calls"] if row else 0, "successes": row["successes"] if row else 0, "failures": row["failures"] if row else 0, "cooldown_remaining": max(0, round(row["until"] - time.time())) if row else 0, "last_status": row["last_status"] if row else "未调用"})
            return result

    def reset(self):
        with self.connection() as database:
            database.execute("DELETE FROM health")
            database.execute("DELETE FROM cursors")


def endpoints_for(config_data, preferences, payload, vision=False):
    api = config_data.get("api", {})
    endpoints = deepcopy(preferences["endpoints"])
    if preferences["include_primary"]:
        key = (api.get("vision_api_key") if vision else "") or api.get("unified_api_key") or os.getenv("BILI_AI_API_KEY", "")
        base = (api.get("vision_base_url") if vision else "") or api.get("unified_base_url") or os.getenv("BILI_AI_BASE_URL", "")
        if base:
            endpoints.insert(0, dict(deepcopy(ENDPOINT_DEFAULTS), id="primary", name="当前主API", base_url=base, api_key=key, supports_vision=True, model_chat="", model_vision=api.get("model_vision", "")))
    return [item for item in endpoints if item["enabled"] and (not vision or item["supports_vision"]) and (not payload.get("tools") or item["supports_tools"])]


async def route(payload, *, config_data=None, timeout=120, vision=False, data_dir=None):
    if config_data is None:
        from core.config import load_config
        config_data = load_config()
    preferences = settings(config_data)
    if not preferences["enabled"]:
        raise PoolError("接口池未开启")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise PoolError("调用超时必须为正数")
    vision = vision or has_images(payload.get("messages", []))
    pool = EndpointPool(data_dir)
    endpoints = endpoints_for(config_data, preferences, payload, vision)
    scope = "vision" if vision else "tools" if payload.get("tools") else "chat"
    ordered = pool.order(endpoints, preferences, scope)
    if not ordered:
        raise PoolError("没有符合能力要求的可用API（可能全部冷却），请检查接口池")
    try:
        return await asyncio.wait_for(_route(pool, ordered, preferences, payload, timeout, vision, (config_data or {}).get("model_provider", {}).get("plugin", "openai-compatible")), timeout=preferences["total_timeout_seconds"])
    except asyncio.TimeoutError:
        raise PoolError("接口池达到总耗时上限，已停止重试") from None


async def _route(pool, ordered, preferences, payload, timeout, vision, provider="openai-compatible"):
    attempts = 0
    last_status = "未尝试"
    cooling = set()
    proxy = None
    try:
        from services.proxy_config import get_proxy_url
        proxy = get_proxy_url() or None
    except Exception:
        pass
    async with httpx.AsyncClient(proxy=proxy, follow_redirects=False) as client:
        for _round in range(preferences["rounds"]):
            for endpoint in ordered:
                if endpoint["id"] in cooling:
                    continue
                for local_attempt in range(endpoint["attempts"]):
                    if attempts >= preferences["attempt_limit"]:
                        raise PoolError("接口池达到总请求次数上限")
                    attempts += 1
                    outgoing = deepcopy(payload)
                    outgoing["model"] = endpoint["model_vision" if vision else "model_chat"] or payload.get("model", "")
                    if not outgoing["model"]:
                        raise PoolError("未配置调用模型")
                    headers = dict(endpoint["headers"], **{"Content-Type": "application/json; charset=utf-8"})
                    if endpoint["api_key"]:
                        headers["Authorization"] = "Bearer " + endpoint["api_key"]
                    parsed = urlsplit(endpoint["base_url"])
                    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                        raise PoolError("API基础地址无效，请检查当前主API或自定义接口")
                    url = endpoint["base_url"].rstrip("/")
                    if not url.endswith("/chat/completions"):
                        url += "/chat/completions"
                    retry_after = 0
                    try:
                        response = await provider_post(client, url, provider=provider, fallback=observed_post, source="api-pool", model=outgoing["model"], data_dir=pool.path.parent, endpoint=endpoint["id"], content=json.dumps(outgoing, ensure_ascii=False).encode(), headers=headers, timeout=min(float(timeout), endpoint["timeout_seconds"]))
                        status = response.status_code
                        if status >= 400:
                            retry_after = _retry_after(response)
                            raise httpx.HTTPStatusError("provider status", request=response.request, response=response)
                        if status >= 300:
                            raise PoolError("接口返回重定向，拒绝携带密钥跳转")
                        data = response.json()
                        choices = data.get("choices") if isinstance(data, dict) else None
                        message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
                        if not isinstance(message, dict) or not (str(message.get("content") or message.get("reasoning_content") or "").strip() or message.get("tool_calls")):
                            raise ValueError("empty response")
                        pool.record(endpoint, success=True, status=200, preferences=preferences)
                        return data
                    except httpx.HTTPStatusError as error:
                        status = error.response.status_code
                        retry = status in preferences["retry_statuses"] and status not in (401, 402, 403)
                        failover = status in preferences["failover_statuses"]
                    except httpx.RequestError:
                        status = "network"
                        retry = failover = preferences["retry_network_errors"]
                    except (ValueError, KeyError, TypeError):
                        status = "invalid_response"
                        retry = failover = True
                    last_status = str(status)
                    is_cooling = pool.record(endpoint, success=False, status=status, preferences=preferences, retry_after=retry_after)
                    if not failover:
                        raise PoolError(f"API {endpoint['id']} 请求被拒绝（{last_status}），未继续重放")
                    if is_cooling or status in (401, 402, 403):
                        cooling.add(endpoint["id"])
                        break
                    if not retry or local_attempt + 1 >= endpoint["attempts"]:
                        break
                    delay = min(preferences["max_delay_seconds"], preferences["retry_delay_seconds"] * preferences["backoff_multiplier"] ** local_attempt)
                    if delay:
                        await asyncio.sleep(delay)
            if _round + 1 < preferences["rounds"] and len(cooling) < len(ordered):
                delay = min(preferences["max_delay_seconds"], preferences["retry_delay_seconds"] * preferences["backoff_multiplier"] ** _round)
                if delay:
                    await asyncio.sleep(delay)
    raise PoolError(f"接口池调用失败，已尝试{attempts}次；最后状态{last_status}。请检查配置、余额或冷却状态")
