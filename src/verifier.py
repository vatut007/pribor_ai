"""Верификатор чисел против входных данных.

Анти-галлюцинация кодом, а не «надеждой на промпт»: из ответа LLM
(seo_description и specs) извлекаются все числа с ближайшими единицами,
и каждое проверяется на присутствие во входных данных. Форматы
нормализуются: 0,03 ≡ 0.03; 0...100 ≡ 0–100 ≡ 0 - 100 (диапазон
распадается на числа-концы); гПа ≡ ГПа ≡ hPa (кириллица транслитерируется,
регистр и алиасы приводятся к канону).

Правило пропуска числа:
- число известно, если встречается во входе отдельным числовым токеном
  (вплотную к другим цифрам — не считается);
- число с единицей дополнительно требует, чтобы единица встречалась во
  входе (сразу после числа или в любом другом месте входа): «100 МПа»
  против входа «0...100 гПа» будет отклонено.

Итог — VerificationReport со счётчиками проверенных/отклонённых чисел
и списком HALLUCINATED-чисел с контекстом. Решение (перегенерация или
правка карточки) принимает генератор.

Ограничения (подробно в docs/LIMITATIONS.md): сканируются
только seo_description и значения specs; единицы
распознаются по белому списку — редкая единица вне списка проверяется
как «голое» число; одно- и двухбуквенные единицы после транслитерации
(«v», «a») почти всегда находятся во входе; отдельно стоящее «5»
совпадёт с входом «0,5».
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from .models import ProductCardOutput, ProductInput

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_UNIT_RE = re.compile(
    r"[ \t\n\r\xa0]*([°%A-Za-zА-Яа-яЁё][°%A-Za-zА-Яа-яЁё/]{0,5})"
)
_CONTEXT_RADIUS = 25

# кириллица → латиница для сравнения единиц
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "c", "т": "t", "у": "y", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
})
# каноничные формы после транслитерации: гПа ≡ hPa, Ом ≡ ohm ≡ Ω,
# гц ≡ Hz, ч ≡ h, вт ≡ W
_UNIT_ALIASES = (
    ("gpa", "hpa"),
    ("ohm", "om"),
    ("ω", "om"),
    ("gts", "hz"),
    ("kgts", "khz"),
    ("mgts", "mhz"),
    ("vt", "w"),
    ("ch", "h"),
)
# единицы, которые признаются единицами (в канонической записи); прочие
# слова после числа («от 0 до 100», «510 измеряет») единицей не считаются
_UNIT_WHITELIST = {
    "pa", "kpa", "mpa", "hpa", "bar", "mbar", "atm",  # давление
    "mm", "sm", "m", "km",  # длина
    "°c", "%",  # температура, проценты
    "v", "mv", "kv", "w", "mw", "kw",  # электричество
    "a", "ma", "ah", "mah", "om", "kom", "mom",
    "hz", "khz", "mhz", "s", "ms", "h",  # частота, время
    "kg", "g", "t", "l", "ml",  # масса, объём
}


@dataclass
class HallucinatedNumber:
    """Число из ответа LLM, которого нет во входных данных."""

    value: str  # как написано в выводе, напр. «0,001»
    unit: str  # нормализованная единица («hpa») или «»
    place: str  # "specs" | "seo_description"
    spec_name: str  # имя характеристики для place="specs", иначе «»
    context: str  # фрагмент вывода вокруг числа


@dataclass
class VerificationReport:
    """Отчёт верификации: счётчики и отклонённые числа."""

    checked: int = 0
    rejected: int = 0
    hallucinated: list[HallucinatedNumber] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.rejected == 0

    def summary(self) -> str:
        """Многострочная сводка; годится как причина для RETRY_PROMPT."""
        lines = [
            f"Проверено чисел: {self.checked}, "
            f"отклонено: {self.rejected}."
        ]
        for h in self.hallucinated:
            unit = f" {h.unit}" if h.unit else ""
            where = (
                f"specs[{h.spec_name}]"
                if h.place == "specs"
                else h.place
            )
            lines.append(
                f"- {h.value}{unit} в {where}: …{h.context}…"
            )
        return "\n".join(lines)


def _unit_view(text: str) -> str:
    """Приводит текст к каноническому виду для сравнения единиц."""
    text = text.lower().translate(_TRANSLIT)
    for src, dst in _UNIT_ALIASES:
        text = text.replace(src, dst)
    return text


def _number_view(text: str) -> str:
    """Единая десятичная точка: 0,03 → 0.03."""
    return text.replace(",", ".")


def _normalize_unit(token: str) -> str:
    token = token.strip().lower().translate(_TRANSLIT).replace(" ", "")
    for src, dst in _UNIT_ALIASES:
        token = token.replace(src, dst)
    return token


def _build_corpus(product: ProductInput) -> str:
    """Весь текст входа: число законно, только если есть где-то во входе."""
    parts = [product.name, product.manufacturer]
    if product.category:
        parts.append(product.category)
    parts += [f"{k}: {v}" for k, v in product.specs.items()]
    if product.description:
        parts.append(product.description)
    return "\n".join(parts)


def _iter_number_units(text: str) -> Iterator[tuple[re.Match[str], str]]:
    """(совпадение числа, нормализованная единица или «»).

    Единица — токен сразу после числа («0,03 гПа», «9 В», «5 %»),
    распознанный по белому списку _UNIT_WHITELIST; обычные слова рядом
    («от 0 до 100», «510 измеряет») единицей не считаются.
    """
    for m in _NUMBER_RE.finditer(text):
        um = _UNIT_RE.match(text, m.end())
        unit = _normalize_unit(um.group(1)) if um else ""
        if unit not in _UNIT_WHITELIST:
            unit = ""
        yield m, unit


def _is_known(
    number: str,
    unit: str,
    corpus_numbers: str,
    corpus_units: str,
) -> bool:
    """Число (опционально с единицей) есть во входе?"""
    num_pat = rf"(?<!\d){re.escape(_number_view(number))}(?!\d)"
    if not re.search(num_pat, corpus_numbers):
        return False
    if not unit:
        return True
    # пара «число + единица» рядом (вид входа: канон чисел и единиц)
    pair_pat = rf"{num_pat}[ \t\n\r\xa0]*{re.escape(unit)}"
    if re.search(pair_pat, corpus_units):
        return True
    # единица может стоять во входе отдельно от числа (другая строка)
    return unit in corpus_units


def verify_output(
    output: ProductCardOutput,
    product: ProductInput,
) -> VerificationReport:
    """Проверяет все числа ответа LLM на наличие во входе."""
    corpus = _build_corpus(product)
    corpus_numbers = _number_view(corpus)
    corpus_units = _unit_view(_number_view(corpus))

    sources: list[tuple[str, str, str]] = []
    for spec in output.specs:
        sources.append(("specs", spec.name, spec.value))
    sources.append(("seo_description", "", output.seo_description))

    report = VerificationReport()
    for place, spec_name, text in sources:
        for m, unit in _iter_number_units(text):
            report.checked += 1
            if _is_known(m.group(0), unit, corpus_numbers, corpus_units):
                continue
            start, end = m.span()
            context = text[
                max(0, start - _CONTEXT_RADIUS):end + _CONTEXT_RADIUS
            ]
            report.rejected += 1
            report.hallucinated.append(
                HallucinatedNumber(
                    value=m.group(0),
                    unit=unit,
                    place=place,
                    spec_name=spec_name,
                    context=context.replace("\n", " "),
                )
            )
    return report
