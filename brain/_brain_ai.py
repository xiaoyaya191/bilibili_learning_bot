"""brain/_brain_ai.py — AgentBrain AI后端 & 多Provider mixin"""
from brain._mixin_imports import *
from utils.helpers import _mask_urls

class BrainAIMixin:
    """AI backend methods"""
    
    def _get_ai_backends(self):
        """返回按优先级排列的AI调用后端列表（当前优选排第一）。"""
        all_backends = ["openai", "httpx"]
        if self._preferred_ai_method and self._preferred_ai_method in all_backends:
            return [self._preferred_ai_method] + [m for m in all_backends if m != self._preferred_ai_method]
        return all_backends

    def _is_ai_degraded(self):
        """检查 AI 是否处于降级模式（连续失败后的冷却期，跳过所有 AI 调用）。"""
        if self._ai_degraded_until and time.time() < self._ai_degraded_until:
            remaining = int(self._ai_degraded_until - time.time())
            if not getattr(self, '_ai_degraded_logged', False):
                log(f"🔻 AI处于降级模式（跳过封面分析/兴趣判断，纯关键词匹配），剩余 {remaining}s", "WARN")
                self._ai_degraded_logged = True
            return True
        if self._ai_degraded_until and time.time() >= self._ai_degraded_until:
            self._ai_degraded_until = 0.0
            self._ai_degraded_logged = False
            log("🔺 AI降级模式已解除，恢复AI调用", "INFO")
        return False

    def _live_config(self):
        """实时读取 API 配置（绕过 import * 导致的模块级变量缓存问题）。
        每次调用都从 config 字典重新读取，确保用户通过菜单修改后即时生效。"""
        from core.config import config as _cfg
        api = _cfg.get("api", {})
        fb_prov = _cfg.get("fallback_provider", {})
        fb_models = _cfg.get("fallback_models", {})
        
        def _or_env(cfg_key, env_name):
            return api.get(cfg_key, "") or os.getenv(env_name, "")
        
        vision_api_key = api.get("vision_api_key", "")
        vision_base_url = api.get("vision_base_url", "")
        
        return {
            "api_key": _or_env("unified_api_key", "BILI_AI_API_KEY"),
            "base_url": _or_env("unified_base_url", "BILI_AI_BASE_URL"),
            "model_brain": _or_env("model_brain", "BILI_AI_MODEL_BRAIN"),
            "model_vision": _or_env("model_vision", "BILI_AI_MODEL_VISION"),
            "vision_api_key": vision_api_key if vision_api_key else _or_env("unified_api_key", "BILI_AI_API_KEY"),
            "vision_base_url": vision_base_url if vision_base_url else _or_env("unified_base_url", "BILI_AI_BASE_URL"),
            "fallback_models": fb_models,
            "fallback_model_chat": fb_models.get("chat", ""),
            "fallback_model_vision": fb_models.get("vision", ""),
            "fallback_provider_enabled": fb_prov.get("enabled", False),
            "fallback_provider_api_key": fb_prov.get("api_key", ""),
            "fallback_provider_base_url": fb_prov.get("base_url", ""),
            "fallback_provider_name": fb_prov.get("name", ""),
            "fallback_provider_models": fb_prov.get("models", {}),
        }

    async def _call_ai_via_openai(self, **kwargs):
        """通过 openai 库调用（新版 openai>=1.0.0 客户端）。"""
        timeout_val = kwargs.pop("request_timeout", kwargs.pop("timeout", 120))
        live = self._live_config()
        
        api_key = (kwargs.pop("_override_api_key", None) 
                   or kwargs.pop("_vision_api_key", None) 
                   or live["api_key"])
        base_url = (kwargs.pop("_override_base_url", None) 
                    or kwargs.pop("_vision_base_url", None) 
                    or live["base_url"])
        
        if not base_url or "://" not in str(base_url):
            if live["base_url"] and "://" in str(live["base_url"]):
                base_url = live["base_url"]
        
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=float(timeout_val))
        kwargs.pop("_vision_api_key", None)
        kwargs.pop("_vision_base_url", None)
        return client.chat.completions.create(**kwargs)

    async def _call_ai_via_httpx(self, **kwargs):
        """通过 httpx 直接 POST 到 OpenAI 兼容端点（备选方案）。
        
        [FIX] 使用 content=json_bytes 替代 json=payload，避免 httpx 在 
        Windows 某些环境下对中文内容进行 ASCII 编码导致 UnicodeEncodeError。
        """
        live = self._live_config()
        model = kwargs.get("model", live["model_brain"])
        messages = kwargs.get("messages", [])
        timeout = kwargs.get("request_timeout", 120)
        extra_body = {}
        if "max_tokens" in kwargs:
            extra_body["max_tokens"] = kwargs["max_tokens"]
        
        api_key = (kwargs.pop("_override_api_key", None) 
                   or kwargs.pop("_vision_api_key", None) 
                   or live["api_key"])
        base_url = (kwargs.pop("_override_base_url", None) 
                    or kwargs.pop("_vision_base_url", None) 
                    or live["base_url"])

        if not base_url or "://" not in str(base_url):
            if live["base_url"] and "://" in str(live["base_url"]):
                base_url = live["base_url"]
            else:
                raise RuntimeError(
                    f"API地址无效: '{base_url}'，请在配置菜单中设置有效的API地址（如 http://127.0.0.1:18767/v1）"
                )

        url = f"{base_url.rstrip('/')}/chat/completions"
        payload = {"model": model, "messages": messages}
        if extra_body:
            payload.update(extra_body)

        # [FIX] 手动序列化JSON为UTF-8字节，避免httpx内部JSON编码器
        # 在某些Windows环境下误用ASCII编码导致UnicodeEncodeError
        body_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body_bytes)),
        }

        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            resp = await client.post(url, headers=headers, content=body_bytes)
            resp.raise_for_status()
            data = resp.json()

        class _Msg:
            def __init__(self, d): self.content = d.get("content", "")
        class _Choice:
            def __init__(self, d): self.message = _Msg(d.get("message", {}))
        class _Resp:
            def __init__(self, d): self.choices = [_Choice(c) for c in d.get("choices", [])]
        return _Resp(data)

    async def _call_ai_with_retry(self, **kwargs):
        """多级降级AI调用：后端切换 → 模型降级 → 备用提供商。"""
        live = self._live_config()
        max_retries = 11
        last_error = None
        _was_cooled_down = False
        
        if self._is_ai_degraded():
            raise RuntimeError("AI处于降级模式，跳过调用")
        
        _is_vision = (
            kwargs.get("model") == live["model_vision"]
            or kwargs.get("model") == live["fallback_model_vision"]
            or "vision" in str(kwargs.get("model", "")).lower()
        )
        
        _primary_model = kwargs.get("model") or live["model_brain"]
        _fallback_model = live["fallback_model_vision"] if _is_vision else live["fallback_model_chat"]
        _models_to_try = [_primary_model]
        if _fallback_model and _fallback_model != _primary_model:
            _models_to_try.append(_fallback_model)
        _fallback_retries = 10
        _primary_retries = 11
        
        _providers = [{
            "name": "primary",
            "api_key": (live["vision_api_key"] if _is_vision and live["vision_api_key"] else live["api_key"]),
            "base_url": (live["vision_base_url"] if _is_vision and live["vision_base_url"] else live["base_url"]),
        }]
        
        if (live["fallback_provider_enabled"] 
            and live["fallback_provider_api_key"] 
            and live["fallback_provider_base_url"]):
            fb_model_key = "vision" if _is_vision else "chat"
            fb_model = live["fallback_provider_models"].get(fb_model_key, "gpt-3.5-turbo")
            _providers.append({
                "name": live["fallback_provider_name"],
                "api_key": live["fallback_provider_api_key"],
                "base_url": live["fallback_provider_base_url"],
                "models": [fb_model],
                "is_fallback": True,
            })
        
        if not _providers[0]["api_key"]:
            log("[WARN] 未配置 API Key，跳过 AI 调用（请在配置菜单设置 unified_api_key）", "WARN")
            raise RuntimeError("API Key 未配置，无法调用 AI")
        
        if self._ai_using_fallback_provider and self._ai_fallback_recheck_at:
            if time.time() >= self._ai_fallback_recheck_at:
                self._ai_using_fallback_provider = False
                log("🔍 尝试恢复主API提供商...", "INFO")
            else:
                _providers = [p for p in _providers if p.get("is_fallback")]
                if not _providers:
                    raise RuntimeError("主API不可用且无可用备用提供商")
        
        if _is_vision:
            backends = ["httpx"]
        else:
            backends = self._get_ai_backends()
        
        if self._ai_errors_consecutive >= 5:
            cooldown = 60
            log(f"[WARN] AI服务器连续{self._ai_errors_consecutive}次失败，进入{cooldown}秒熔断冷却...", "WARN")
            await asyncio.sleep(cooldown)
            self._ai_errors_consecutive = 0
            _was_cooled_down = True
        
        for pi, provider in enumerate(_providers):
            _is_fallback_provider = provider.get("is_fallback", False)
            _prov_models = provider.get("models", _models_to_try)
            _prov_api_key = provider["api_key"]
            _prov_base_url = provider["base_url"]
            
            if _is_fallback_provider and not self._ai_using_fallback_provider:
                log(f"[REFRESH] 主API不可用，切换到备用提供商: {provider['name']}", "WARN")
                self._ai_using_fallback_provider = True
            
            for mi, model in enumerate(_prov_models):
                if mi > 0:
                    log(f"[REFRESH] 模型降级: {_prov_models[0]} → {model}", "WARN")
                
                kwargs["model"] = model
                if _is_fallback_provider:
                    kwargs["_override_api_key"] = _prov_api_key
                    kwargs["_override_base_url"] = _prov_base_url
                elif _is_vision:
                    kwargs["_vision_api_key"] = _prov_api_key
                    kwargs["_vision_base_url"] = _prov_base_url
                
                _cur_retries = _fallback_retries if (_is_fallback_provider or mi > 0) else _primary_retries
                
                for attempt in range(_cur_retries):
                    for bi, backend in enumerate(backends):
                        is_last_backend = (bi == len(backends) - 1)
                        try:
                            if backend == "openai" and not _is_fallback_provider:
                                resp = await self._call_ai_via_openai(**kwargs)
                            else:
                                resp = await self._call_ai_via_httpx(**kwargs)
                            
                            self._ai_errors_consecutive = 0
                            self._ai_primary_failing = 0
                            if self._preferred_ai_method != backend:
                                self._preferred_ai_method = backend
                            if self._ai_degraded_until:
                                self._ai_degraded_until = 0.0
                                self._ai_degraded_logged = False
                                log("🔺 AI调用恢复，降级模式已解除", "INFO")
                            if self._ai_using_fallback_provider:
                                log(f"[WARN] 当前仍使用备用提供商({provider['name']})，将在稍后重试主API", "INFO")
                                self._ai_fallback_recheck_at = time.time() + 300
                            return resp
                        except Exception as e:
                            if is_last_backend:
                                last_error = e
                                err_msg = str(e).lower()
                                is_model_gone = any(kw in err_msg for kw in
                                    ['model_not_found', '无可用渠道', 'model is not found', 'unsupported model'])
                                is_overload = any(kw in err_msg for kw in 
                                    ['overload', 'not ready', 'too many', 'rate limit', '429', '503', '502', '522', 'timeout'])
                                if is_model_gone:
                                    log(f"[SKIP] 模型不可用({err_msg[:120]})，跳过重试直接切换", "WARN")
                                    break
                                if attempt < _cur_retries - 1:
                                    wait = (attempt + 1) * 3.0
                                    short_err = _mask_urls(str(e)[:120]) or type(e).__name__
                                    if is_overload:
                                        log(f"⏳ AI服务器繁忙{short_err}，第{attempt+1}次重试，等待{wait:.0f}秒...", "WARN")
                                    else:
                                        log(f"⏳ AI调用异常{short_err}，第{attempt+1}次重试，等待{wait:.0f}秒...", "WARN")
                                    await asyncio.sleep(wait)
                                    break
                                else:
                                    break
                            continue
                    else:
                        pass
                    continue
                if mi > 0 and not _is_fallback_provider:
                    log(f"[REFRESH] 备用模型{model}重试耗尽，回退到默认模型: {_primary_model}", "WARN")
                    kwargs["model"] = _primary_model
                    for attempt in range(1):
                        for bi, backend in enumerate(backends):
                            is_last_backend = (bi == len(backends) - 1)
                            try:
                                if backend == "openai":
                                    resp = await self._call_ai_via_openai(**kwargs)
                                else:
                                    resp = await self._call_ai_via_httpx(**kwargs)
                                self._ai_errors_consecutive = 0
                                self._ai_primary_failing = 0
                                if self._preferred_ai_method != backend:
                                    self._preferred_ai_method = backend
                                if self._ai_degraded_until:
                                    self._ai_degraded_until = 0.0
                                    self._ai_degraded_logged = False
                                    log("🔺 AI调用恢复，降级模式已解除", "INFO")
                                log(f"[OK] 回退到默认模型{_primary_model}成功", "INFO")
                                return resp
                            except Exception as e2:
                                if is_last_backend:
                                    last_error = e2
                                continue
                
                continue
        
        self._ai_errors_consecutive += 1
        self._ai_primary_failing += 1
        
        if self._ai_primary_failing >= 3 and not self._ai_using_fallback_provider:
            if live["fallback_provider_enabled"] and live["fallback_provider_api_key"]:
                self._ai_using_fallback_provider = True
                self._ai_fallback_recheck_at = time.time() + 600
                log(f"🔻 主API连续失败{self._ai_primary_failing}次，将在下次调用切换到备用提供商", "WARN")
        
        if _was_cooled_down:
            degrade_sec = 300
            self._ai_degraded_until = time.time() + degrade_sec
            self._ai_degraded_logged = False
            log(f"🔻 熔断恢复后仍失败，进入{degrade_sec}s AI降级模式（跳过封面分析/兴趣判断）", "WARN")
        
        raise last_error or RuntimeError("AI调用全部失败，原因未知")

    async def _psycho_ai_caller(self, **kwargs):
        """心理画像引擎的AI调用桥接，复用主Agent的多级降级/provider切换"""
        return await self._call_ai_with_retry(**kwargs)
