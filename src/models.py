"""Pydantic-схемы входа и выхода.

ProductInput      — JSON, который клиент присылает в POST /generate и в CLI.
SpecItem          — одна строка списка характеристик карточки.
ProductCardOutput — строгий JSON-ответ LLM, который возвращает сервис.
"""

from pydantic import BaseModel, Field

# Ограничения из задания — проверяются pydantic при валидации ответа LLM
SEO_TITLE_MAX_LEN = 70
SEO_DESCRIPTION_MIN_LEN = 800
SEO_DESCRIPTION_MAX_LEN = 1200
SEARCH_QUERIES_MIN = 3
SEARCH_QUERIES_MAX = 5


class ProductInput(BaseModel):
    """Входные данные о приборе.

    Обязательные поля: name и manufacturer.
    specs — словарь «характеристика → значение». Отсутствие описания и
    части характеристик — нормальный случай: они попадут в missing_fields.
    """

    name: str = Field(min_length=1, description="Название прибора")
    manufacturer: str = Field(min_length=1, description="Производитель")
    category: str | None = Field(
        default=None,
        description="Категория прибора (опционально)",
    )
    specs: dict[str, str] = Field(
        default_factory=dict,
        description="Характеристики прибора: ключ → значение",
    )
    description: str = Field(
        default="",
        description="Текстовое описание прибора (источник фактов для LLM)",
    )


class SpecItem(BaseModel):
    """Одна характеристика в карточке."""

    name: str
    value: str  # значение из входа ИЛИ «данных нет»


class ProductCardOutput(BaseModel):
    """Черновик карточки товара: строгий JSON-ответ LLM."""

    seo_title: str = Field(
        max_length=SEO_TITLE_MAX_LEN,
        description=f"SEO-заголовок, не более {SEO_TITLE_MAX_LEN} символов",
    )
    seo_description: str = Field(
        min_length=SEO_DESCRIPTION_MIN_LEN,
        max_length=SEO_DESCRIPTION_MAX_LEN,
        description="SEO-описание, 800–1200 символов",
    )
    specs: list[SpecItem] = Field(
        description="Ключевые характеристики из входных данных"
    )
    search_queries: list[str] = Field(
        min_length=SEARCH_QUERIES_MIN,
        max_length=SEARCH_QUERIES_MAX,
        description="Поисковые запросы, 3–5 шт.",
    )
    commercial_block: str = Field(
        description=(
            "Кому подходит прибор и какие задачи решает (для менеджера)"
        ),
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Характеристики, которых нет во входе "
            "(в карточке — «данных нет»)"
        ),
    )
