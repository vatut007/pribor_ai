"""Валидатор входного JSON.

Разбирает JSON с понятной ошибкой и позицией, проверяет структуру через
pydantic-модель ProductInput и готовит отчёт missing_fields: какие
«ожидаемые характеристики» не удалось найти во входных данных — их модель
обязана вывести в карточке как «данных нет».
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError as PydanticValidationError

from .models import ProductInput


class InvalidInputError(ValueError):
    """Некорректный вход: битый JSON, неверная структура,
    типы или пустые поля."""


@dataclass
class ValidationResult:
    """Результат валидации: нормализованный вход + отчёт о пропусках."""

    product: ProductInput
    missing_fields: list[str] = field(default_factory=list)


# «Ожидаемые характеристики»: если ни одно из ключевых слов не
# встречается среди ключей specs — характеристика считается отсутствующей.
EXPECTED_CHARACTERISTICS: list[tuple[str, tuple[str, ...]]] = [
    ("диапазон измерений", ("диапазон",)),
    ("класс точности / погрешность", ("класс точности", "погрешность")),
    ("питание", ("питание",)),
    ("степень защиты / корпус", ("степен", "защит", "корпус", "ip")),
    ("интерфейсы", ("интерфейс", "связь", "коммуникац", "протокол", "выход")),
    ("габариты", ("габарит", "размер")),
]

# Русские формулировки частых ошибок pydantic (для понятных сообщений)
_TYPE_RU = {
    "missing": "обязательное поле отсутствует",
    "string_type": "ожидалась строка",
    "string_too_short": "пустое значение",
    "dict_type": "ожидался объект {ключ: значение}",
    "list_type": "ожидался список",
}


def parse_json(raw: str) -> dict:
    """Разбирает JSON-текст; при ошибке — InvalidInputError с позицией."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise InvalidInputError(
            f"Некорректный JSON на позиции {e.pos} "
            f"(строка {e.lineno}, столбец {e.colno}): {e.msg}"
        ) from e
    if not isinstance(data, dict):
        kind = type(data).__name__
        raise InvalidInputError(
            f"Ожидался JSON-объект с полями name/manufacturer/specs, "
            f"получен {kind}"
        )
    return data


def _format_pydantic_error(e: PydanticValidationError) -> str:
    """Сводит ошибки pydantic в одну читаемую строку."""
    parts: list[str] = []
    for err in e.errors():
        path = ".".join(str(p) for p in err["loc"]) or "<корень>"
        reason = _TYPE_RU.get(err["type"], err["msg"])
        parts.append(f"'{path}': {reason} [{err['type']}]")
    return "; ".join(parts)


def _collect_missing_fields(specs: dict[str, str]) -> list[str]:
    """Ожидаемые характеристики без данных
    + заявленные ключи с пустым значением."""
    keys_lower = [k.lower() for k in specs]
    missing: list[str] = []
    for label, keywords in EXPECTED_CHARACTERISTICS:
        if not any(kw in key for kw in keywords for key in keys_lower):
            missing.append(label)
    for key, value in specs.items():
        if not value and key not in missing:
            missing.append(key)
    return missing


def validate_input(raw: str | dict) -> ValidationResult:
    """Валидирует вход: JSON-строка или уже разобранный dict.

    Нормализует пробелы в полях и ключах specs. Бросает InvalidInputError
    с понятным сообщением при любой проблеме входа.
    """
    if isinstance(raw, str):
        data = parse_json(raw)
    elif isinstance(raw, dict):
        data = raw
    else:
        raise InvalidInputError(
            f"Ожидали JSON-строку или объект, получен {type(raw).__name__}"
        )

    try:
        product = ProductInput.model_validate(data)
    except PydanticValidationError as e:
        raise InvalidInputError(
            f"Некорректный вход: {_format_pydantic_error(e)}"
        ) from e

    # пустые (в т.ч. из одних пробелов) обязательные поля — тоже «нет данных»
    empty = [
        f
        for f in ("name", "manufacturer")
        if not getattr(product, f).strip()
    ]
    if empty:
        raise InvalidInputError(
            f"Пустые обязательные поля: {', '.join(empty)}"
        )

    product = product.model_copy(
        update={
            "name": product.name.strip(),
            "manufacturer": product.manufacturer.strip(),
            "category": (
                product.category.strip()
                if product.category
                else product.category
            ),
            "description": product.description.strip(),
            "specs": {k.strip(): v.strip() for k, v in product.specs.items()},
        }
    )

    return ValidationResult(
        product=product,
        missing_fields=_collect_missing_fields(product.specs),
    )
