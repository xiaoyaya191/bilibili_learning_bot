"""Explicit trusted-provider registry; UI cannot load arbitrary Python paths."""
from typing import Protocol


class ModelProvider(Protocol):
    async def chat(self, client, url, payload, *, headers, timeout, source, **telemetry): ...


class OpenAICompatible:
    async def chat(self, client, url, payload, *, headers, timeout, source, **telemetry):
        import json
        from services.token_observability import observed_post
        return await observed_post(client, url, source=source, model=payload.get('model', ''),
                                   content=json.dumps(payload, ensure_ascii=False).encode(),
                                   headers=headers, timeout=timeout, **telemetry)


_PROVIDERS = {'openai-compatible': OpenAICompatible()}


def register_provider(identifier, provider):
    import re
    import inspect
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', identifier) or identifier in _PROVIDERS:
        raise ValueError('模型插件 ID 无效或已注册')
    if not inspect.iscoroutinefunction(getattr(provider, 'chat', None)):
        raise TypeError('模型插件必须实现异步 chat 接口')
    _PROVIDERS[identifier] = provider


def get_provider(identifier='openai-compatible'):
    if identifier not in _PROVIDERS:
        raise ValueError('未注册的模型插件: ' + identifier)
    return _PROVIDERS[identifier]


def provider_ids():
    return sorted(_PROVIDERS)


async def provider_post(client, url, *, provider='openai-compatible', fallback=None, **kwargs):
    if provider == 'openai-compatible':
        if fallback is None:
            from services.token_observability import observed_post
            fallback = observed_post
        return await fallback(client, url, **kwargs)
    import json
    payload = json.loads(kwargs.pop('content'))
    kwargs.pop('model', None)
    kwargs.setdefault('timeout', 120)
    kwargs['headers'] = {key: value for key, value in kwargs.get('headers', {}).items() if key.casefold() != 'content-length'}
    return await get_provider(provider).chat(client, url, payload, **kwargs)
