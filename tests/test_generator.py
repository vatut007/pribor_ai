"""Тесты генератора: один ретрай на невалидный ответ,
перегенерация при выдуманных числах в описании, «данных нет» в specs."""

import json

import pytest

from src.generator import GenerationError, generate_card
from src.llm.base import BaseLLMClient, LLMMessage, LLMResponse
from src.validator import InvalidInputError

INPUT = {
    "name": "Манометр дифференциальный testo 510",
    "manufacturer": "testo",
    "category": "Манометры",
    "specs": {
        "Диапазон измерений": "0...100 гПа",
        "Погрешность": "±0,03 гПа",
        "Питание": "батарея 9 В, тип 6F22",
    },
    "description": "Прибор для измерения перепада давления.",
}

MISSING_FROM_INPUT = ["степень защиты / корпус", "интерфейсы", "габариты"]


def _pad(text: str) -> str:
    sentence = "Прибор применяется при пусконаладке и сервисных работах. "
    while len(text) < 810:
        text += sentence
    return text


def _card_payload(**overrides) -> dict:
    payload = {
        "seo_title": "Манометр testo 510 — измерение перепада давления",
        "seo_description": _pad(
            "Диапазон измерений от 0 до 100 гПа, погрешность ±0,03 гПа, "
            "питание — батарея 9 В, тип 6F22."
        ),
        "specs": [
            {"name": "Диапазон измерений", "value": "0...100 гПа"},
            {"name": "Погрешность", "value": "±0,03 гПа"},
            {"name": "Питание", "value": "батарея 9 В, тип 6F22"},
            {"name": "Интерфейсы", "value": "данных нет"},
        ],
        "search_queries": [
            "купить манометр testo 510",
            "манометр перепада давления",
            "дифференциальный манометр testo",
        ],
        "commercial_block": (
            "Подойдёт монтажникам ОВиК и сервисным инженерам для "
            "пусконаладки, поверки и поиска утечек в системах вентиляции."
        ),
        "missing_fields": MISSING_FROM_INPUT,
    }
    payload.update(overrides)
    return payload


class FakeLLMClient(BaseLLMClient):
    """Возвращает заготовленные ответы по очереди и записывает вызовы."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[LLMMessage]] = []

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("FakeLLMClient: заготовки кончились")
        return LLMResponse(text=self._responses.pop(0), model="fake")

    def health(self) -> bool:
        return True


def test_success_first_attempt() -> None:
    client = FakeLLMClient(
        [json.dumps(_card_payload(), ensure_ascii=False)]
    )
    result = generate_card(INPUT, client=client)
    assert result.llm_calls == 1
    assert result.verification.ok
    assert result.card.specs[0].value == "0...100 гПа"
    assert result.missing_fields == MISSING_FROM_INPUT
    user_prompt = client.calls[0][1].content
    assert "ОТСУТСТВУЮЩИЕ ХАРАКТЕРИСТИКИ" in user_prompt


def test_fenced_json_is_parsed() -> None:
    payload = json.dumps(_card_payload(), ensure_ascii=False)
    client = FakeLLMClient([f"Вот карточка:\n```json\n{payload}\n```"])
    result = generate_card(INPUT, client=client)
    assert result.llm_calls == 1
    assert result.card.seo_title.startswith("Манометр")


def test_one_retry_on_broken_answer() -> None:
    client = FakeLLMClient([
        "К сожалению, карточка не поместилась в ответ.",
        json.dumps(_card_payload(), ensure_ascii=False),
    ])
    result = generate_card(INPUT, client=client)
    assert result.llm_calls == 2
    assert "не принят" in client.calls[1][-1].content


def test_two_broken_answers_raise() -> None:
    client = FakeLLMClient(["нет и не будет", "всё ещё нет"])
    with pytest.raises(GenerationError) as exc_info:
        generate_card(INPUT, client=client)
    assert "дважды" in str(exc_info.value)
    assert len(client.calls) == 2


def test_hallucinated_description_triggers_retry() -> None:
    bad = _card_payload(
        seo_description=_pad("Точность 0,001 гПа — сверхточно."),
    )
    client = FakeLLMClient([
        json.dumps(bad, ensure_ascii=False),
        json.dumps(_card_payload(), ensure_ascii=False),
    ])
    result = generate_card(INPUT, client=client)
    assert result.llm_calls == 2
    assert result.verification.ok
    assert "0,001" in client.calls[1][-1].content


def test_persistent_hallucination_raises() -> None:
    bad = _card_payload(seo_description=_pad("Точность 0,001 гПа."))
    raw = json.dumps(bad, ensure_ascii=False)
    client = FakeLLMClient([raw, raw])
    with pytest.raises(GenerationError) as exc_info:
        generate_card(INPUT, client=client)
    assert "0,001" in str(exc_info.value)


def test_spec_hallucination_sanitized_without_retry() -> None:
    bad = _card_payload(specs=[
        {"name": "Диапазон измерений", "value": "0...100 гПа"},
        {"name": "Класс защиты корпуса", "value": "IP67"},
        {"name": "Погрешность", "value": "±0,03 гПа"},
    ])
    client = FakeLLMClient([json.dumps(bad, ensure_ascii=False)])
    result = generate_card(INPUT, client=client)
    assert result.llm_calls == 1  # перегенерация не потребовалась
    assert result.verification.ok
    spec = next(
        s for s in result.card.specs if s.name == "Класс защиты корпуса"
    )
    assert spec.value == "данных нет"
    assert "Класс защиты корпуса" in result.card.missing_fields


def test_invalid_input_short_circuits_llm() -> None:
    client = FakeLLMClient([])
    with pytest.raises(InvalidInputError):
        generate_card("{битый json", client=client)
    assert client.calls == []
