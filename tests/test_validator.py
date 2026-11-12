"""Тесты валидатора входа (п. 6.5): битый JSON, пустые поля, неверные типы."""

import pytest

from src.validator import EXPECTED_CHARACTERISTICS, InvalidInputError, validate_input

VALID = {
    "name": "Дифференциальный манометр testo 510",
    "manufacturer": "Testo",
    "category": "Измерители давления воздушного потока",
    "specs": {
        "диапазон измерений": "0…100 гПа",
        "класс точности": "",
        "питание": "2 батарейки ААА 1,5 В",
        "степень защиты": "IP40",
        "габариты": "119×46×25 мм",
    },
    "description": "Манометр для измерения дифференциального давления.",
}


def test_valid_full_input():
    res = validate_input(dict(VALID))
    assert res.product.manufacturer == "Testo"
    # не заявлены только «интерфейсы»; «класс точности» заявлен, но с пустым значением
    assert res.missing_fields == ["интерфейсы", "класс точности"]


def test_minimal_input_all_characteristics_missing():
    res = validate_input({"name": "ОВЕН ИМС-Ф1", "manufacturer": "ОВЕН"})
    assert res.product.specs == {}
    assert len(res.missing_fields) == len(EXPECTED_CHARACTERISTICS)
    assert "диапазон измерений" in res.missing_fields


def test_broken_json_reports_position():
    # пропущена запятая после значения manufacturer — ошибка на строке 4
    raw = '{\n  "name": "testo",\n  "manufacturer": "Testo"\n  "specs": {}\n}'
    with pytest.raises(InvalidInputError) as ei:
        validate_input(raw)
    msg = str(ei.value)
    assert "строка 4" in msg
    assert "позиции" in msg


def test_empty_json_string():
    with pytest.raises(InvalidInputError):
        validate_input("")


def test_json_array_is_not_an_object():
    with pytest.raises(InvalidInputError) as ei:
        validate_input("[1, 2, 3]")
    assert "JSON-объект" in str(ei.value)


def test_missing_required_field():
    with pytest.raises(InvalidInputError) as ei:
        validate_input({"name": "testo 510"})
    assert "manufacturer" in str(ei.value)


def test_wrong_types():
    with pytest.raises(InvalidInputError) as ei:
        validate_input({"name": "x", "manufacturer": "y", "specs": ["не", "словарь"]})
    assert "specs" in str(ei.value)

    with pytest.raises(InvalidInputError) as ei:
        validate_input({"name": "x", "manufacturer": "y", "description": 123})
    assert "description" in str(ei.value)


def test_whitespace_only_required_field():
    with pytest.raises(InvalidInputError) as ei:
        validate_input({"name": "   ", "manufacturer": "ОВЕН"})
    assert "name" in str(ei.value)


def test_whitespace_is_stripped():
    res = validate_input(
        {
            "name": "  testo 510  ",
            "manufacturer": " Testo ",
            "specs": {" диапазон ": " 0…100 гПа "},
        }
    )
    assert res.product.name == "testo 510"
    assert res.product.specs == {"диапазон": "0…100 гПа"}


def test_spec_key_with_empty_value_goes_to_missing():
    res = validate_input(dict(VALID))
    assert "класс точности" in res.missing_fields


def test_declared_characteristic_is_not_missing():
    res = validate_input(
        {
            "name": "x",
            "manufacturer": "y",
            "specs": {"интерфейс": "USB", "Диапазон измерений": "0…100 гПа"},
        }
    )
    assert "интерфейсы" not in res.missing_fields
    assert "диапазон измерений" not in res.missing_fields
    assert "степень защиты / корпус" in res.missing_fields
