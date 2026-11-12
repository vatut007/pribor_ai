"""Тесты FastAPI: /generate в форматах json/md, ошибки
422/502/503, GET / с формой. LLM подменяется фейковым клиентом."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app
from src.llm.base import (
    BaseLLMClient,
    LLMMessage,
    LLMRateLimitError,
    LLMResponse,
    LLMResponseError,
)

EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "testo_510_input.json"
)

client = TestClient(app)


def _pad(text: str) -> str:
    sentence = "Прибор применяется при пусконаладке и сервисных работах. "
    while len(text) < 810:
        text += sentence
    return text


def _valid_payload() -> dict:
    """Валидная карточка: все числа — из входа testo 510."""
    return {
        "seo_title": "Манометр testo 510 — измерение перепада давления",
        "seo_description": _pad(
            "Диапазон измерений 0…100 гПа, погрешность ±0,03 гПа. "
            "Защита корпуса IP40, питание 2×ААА, ресурс до 50 ч. "
            "Габариты 119×46×25 мм, рабочая температура 0…+50 °C."
        ),
        "specs": [
            {"name": "Диапазон измерений", "value": "0…100 гПа"},
            {"name": "Погрешность", "value": "±0,03 гПа"},
            {"name": "Степень защиты", "value": "IP40"},
            {"name": "Интерфейсы", "value": "данных нет"},
        ],
        "search_queries": [
            "купить манометр testo 510",
            "дифференциальный манометр",
            "манометр перепада давления",
        ],
        "commercial_block": (
            "Подойдёт монтажникам ОВиК и сервисным инженерам для "
            "пусконаладки и поверки систем вентиляции."
        ),
        "missing_fields": ["интерфейсы"],
    }


class FakeLLMClient(BaseLLMClient):
    """Готовые ответы; exceptions — что бросать вместо ответа."""

    def __init__(
        self,
        responses: list[str],
        exceptions: list[Exception] | None = None,
    ) -> None:
        self._responses = list(responses)
        self._exceptions = list(exceptions or [])
        self.calls: int = 0

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        self.calls += 1
        if self._exceptions:
            raise self._exceptions.pop(0)
        return LLMResponse(text=self._responses.pop(0), model="fake")

    def health(self) -> bool:
        return True


def _patch(monkeypatch: pytest.MonkeyPatch, fake: FakeLLMClient) -> None:
    monkeypatch.setattr("src.generator.get_client", lambda p=None: fake)


def test_index_serves_form() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "textarea" in resp.text
    assert 'id="input"' in resp.text
    assert "Сгенерировать" in resp.text
    assert "Копировать" in resp.text


def test_generate_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLLMClient(
        [json.dumps(_valid_payload(), ensure_ascii=False)]
    )
    _patch(monkeypatch, fake)
    resp = client.post("/generate", content=EXAMPLE.read_bytes())
    assert resp.status_code == 200
    data = resp.json()
    assert data["seo_title"].startswith("Манометр")
    assert data["missing_fields"] == ["интерфейсы"]
    assert fake.calls == 1


def test_generate_markdown_format(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLLMClient(
        [json.dumps(_valid_payload(), ensure_ascii=False)]
    )
    _patch(monkeypatch, fake)
    resp = client.post("/generate?format=md", content=EXAMPLE.read_bytes())
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert resp.text.startswith("# Манометр testo 510")


def test_bad_format_is_422() -> None:
    resp = client.post("/generate?format=xml", content=EXAMPLE.read_bytes())
    assert resp.status_code == 422


def test_broken_json_body_is_422() -> None:
    resp = client.post("/generate", content="{битый")
    assert resp.status_code == 422
    assert "JSON" in resp.json()["detail"]


def test_non_object_body_is_422() -> None:
    resp = client.post("/generate", content='[1, 2, 3]')
    assert resp.status_code == 422
    assert "объект" in resp.json()["detail"]


def test_missing_manufacturer_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLLMClient([])
    _patch(monkeypatch, fake)
    body = EXAMPLE.read_text(encoding="utf-8").replace(
        '"manufacturer": "Testo",', ""
    )
    resp = client.post("/generate", content=body.encode("utf-8"))
    assert resp.status_code == 422
    assert "manufacturer" in resp.json()["detail"]
    assert fake.calls == 0


def test_persistent_bad_answer_is_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLLMClient(["нет и не будет", "всё ещё нет"])
    _patch(monkeypatch, fake)
    resp = client.post("/generate", content=EXAMPLE.read_bytes())
    assert resp.status_code == 502
    assert "дважды" in resp.json()["detail"]
    assert fake.calls == 2


def test_rate_limit_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLLMClient([], exceptions=[LLMRateLimitError("429")])
    _patch(monkeypatch, fake)
    resp = client.post("/generate", content=EXAMPLE.read_bytes())
    assert resp.status_code == 503
    assert "недоступен" in resp.json()["detail"]


def test_invalid_answer_error_is_502(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLLMClient(
        [], exceptions=[LLMResponseError("битый ответ", status_code=418)]
    )
    _patch(monkeypatch, fake)
    resp = client.post("/generate", content=EXAMPLE.read_bytes())
    assert resp.status_code == 502
    assert "Ошибка LLM" in resp.json()["detail"]
