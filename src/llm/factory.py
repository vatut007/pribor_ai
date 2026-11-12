"""Фабрика LLM-провайдеров: выбор по LLM_PROVIDER
и общие параметры генерации из env.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from .base import BaseLLMClient, LLMConfigError
from .openai_compat import OpenAICompatibleClient
from .yandex_gpt import YandexGPTClient

PROVIDERS = ("yandexgpt", "openai_compatible")


def get_client(provider: str | None = None) -> BaseLLMClient:
    """Инстанцирует провайдера по аргументу или env LLM_PROVIDER.

    load_dotenv() безопасен при повторных вызовах: уже установленные
    переменные окружения не перезаписываются.
    """
    load_dotenv()
    name = (provider or os.getenv("LLM_PROVIDER") or "yandexgpt")
    name = name.strip().lower()
    if name == "yandexgpt":
        return YandexGPTClient()
    if name == "openai_compatible":
        return OpenAICompatibleClient()
    raise LLMConfigError(
        f"Неизвестный LLM_PROVIDER={name!r}; "
        f"допустимы: {', '.join(PROVIDERS)}"
    )


def chat_params() -> dict[str, Any]:
    """Общие параметры генерации из env с разумными дефолтами."""
    return {
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.2")),
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "2000")),
        "timeout": float(os.getenv("LLM_TIMEOUT", "60")),
    }
