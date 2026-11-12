"""Генератор карточки товара — оркестрация пайплайна.

Шаги: validate → prompt → LLM → parse (один ретрай) → verify → output.

Политика повторов. На невалидный ответ LLM (не JSON, не по схеме,
обрезан) отправляется ровно ОДИН повторный запрос с уточнением
RETRY_PROMPT. Выдуманные числа в seo_description тоже ведут
к одному повторному запросу («повторная генерация»); оба
повтора делят общий бюджет из двух попыток. Выдуманные числа в
значениях specs перегенерации не требуют: значение заменяется на
«данных нет», имя характеристики добавляется в missing_fields
(«удаление»).

Инвариант: карточка в GenerationResult всегда проходит верификатор
(verification.ok); иначе бросается GenerationError.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from .llm.base import BaseLLMClient, LLMMessage
from .llm.factory import chat_params, get_client
from .models import ProductCardOutput, SpecItem
from .prompts import RETRY_PROMPT, SYSTEM_PROMPT, build_user_prompt
from .validator import validate_input
from .verifier import VerificationReport, verify_output


class GenerationError(Exception):
    """LLM дважды вернул непригодный ответ: битый JSON, схема не
    сходится или в seo_description остались выдуманные числа."""


@dataclass
class GenerationResult:
    """Итог генерации: карточка + прозрачность процесса."""

    card: ProductCardOutput
    verification: VerificationReport
    missing_fields: list[str] = field(default_factory=list)  # от валидатора
    llm_calls: int = 0  # фактическое число запросов к LLM


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_text(text: str) -> str:
    """Вырезает JSON из ответа модели (модель может обернуть его в ```)."""
    stripped = text.strip()
    fenced = _JSON_BLOCK_RE.search(stripped)
    if fenced:
        return fenced.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start:end + 1]
    return stripped


def _schema_reason(error: ValidationError) -> str:
    """Краткое перечисление первых ошибок схемы — для RETRY_PROMPT."""
    parts = []
    for err in error.errors()[:3]:
        loc = ".".join(str(item) for item in err["loc"])
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def _parse_card(text: str) -> tuple[ProductCardOutput | None, str]:
    """(карточка, «») при успехе, иначе (None, причина для ретрая)."""
    raw = _extract_json_text(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        reason = (
            f"ответ не является валидным JSON: {e.msg} (позиция {e.pos})"
        )
        return None, reason
    try:
        return ProductCardOutput.model_validate(data), ""
    except ValidationError as e:
        reason = (
            f"JSON не соответствует схеме карточки: {_schema_reason(e)}"
        )
        return None, reason


def _replace_hallucinated_specs(
    card: ProductCardOutput,
    names: set[str],
) -> ProductCardOutput:
    """Выдуманные числа в specs → «данных нет» (удаление)."""
    if not names:
        return card
    specs = [
        spec
        if spec.name not in names
        else SpecItem(name=spec.name, value="данных нет")
        for spec in card.specs
    ]
    missing = list(dict.fromkeys([*card.missing_fields, *names]))
    return card.model_copy(
        update={"specs": specs, "missing_fields": missing}
    )


def generate_card(
    raw: str | dict,
    *,
    provider: str | None = None,
    client: BaseLLMClient | None = None,
) -> GenerationResult:
    """Полный пайплайн: вход → валидация → промпт → LLM → парсинг
    с одним ретраем → верификация → карточка.

    Наверх уходят доменные исключения: InvalidInputError (вход),
    LLMError* (сеть/провайдер), GenerationError (дважды непригодный
    ответ). client — для тестов; provider — переопределение
    LLM_PROVIDER для CLI/API.
    """
    validation = validate_input(raw)
    product = validation.product
    llm = client if client is not None else get_client(provider)
    params = chat_params()
    messages = [
        LLMMessage("system", SYSTEM_PROMPT),
        LLMMessage(
            "user",
            build_user_prompt(product, validation.missing_fields),
        ),
    ]

    llm_calls = 0
    last_reason = ""
    for _attempt in (1, 2):
        response = llm.chat(messages, **params)
        llm_calls += 1
        card, reason = _parse_card(response.text)
        if card is None:
            last_reason = reason
        else:
            report = verify_output(card, product)
            spec_bad = {
                h.spec_name
                for h in report.hallucinated
                if h.place == "specs"
            }
            desc_bad = [
                h
                for h in report.hallucinated
                if h.place == "seo_description"
            ]
            if not desc_bad:
                card = _replace_hallucinated_specs(card, spec_bad)
                report = verify_output(card, product)
                return GenerationResult(
                    card=card,
                    verification=report,
                    missing_fields=validation.missing_fields,
                    llm_calls=llm_calls,
                )
            numbers = "; ".join(
                f"{h.value} {h.unit}".strip() for h in desc_bad
            )
            last_reason = (
                "в seo_description есть числа, которых нет во входных "
                f"данных: {numbers}"
            )
        messages = messages + [
            LLMMessage("assistant", response.text),
            LLMMessage("user", RETRY_PROMPT.format(reason=last_reason)),
        ]
    raise GenerationError(
        "LLM дважды вернул непригодный ответ. Последняя причина: "
        f"{last_reason}"
    )
