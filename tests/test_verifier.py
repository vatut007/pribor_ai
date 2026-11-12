"""Тесты верификатора (п. 6.4): выдуманные числа ловятся, форматы
нормализуются, отчёт содержит счётчики проверенных/отклонённых чисел."""

from src.models import ProductCardOutput, ProductInput, SpecItem
from src.verifier import verify_output


def _product() -> ProductInput:
    return ProductInput(
        name="Манометр дифференциальный testo 510",
        manufacturer="testo",
        category="Манометры",
        specs={
            "Диапазон измерений": "0...100 гПа",
            "Погрешность": "±0,03 гПа",
            "Разрешение": "0,01 гПа",
            "Рабочая температура": "-20...+50 °С",
            "Питание": "батарея 9 В, тип 6F22",
        },
        description="Прибор для измерения перепада давления.",
    )


def _specs_ok() -> list[SpecItem]:
    return [
        SpecItem(name="Диапазон измерений", value="0–100 гПа"),
        SpecItem(name="Погрешность", value="±0,03 гПа"),
        SpecItem(name="Разрешение", value="0,01 гПа"),
        SpecItem(name="Питание", value="батарея 9 В, тип 6F22"),
    ]


def _pad(text: str) -> str:
    """Дотягивает описание до pydantic-минимума (800) без новых чисел."""
    sentence = (
        "Рекомендуется для пусконаладки, сервисных работ "
        "и входного контроля. "
    )
    while len(text) < 810:
        text += sentence
    return text


def _output(specs: list[SpecItem], description: str) -> ProductCardOutput:
    return ProductCardOutput(
        seo_title="Манометр testo 510 — измерение перепада давления",
        seo_description=_pad(description),
        specs=specs,
        search_queries=[
            "купить манометр testo 510",
            "перепад давления",
            "дифференциальный манометр",
        ],
        commercial_block="Подходит монтажникам и метрологам для замеров.",
    )


def test_valid_output_passes() -> None:
    """Корректный ответ (все числа из входа, «данных нет») — ok."""
    specs = [
        SpecItem(name="Диапазон измерений", value="0–100 гПа"),
        SpecItem(name="Погрешность", value="±0,03 гПа"),
        SpecItem(name="Питание", value="батарея 9 В, тип 6F22"),
        SpecItem(name="Интерфейсы", value="данных нет"),
    ]
    description = (
        "Манометр testo 510 измеряет перепад давления и давления газа "
        "в диапазоне от 0 до 100 hPa с точностью 0.03 hPa. "
        "Рабочая температура от -20 до +50 °C, питание — батарея 9 В."
    )
    report = verify_output(_output(specs, description), _product())
    assert report.ok
    assert report.rejected == 0
    # specs: 0,100,0,03,9,6,22 = 6; описание: 510,0,100,0.03,20,50,9 = 7
    assert report.checked == 13


def test_hallucinated_in_description_caught() -> None:
    """Выдуманное число в seo_description отклоняется."""
    report = verify_output(
        _output(
            _specs_ok(),
            "Точность 0,001 гПа — без аналогов.",
        ),
        _product(),
    )
    assert not report.ok
    assert report.rejected == 1
    h = report.hallucinated[0]
    assert h.value == "0,001"
    assert h.place == "seo_description"
    assert h.spec_name == ""
    assert h.unit == "hpa"
    assert "0,001" in h.context
    assert "отклонено: 1" in report.summary()


def test_hallucinated_in_spec_caught() -> None:
    """Выдуманное число в значении характеристики отклоняется."""
    specs = _specs_ok() + [SpecItem(name="Степень защиты", value="IP54")]
    report = verify_output(
        _output(specs, "Обычное описание без чисел."),
        _product(),
    )
    assert not report.ok
    assert report.rejected == 1
    h = report.hallucinated[0]
    assert h.place == "specs"
    assert h.spec_name == "Степень защиты"
    assert h.value == "54"
    assert h.unit == ""
    assert "54" in h.context


def test_format_normalization_passes() -> None:
    """0,03 ≡ 0.03; 0...100 ≡ 0 - 100 ≡ 0–100; гПа ≡ hPa; °С ≡ °C."""
    specs = [
        SpecItem(name="Диапазон измерений", value="0 - 100"),
        SpecItem(name="Погрешность", value="0.03 hPa"),
    ]
    description = (
        "Диапазон 0...100 hPa, погрешность 0,03 hPa, "
        "температура -20…+50 °C."
    )
    report = verify_output(_output(specs, description), _product())
    assert report.ok
    assert report.rejected == 0


def test_wrong_unit_rejected() -> None:
    """Число есть во входе, но единица выдумана: «100 МПа» vs «0...100 гПа»."""
    report = verify_output(
        _output(_specs_ok(), "Измеряет давление до 100 МПа."),
        _product(),
    )
    assert not report.ok
    h = report.hallucinated[0]
    assert h.value == "100"
    assert h.unit == "mpa"
    assert "100" in h.context


def test_report_counters() -> None:
    """Счётчики проверенных/отклонённых чисел в отчёте и summary()."""
    report = verify_output(
        _output(_specs_ok(), "Диапазон до 200 гПа, точность 0,001 гПа."),
        _product(),
    )
    assert report.rejected == 2
    assert len(report.hallucinated) == 2
    # specs: 7 чисел; описание: 200 и 0,001 — всего 9
    assert report.checked == 9
    s = report.summary()
    assert f"Проверено чисел: {report.checked}" in s
    assert "отклонено: 2" in s
    assert "200 hpa" in s
    assert "0,001 hpa" in s


def test_model_number_allowed() -> None:
    """«510» из названия модели есть во входе — не галлюцинация."""
    report = verify_output(
        _output(
            _specs_ok(),
            "Манометр testo 510 для измерения перепада давления.",
        ),
        _product(),
    )
    assert report.ok
    assert report.rejected == 0
