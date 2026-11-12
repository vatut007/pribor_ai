"""Рендер карточки: JSON-строка и Markdown (п. 4: output.py).

Markdown — «человеческий» черновик для менеджера: заголовок,
SEO-описание, таблица характеристик (символ «|» в значениях
экранируется), поисковые запросы, коммерческий блок и список
отсутствующих данных.
"""

from __future__ import annotations

from .models import ProductCardOutput


def to_json(card: ProductCardOutput) -> str:
    """Карточка в JSON (UTF-8, кириллица без \\u-эскейпов)."""
    return card.model_dump_json(indent=2)


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|")


def to_markdown(card: ProductCardOutput) -> str:
    """Карточка в Markdown для вставки в админку или документ."""
    parts = [
        f"# {card.seo_title}",
        "",
        "## SEO-описание",
        "",
        card.seo_description,
        "",
        "## Характеристики",
        "",
        "| Характеристика | Значение |",
        "| --- | --- |",
    ]
    for spec in card.specs:
        parts.append(
            f"| {_escape_table(spec.name)} | {_escape_table(spec.value)} |"
        )
    parts += [
        "",
        "## Поисковые запросы",
        "",
    ]
    parts += [f"- {query}" for query in card.search_queries]
    parts += [
        "",
        "## Коммерческий блок",
        "",
        card.commercial_block,
    ]
    if card.missing_fields:
        parts += [
            "",
            "## Отсутствующие данные («данных нет»)",
            "",
        ]
        parts += [f"- {name}" for name in card.missing_fields]
    return "\n".join(parts)
