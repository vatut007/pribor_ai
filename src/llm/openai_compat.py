"""OpenAI-совместимый провайдер.

Работает с любым endpoint формата OpenAI: OpenAI, DeepSeek, локальные
Ollama/vLLM/LM Studio через LLM_BASE_URL. Endpoint:
POST {LLM_BASE_URL}/chat/completions. Ретраи на 429/5xx.
"""

from __future__ import annotations

import os

import requests

from .base import (
    BaseLLMClient,
    LLMConfigError,
    LLMMessage,
    LLMResponse,
    LLMResponseError,
    run_with_retries,
    translate_errors,
)


class OpenAICompatibleClient(BaseLLMClient):
    """Клиент OpenAI-совместимого API с ретраями на 429/5xx."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("LLM_BASE_URL", "")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "")
        self.max_retries = (
            max_retries
            if max_retries is not None
            else int(os.getenv("LLM_MAX_RETRIES", "3"))
        )
        missing: list[str] = []
        if not self.base_url:
            missing.append("LLM_BASE_URL")
        if not self.model:
            missing.append("LLM_MODEL")
        if missing:
            raise LLMConfigError(
                "OpenAI-совместимый провайдер не сконфигурирован, "
                "задайте в .env: " + ", ".join(missing)
            )
        # ключ не обязателен: локальные Ollama/vLLM работают без него
        self._headers = (
            {"Authorization": f"Bearer {self.api_key}"}
            if self.api_key
            else {}
        )

    def health(self) -> bool:
        return bool(self.base_url and self.model)

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        def attempt() -> LLMResponse:
            with translate_errors(timeout):
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers,
                    timeout=timeout,
                )
                resp.raise_for_status()
                data = resp.json()
            return self._parse(data)

        return run_with_retries(attempt, max_retries=self.max_retries)

    @staticmethod
    def _parse(data: dict) -> LLMResponse:
        choices = data.get("choices") or []
        if not choices:
            raise LLMResponseError(
                "В ответе нет choices: " + str(data)[:200]
            )
        message = choices[0].get("message") or {}
        text = message.get("content") or ""
        if not text.strip():
            raise LLMResponseError(
                "Провайдер вернул пустой текст ответа"
            )
        return LLMResponse(
            text=text,
            model=data.get("model", ""),
            usage=data.get("usage"),
            raw=data,
        )
