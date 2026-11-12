"""Провайдер YandexGPT (Yandex Cloud Foundation Models).

Авторизация: Authorization: Api-key <YC_API_KEY> или Bearer <YC_IAM_TOKEN>;
плюс заголовок x-folder-id. Модель: gpt://<folder>/<модель>. Ретраи на
429/5xx с экспоненциальным backoff (см. base.py).
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


class YandexGPTClient(BaseLLMClient):
    """Клиент YandexGPT с авторизацией Api-key/IAM и ретраями."""

    DEFAULT_URL = (
        "https://llm.api.cloud.yandex.net"
        "/foundationModels/v1/completion"
    )
    DEFAULT_MODEL = "yandexgpt"

    def __init__(
        self,
        *,
        folder_id: str | None = None,
        api_key: str | None = None,
        iam_token: str | None = None,
        model: str | None = None,
        url: str | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.folder_id = folder_id or os.getenv("YC_FOLDER_ID", "")
        self.api_key = api_key or os.getenv("YC_API_KEY", "")
        self.iam_token = iam_token or os.getenv("YC_IAM_TOKEN", "")
        self.model = model or os.getenv("YC_MODEL", self.DEFAULT_MODEL)
        self.url = url or self.DEFAULT_URL
        self.max_retries = (
            max_retries
            if max_retries is not None
            else int(os.getenv("LLM_MAX_RETRIES", "3"))
        )
        self._validate_config()
        headers = {"x-folder-id": self.folder_id}
        if self.api_key:
            headers["Authorization"] = f"Api-key {self.api_key}"
        else:
            headers["Authorization"] = f"Bearer {self.iam_token}"
        self._headers = headers
        self.model_uri = f"gpt://{self.folder_id}/{self.model}"

    def _validate_config(self) -> None:
        missing: list[str] = []
        if not self.folder_id:
            missing.append("YC_FOLDER_ID")
        if not self.api_key and not self.iam_token:
            missing.append("YC_API_KEY (или YC_IAM_TOKEN)")
        if missing:
            raise LLMConfigError(
                "YandexGPT не сконфигурирован, задайте в .env: "
                + ", ".join(missing)
            )

    def health(self) -> bool:
        try:
            self._validate_config()
        except LLMConfigError:
            return False
        return True

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": max_tokens,
            },
            "messages": [
                {"role": m.role, "text": m.content} for m in messages
            ],
        }

        def attempt() -> LLMResponse:
            with translate_errors(timeout):
                resp = requests.post(
                    self.url,
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
        result = data.get("result") or {}
        alternatives = result.get("alternatives") or []
        if not alternatives:
            raise LLMResponseError(
                "В ответе YandexGPT нет alternatives: "
                f"{str(data)[:200]}"
            )
        message = alternatives[0].get("message") or {}
        text = message.get("text") or ""
        if not text.strip():
            raise LLMResponseError("YandexGPT вернул пустой текст")
        return LLMResponse(
            text=text,
            model=f"yandexgpt/{result.get('modelVersion', '?')}",
            usage=result.get("usage"),
            raw=data,
        )
