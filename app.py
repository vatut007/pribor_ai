"""FastAPI: POST /generate (JSON) + GET / (HTML-форма).

Запуск: uvicorn app:app --reload (из корня проекта).

Ошибки: 422 — некорректный вход; 502 — LLM ответил непригодно
(в т.ч. дважды битый ответ); 503 — LLM недоступен (таймаут, лимит 429,
не сконфигурирован). Сообщения — понятные, на русском.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from src.generator import GenerationError, generate_card
from src.llm.base import (
    LLMConfigError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from src.models import ProductCardOutput
from src.output import to_markdown
from src.validator import InvalidInputError

app = FastAPI(
    title="Генератор карточек приборов",
    description=(
        "Черновик карточки контрольно-измерительного прибора: "
        "входные данные + LLM (YandexGPT / OpenAI-совместимый)."
    ),
)

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="form.html")


@app.post("/generate", response_model=ProductCardOutput)
async def generate(
    request: Request,
    format: str = Query(default="json", pattern="^(json|md)$"),
) -> object:
    """Генерирует карточку из JSON товара.

    format=json (по умолчанию) — ProductCardOutput; format=md —
    Markdown-черновик (text/markdown). Возвращаемая карточка всегда
    прошла верификатор чисел.
    """
    try:
        raw = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=422, detail="Некорректный JSON в теле запроса"
        )
    try:
        result = generate_card(raw)
    except InvalidInputError as e:
        # сообщение валидатора уже начинается с «Некорректный вход: …»
        raise HTTPException(status_code=422, detail=str(e))
    except GenerationError as e:
        raise HTTPException(
            status_code=502, detail=f"Генерация не удалась: {e}"
        )
    except LLMConfigError as e:
        raise HTTPException(
            status_code=503,
            detail=f"LLM не сконфигурирован: {e}",
        )
    except (LLMTimeoutError, LLMRateLimitError) as e:
        raise HTTPException(
            status_code=503, detail=f"LLM временно недоступен: {e}"
        )
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"Ошибка LLM: {e}")

    if format == "md":
        return PlainTextResponse(
            to_markdown(result.card),
            media_type="text/markdown; charset=utf-8",
        )
    return result.card
