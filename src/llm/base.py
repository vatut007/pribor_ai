"""База LLM-слоя.

LLMMessage / LLMResponse — структуры данных, общие для всех провайдеров.
BaseLLMClient — абстракция: чтобы добавить своего провайдера, достаточно
унаследоваться и реализовать chat() и health().

Единая обёртка translate_errors() превращает любые ошибки HTTP-запроса в
доменные исключения, с которыми работает остальной код:
- LLMTimeoutError   — таймаут или нет соединения;
- LLMRateLimitError — HTTP 429, исчерпан лимит запросов;
- LLMResponseError  — провайдер ответил, но ответ невалиден (HTTP 4xx/5xx,
  не-JSON тело);
- LLMError          — базовый класс и всё прочее (прочие сетевые сбои).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import requests

ALLOWED_ROLES = ("system", "user", "assistant")


class LLMError(Exception):
    """Базовая ошибка LLM-слоя."""


class LLMTimeoutError(LLMError):
    """Провайдер не ответил за отведённое время
    или соединение не установлено."""


class LLMRateLimitError(LLMError):
    """Превышен лимит запросов к провайдеру (HTTP 429)."""


class LLMResponseError(LLMError):
    """Провайдер ответил невалидно: HTTP-ошибка или не-JSON тело."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMConfigError(LLMError):
    """Провайдер не сконфигурирован: нет обязательных
    переменных окружения."""


@dataclass
class LLMMessage:
    """Одно сообщение в диалоге с моделью."""

    role: str  # "system" | "user" | "assistant"
    content: str

    def __post_init__(self) -> None:
        if self.role not in ALLOWED_ROLES:
            allowed = ", ".join(ALLOWED_ROLES)
            raise ValueError(
                f"Недопустимая роль {self.role!r}; допустимы: {allowed}"
            )


@dataclass
class LLMResponse:
    """Ответ провайдера: текст плюс метаданные для отладки."""

    text: str
    model: str = ""
    usage: dict[str, Any] | None = None  # токены и пр., как вернул API
    raw: Any = None  # полное тело ответа API


class BaseLLMClient(ABC):
    """Абстрактный клиент LLM.

    Наследник реализует chat() под HTTP API конкретного провайдера и
    health() — лёгкую проверку конфигурации без реального запроса.
    """

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        """Отправляет сообщения провайдеру и возвращает ответ."""

    @abstractmethod
    def health(self) -> bool:
        """True, если обязательные env-переменные провайдера заполнены."""


@contextmanager
def translate_errors(timeout: float) -> Iterator[None]:
    """Единая обёртка ошибок HTTP-вызова в доменные исключения.

    Провайдеры оборачивают сюда запрос и raise_for_status(). Порядок
    except-веток важен: JSONDecodeError — подкласс RequestException.
    """
    try:
        yield
    except requests.Timeout as e:
        raise LLMTimeoutError(f"LLM не ответил за {timeout:.0f} с") from e
    except requests.ConnectionError as e:
        raise LLMTimeoutError(f"Не удалось подключиться к LLM: {e}") from e
    except requests.JSONDecodeError as e:
        raise LLMResponseError(f"LLM вернул не-JSON ответ: {e}") from e
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 429:
            raise LLMRateLimitError(
                "Превышен лимит запросов к LLM (HTTP 429)"
            ) from e
        raise LLMResponseError(
            f"LLM вернул HTTP-ошибку {status}: {e}", status_code=status
        ) from e
    except requests.RequestException as e:
        raise LLMError(f"Ошибка сети при обращении к LLM: {e}") from e


def run_with_retries(
    attempt: Callable[[], LLMResponse],
    *,
    max_retries: int,
    on_retry: Callable[[int, LLMError], None] | None = None,
) -> LLMResponse:
    """Ретраи с экспоненциальным backoff на 429/5xx.

    attempt() должен бросать доменные исключения (см. translate_errors).
    Повторяются только LLMRateLimitError и LLMResponseError со статусом
    5xx; остальные ошибки (в т.ч. таймауты) выходят сразу. Задержки —
    1, 2, 4 с (растут вдвое, максимум 8 с).
    """
    for attempt_no in range(1, max_retries + 1):
        try:
            return attempt()
        except (LLMRateLimitError, LLMResponseError) as e:
            retriable = isinstance(e, LLMRateLimitError) or (
                isinstance(e, LLMResponseError)
                and e.status_code is not None
                and e.status_code >= 500
            )
            if not retriable or attempt_no == max_retries:
                raise
            if on_retry is not None:
                on_retry(attempt_no, e)
            time.sleep(min(2 ** (attempt_no - 1), 8))
    raise AssertionError("run_with_retries: недостижимая ветка")
