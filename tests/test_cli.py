"""Тесты CLI (п. 7.2): чтение файла, форматы json/md, --output,
коды выхода 1/2/3. Реальный LLM подменяется фейковым клиентом."""

import json
from pathlib import Path

import pytest

from src.llm.base import BaseLLMClient, LLMMessage, LLMResponse
from main import main

EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "testo_510_input.json"
)


def _pad(text: str) -> str:
    sentence = "Прибор применяется при пусконаладке и сервисных работах. "
    while len(text) < 810:
        text += sentence
    return text


def _valid_payload() -> dict:
    """Валидная карточка: все числа — из входа testo 510 (п. 3.3)."""
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
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
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
        return LLMResponse(text=self._responses.pop(0), model="fake")

    def health(self) -> bool:
        return True


@pytest.fixture
def fake_ok(monkeypatch: pytest.MonkeyPatch) -> FakeLLMClient:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    fake = FakeLLMClient([payload])
    monkeypatch.setattr("src.generator.get_client", lambda p=None: fake)
    return fake


def test_md_to_stdout(
    fake_ok: FakeLLMClient, capsys: pytest.CaptureFixture
) -> None:
    assert main([str(EXAMPLE), "--format", "md"]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("# Манометр testo 510")
    assert "## Характеристики" in out.out
    assert "Проверено чисел" in out.err
    assert "интерфейсы" in out.err  # недостающие поля — в stderr
    assert fake_ok.calls == 1


def test_json_to_output_file(
    fake_ok: FakeLLMClient,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    target = tmp_path / "card.json"
    argv = [str(EXAMPLE), "--format", "json", "--output", str(target)]
    assert main(argv) == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["seo_title"].startswith("Манометр")
    assert len(data["search_queries"]) == 3
    out = capsys.readouterr()
    assert f"Карточка записана: {target}" in out.err


def test_input_file_not_found(capsys: pytest.CaptureFixture) -> None:
    assert main(["нет-такого-файла.json"]) == 1
    assert "Не удалось прочитать" in capsys.readouterr().err


def test_invalid_input_exit_2(
    fake_ok: FakeLLMClient, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{битый json", encoding="utf-8")
    assert main([str(broken)]) == 2
    assert "Некорректный вход" in capsys.readouterr().err
    assert fake_ok.calls == 0  # до LLM дело не дошло


def test_generation_error_exit_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake = FakeLLMClient(["нет и не будет", "всё ещё нет"])
    monkeypatch.setattr("src.generator.get_client", lambda p=None: fake)
    assert main([str(EXAMPLE)]) == 3
    assert "Генерация не удалась" in capsys.readouterr().err
