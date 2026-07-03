from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import httpx

from .settings import DATA_DIR, MODEL_PRICES, BotSettings
from .state import BotState


class ModelError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, settings: BotSettings, state: BotState):
        self.settings = settings
        self.state = state

    def _models_for_role(self, model_role: str) -> list[str]:
        primary = self.settings.models.get(model_role) or self.settings.models.get("chat")
        fallback = self.settings.fallback_models.get(model_role) or self.settings.fallback_models.get("chat")
        seen: set[str] = set()
        models: list[str] = []
        for model in (primary, fallback):
            if model and model not in seen:
                models.append(model)
                seen.add(model)
        return models

    async def chat(self, messages: list[dict[str, Any]], model_role: str = "chat", purpose: str = "chat") -> str:
        if not self.settings.configured:
            raise ModelError("AI 接口未配置，请设置 BILI_AI_API_KEY 或 Data/config.json。")

        errors: list[str] = []
        for model in self._models_for_role(model_role):
            try:
                return await self._chat_once(model, messages, purpose)
            except ModelError as exc:
                errors.append(f"{model}: {exc}")
        raise ModelError("；".join(errors) or "没有可用模型")

    async def _chat_once(self, model: str, messages: list[dict[str, Any]], purpose: str) -> str:
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=getattr(self, "_html_timeout", 300) if purpose=="html_gen" else 90) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise ModelError(f"模型请求失败：HTTP {resp.status_code} {resp.text[:300]}")

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"模型返回格式异常：{json.dumps(data, ensure_ascii=False)[:500]}") from exc
        if isinstance(content, list):
            content = "\n".join(str(part.get("text", part)) for part in content)
        content = (content or "").strip()
        if not content:
            raise ModelError(f"模型返回空内容。model={model}")

        self.state.record_cost(model, MODEL_PRICES.get(model, 0.0), purpose)
        return content

    async def test(self, model_role: str = "chat") -> dict[str, Any]:
        models = self._models_for_role(model_role)
        if not models:
            raise ModelError(f"{model_role} 没有配置模型")
        content = await self._chat_once(
            models[0],
            [{"role": "user", "content": "请只回复 OK，用于测试模型连接。"}],
            f"model-test:{model_role}",
        )
        return {"role": model_role, "model": models[0], "reply": content}

    async def generate_image(self, prompt: str, size: str = "1024x1024") -> dict[str, Any]:
        if not self.settings.configured:
            raise ModelError("AI 接口未配置，请设置 BILI_AI_API_KEY 或 Data/config.json。")
        model = self._models_for_role("image")[0]
        url = self.settings.base_url.rstrip("/") + "/images/generations"
        headers = {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "prompt": prompt, "size": size, "n": 1}
        async with httpx.AsyncClient(timeout=getattr(self, "_html_timeout", 300) if purpose=="html_gen" else 90) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise ModelError(f"图片生成失败：HTTP {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        item = (data.get("data") or [{}])[0]
        self.state.record_cost(model, MODEL_PRICES.get(model, 0.0), "image-generation")
        if item.get("url"):
            return {"model": model, "url": item["url"], "path": ""}
        if item.get("b64_json"):
            out_dir = DATA_DIR / "generated_images"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{uuid.uuid4().hex}.png"
            path.write_bytes(base64.b64decode(item["b64_json"]))
            return {"model": model, "url": "", "path": str(path)}
        raise ModelError(f"图片返回格式异常：{json.dumps(data, ensure_ascii=False)[:500]}")

    async def embedding(self, text: str) -> list[float]:
        if not self.settings.configured:
            raise ModelError("AI 接口未配置，请设置 BILI_AI_API_KEY 或 Data/config.json。")
        model = self._models_for_role("embedding")[0]
        url = self.settings.base_url.rstrip("/") + "/embeddings"
        headers = {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "input": text[:8000]}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise ModelError(f"Embedding 请求失败：HTTP {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        try:
            vector = data["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"Embedding 返回格式异常：{json.dumps(data, ensure_ascii=False)[:500]}") from exc
        self.state.record_cost(model, MODEL_PRICES.get(model, 0.0), "embedding")
        return [float(x) for x in vector]
