"""CLI генерации карточки прибора (п. 7.2 плана).

    python main.py <input.json> [--format json|md] [--output <path>]
        [--provider yandexgpt|openai_compatible]

Читает входной JSON, валидирует, генерирует карточку через LLM,
печатает результат в stdout (или пишет в --output). Сводка верификации
и недостающие поля — в stderr (п. 6.4.4: прозрачность).

Коды выхода: 0 — успех; 1 — входной файл не читается; 2 — некорректный
вход; 3 — LLM дважды вернул непригодный ответ; 4 — ошибка LLM
(сеть, лимиты, конфигурация).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.generator import GenerationError, generate_card
from src.llm.base import LLMError
from src.output import to_json, to_markdown
from src.validator import InvalidInputError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Черновик карточки контрольно-измерительного прибора "
            "через LLM (YandexGPT / OpenAI-совместимый)."
        ),
    )
    parser.add_argument(
        "input",
        type=Path,
        help="путь к входному JSON товара (ProductInput)",
    )
    parser.add_argument(
        "--format",
        choices=("json", "md"),
        default="json",
        help="формат вывода (по умолчанию json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="файл результата (по умолчанию stdout)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="переопределение LLM_PROVIDER: yandexgpt | openai_compatible",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw = args.input.read_text(encoding="utf-8")
    except OSError as e:
        print(
            f"Не удалось прочитать {args.input}: {e}", file=sys.stderr
        )
        return 1
    try:
        result = generate_card(raw, provider=args.provider)
    except InvalidInputError as e:
        # сообщение валидатора уже начинается с «Некорректный вход: …»
        print(str(e), file=sys.stderr)
        return 2
    except GenerationError as e:
        print(f"Генерация не удалась: {e}", file=sys.stderr)
        return 3
    except LLMError as e:
        print(f"Ошибка LLM: {e}", file=sys.stderr)
        return 4

    text = (
        to_json(result.card)
        if args.format == "json"
        else to_markdown(result.card)
    )
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
        print(f"Карточка записана: {args.output}", file=sys.stderr)
    else:
        print(text)
    print(result.verification.summary(), file=sys.stderr)
    if result.missing_fields:
        print(
            "Нет во входе: " + ", ".join(result.missing_fields),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
