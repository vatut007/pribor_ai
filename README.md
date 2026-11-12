# pribor-ai — AI-генератор карточек контрольно-измерительных приборов

Прототип сервиса для контент-менеджера B2B-магазина КИП: на входе —
JSON о приборе (название, производитель, характеристики, описание),
на выходе — черновик товарной карточки:

- SEO-заголовок (≤ 70 символов);
- SEO-описание (800–1200 символов);
- характеристики (отсутствующие — со значением «данных нет»);
- 3–5 поисковых запросов;
- коммерческий блок для менеджера по продажам.

LLM: **YandexGPT** — основной, любой **OpenAI-совместимый**
(OpenAI, DeepSeek, локальные Ollama/vLLM) — резервный.
Анти-галлюцинация двухуровневая: жёсткие правила в промпте +
программный верификатор, который не пропустит в карточку число,
отсутствующее во входных данных. Подробности: [docs/PROMPTS.md](docs/PROMPTS.md),
ограничения: [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Требования

- Python **3.10+** (проверено на 3.12);
- [uv](https://docs.astral.sh/uv/) (рекомендуется) **или** pip.

## Установка

Вариант с uv (рекомендуется): создаёт `.venv`, ставит версии из
`uv.lock` — полностью воспроизводимо.

```bash
uv sync
```

Вариант с pip — из экспорта uv (`requirements.txt` зафиксирован целиком,
включая транзитивные версии и dev-зависимости):

```bash
pip install -r requirements.txt
```

Затем — ключи провайдера:

```bash
cp .env.example .env
# заполните .env (ключи в git не попадают: .env в .gitignore)
```

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `LLM_PROVIDER` | `yandexgpt` \| `openai_compatible` | `yandexgpt` |
| `YC_FOLDER_ID` | каталог Yandex Cloud (обязателен для YandexGPT) | — |
| `YC_API_KEY` | API-ключ (приоритет над IAM-токеном) | — |
| `YC_IAM_TOKEN` | IAM-токен (альтернатива API-ключу) | — |
| `YC_MODEL` | модель (`yandexgpt`, `yandexgpt-lite`, …) | `yandexgpt` |
| `LLM_BASE_URL` | базовый URL OpenAI-совместимого API | — |
| `LLM_API_KEY` | ключ OpenAI-совместимого (не обязателен: Ollama/vLLM) | — |
| `LLM_MODEL` | имя модели OpenAI-совместимого | — |
| `LLM_TEMPERATURE` | температура генерации | `0.2` |
| `LLM_MAX_TOKENS` | лимит токенов ответа | `2000` |
| `LLM_TIMEOUT` | таймаут запроса, с | `60` |
| `LLM_MAX_RETRIES` | попытки на 429/5xx | `3` |

## Запуск CLI

```bash
python main.py <input.json> [--format json|md] [--output <path>] [--provider yandexgpt|openai_compatible]
```

Примеры:

```bash
uv run python main.py examples/testo_510_input.json --format md
python main.py examples/ims_f1_input.json --format json --output card.json
```

Карточка печатается в stdout (или пишется в `--output`); сводка
верификатора («Проверено чисел: N, отклонено: M») и недостающие поля —
в stderr. Коды выхода: `0` — успех; `1` — файл не читается; `2` —
некорректный вход; `3` — LLM дважды вернул непригодный ответ; `4` —
ошибка LLM (сеть, лимиты, конфигурация).

## Запуск FastAPI

```bash
uvicorn app:app --reload
# или: uv run uvicorn app:app --reload
```

- `GET /` — HTML-форма: вставить JSON, сгенерировать, скопировать
  результат (JSON или Markdown);
- `POST /generate` — тело: JSON товара, ответ — карточка `ProductCardOutput`;
  `POST /generate?format=md` — Markdown-черновик;
- ошибки: `422` — некорректный вход; `502` — LLM ответил непригодно;
  `503` — LLM недоступен (таймаут, лимит, не сконфигурирован).

```bash
curl -s -X POST -H "Content-Type: application/json" \
  --data-binary @examples/testo_510_input.json \
  http://127.0.0.1:8000/generate?format=md
```

## Регенерация примеров YandexGPT

Примеры в `examples/` сгенерированы реальным YandexGPT через те же
промпты и верификатор. Команда для регенерации карточки по входу:

```bash
LLM_PROVIDER=yandexgpt python main.py examples/testo_510_input.json --output examples/testo_510_output.json
LLM_PROVIDER=yandexgpt python main.py examples/testo_510_input.json --format md --output examples/testo_510_output.md
```

(через uv: `uv run python main.py …`). Перед запуском заполните
`YC_FOLDER_ID` и `YC_API_KEY` (или `YC_IAM_TOKEN`) в `.env`.

## Пример входного JSON

```json
{
  "name": "Дифференциальный манометр testo 510",
  "manufacturer": "Testo",
  "category": "Измерители давления воздушного потока",
  "specs": {
    "Диапазон измерений": "0…100 гПа",
    "Погрешность": "±0,03 / ±0,05 / ±(0,1 гПа + 1,5 %)",
    "Разрешение": "0,01 гПа",
    "Степень защиты": "IP40",
    "Питание": "2×ААА",
    "Габариты": "119×46×25 мм"
  },
  "description": "Прибор для измерения перепада давления воздуха."
}
```

Обязательны только `name` и `manufacturer`; пропуск описания и части
характеристик — нормальный случай: они попадут в отчёт «данных нет».

## Тесты

```bash
uv run python -m pytest tests/ -q
```

41 тест: валидатор входа, верификатор чисел (выдуманное число ловится),
пайплайн генератора (ретраи, санитизация), CLI и API. Реальные вызовы
LLM тесты не выполняют — сетевой слой подменяется фейковым клиентом.

## Структура проекта

```
src/
  models.py      # pydantic-схемы входа и выхода
  validator.py   # валидация входного JSON, отчёт missing_fields
  prompts.py     # системный/пользовательский промпты, JSON-схема
  verifier.py    # анти-галлюцинация: числа ответа против входа
  generator.py   # пайплайн: validate → prompt → LLM → parse → verify
  output.py      # рендер JSON и Markdown
  llm/           # BaseLLMClient + YandexGPT + OpenAI-совместимый + фабрика
app.py           # FastAPI: POST /generate + GET / (форма)
main.py          # CLI
templates/       # form.html
examples/        # входные и сгенерированные карточки (json + md)
docs/            # PROMPTS.md, LIMITATIONS.md, план
```
