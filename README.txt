docker build -t finaudit . && docker run --rm --network none --cpus 2 --memory 4g finaudit make check

Windows PowerShell 5.1 не знает `&&` — выполните две команды по очереди:
`docker build -t finaudit .`, затем `docker run --rm --network none --cpus 2 --memory 4g finaudit make check`.
Памятка для жюри — docs/JURY.txt: запуск, адаптер, рецепты D01–D20, правила пересчёта и переименования ID.

# FinAudit — RL-среда (тренажёр) для ИИ-аудитора

Воспроизводимая офлайн-среда обучения с подкреплением для ИИ-аудитора финансовой отчётности. Она генерирует
синтетические компании (одна компания × один календарный месяц) со скрытыми бухгалтерскими ошибками, открывает их
через JSON-контракт в стиле Gymnasium (`reset` / `step`) с узкими инструментами расследования и оценивает выводы
аудитора публичным детерминированным matcher и функцией награды. Мы сдаём среду, а не агента: четыре фиксированные
базовые политики включены только для того, чтобы показать, что среда не тривиальна и решаема.

Все данные вымышлены (имена собраны из слогов; нет реальных компаний, банков, IBAN, карт или людей).
Среда выполнения — стандартная библиотека Python 3.11 + `tzdata==2024.2`; для тестов нужен только `pytest==8.3.3`.
Сеть, GPU и платные API не используются. Зафиксированные wheel-пакеты лежат в `vendor/wheels/`, поэтому
`docker build` не требует сети, если базовый образ `python:3.11-slim` уже есть на машине (один раз
`docker pull python:3.11-slim` или `docker load -i <tar образа>`; проверенный digest — в заголовке `Dockerfile`).
Запускайте образ от root (по умолчанию): каталоги `private/` принадлежат оценщику и намеренно недоступны другим
пользователям, поэтому запуск с `--user` провалит тест утечек на сданных данных с `PermissionError`.

## Быстрый старт

| Команда | Что делает |
|---|---|
| `make check` | полный набор тестов (287 тестов, ≈45–65 с суммарно; лимит 60 с — на эпизод) + smoke-прогон: 2 новых эпизода, verify, 4 политики, сканер утечек |
| `make docker-check` | собирает образ и запускает `make check` с `--network none --cpus 2 --memory 4g` |
| `make episodes` | заново генерирует сданный набор `episodes/{train,dev}` (10 + 10, с проверкой) |
| `make trajectories` | 4 политики × 10 train-эпизодов → `trajectories/trajectories.jsonl` |
| `make jury` | симуляция закрытой проверки: 20 новых эпизодов × 4 политики в режиме eval, 20 парных проверок, 20 повторов |
| `make report` | пересобирает `REPORT.txt` из `runs/jury/summary.json` |
| `make demo` | пошаговый показ в терминале на эпизоде I1 |

Без GNU make любая цель запускается как `python3.11 -m finaudit.tasks <цель>` (в Docker-образе `make` — это
обёртка ровно над этой командой). Один эпизод вручную:
`python3.11 -m finaudit.generator.generate --seed 7 --config configs/default.json --out /tmp/eps`.

```python
from finaudit.env.core import FinAuditEnv
env = FinAuditEnv()
obs, info = env.reset(seed=7, config={"mode": "train"})          # или config={"episode_dir": "episodes/train/ep-…"}
obs, reward, terminated, truncated, info = env.step({"action": "list_records", "table": "ledger"})
```

## Контракт

* `reset(seed, config) -> (observation, info)` — полный сброс состояния. `config["episode_dir"]` загружает
  сохранённый эпизод, иначе эпизод генерируется из `(seed, config, ENV_VERSION)`. `config["mode"]` —
  `train` (по умолчанию) или `eval`.
* `step(action) -> (observation, reward, terminated, truncated, info)`; все значения сериализуются в JSON.
* Observation всегда: `{"ok": bool, "result": any|null, "error": {"code","message"}|null, "steps_left": int}`.
  Первое observation содержит текст задачи, `manifest`, `policy`, имена таблиц, четыре типа выводов и лимиты.

| Действие | Аргументы | Результат |
|---|---|---|
| `list_records` | `table` ∈ ledger/invoices/payments/fx, `cursor` (непрозрачный, null = начало), `limit` 1..50 | `{"table","records","next_cursor"}` в порядке файла |
| `get_record` | `table`, `id` (row_id / doc_id / `fx:YYYY-MM-DD:SRC:TGT`) | `{"table","record"}` |
| `get_document` | `doc_id` счёта или платежа | `{"doc_type","document"}` |
| `calculator` | `expression`: числа, `+ - * /`, унарный минус, скобки, ≤ 200 символов (ast + Decimal, 28 знаков) | `{"value": "…"}` |
| `submit` | `findings` = `{"episode_id", "findings": [...]}` | эпизод завершается |

Коды ошибок (закрытый список): `UNKNOWN_ACTION, BAD_ARGS, UNKNOWN_TABLE, NOT_FOUND, BAD_CURSOR, LIMIT_TOO_LARGE,
BAD_EXPRESSION, EPISODE_DONE, INVALID_FINDINGS`; сообщения ≤ 120 символов, без путей, трассировок и подсказок.
Каждый шаг, включая ошибочный, расходует 1 из 100 шагов (submit тоже). `submit` → `terminated=true`;
100 шагов без submit или 60 с реального времени (контролирует runner) → `truncated=true`, оценивается пустой ответ.
Любой шаг после завершения возвращает `EPISODE_DONE`, ничего не стоит, награда 0, флаги не меняются; повторный
submit никогда не оценивается. На каждом нетерминальном шаге награда 0.0.

* **train**: терминальный шаг возвращает терминальную награду и `info = {precision, recall, f1, tp, fp, fn,
  inspection_steps}`.
* **eval**: награда всегда 0.0, `info = {"steps_used": n}`; оценка пишется только в `grader_log.jsonl`.
  `python -m finaudit.runner run --mode eval …` запускает env-server (`finaudit.env.server`, JSON-строки) и
  агента (`python -m finaudit.policies.<имя>`) отдельными процессами; от root в Docker они работают как
  пользователи `grader` и `agent`, каталоги `private/` и каталоги прогонов принадлежат `grader` с правами 700,
  агент работает в пустом каталоге и получает только observations.

## Форматы данных (`public/` эпизода)

`manifest.json` (ID, компания, базовая валюта, период, часовой пояс, количества, экспоненты валют), `ledger.csv`
(`row_id,timestamp,account,debit_minor,credit_minor,currency,entity_id,invoice_id,payment_id`), `invoices.jsonl`,
`payments.jsonl`, `fx.csv` (`date,source_currency,target_currency,rate`, одна строка в день с period_start−7 по
period_end+7 для каждой иностранной валюты) и `policy.json` (правила проводок). В `private/` лежат `truth.json`,
`provenance.json`, `generation.json`; агенту они не показываются никогда. JSON-схемы: `finaudit/schemas/`.

Независимая проверка любого эпизода: `python3.11 -m finaudit.generator.verify episodes/dev/ep-…` — структура,
sha256, `reference_audit(public) == truth` в обе стороны, достижимость ID доказательств, отсутствие утечек и
**равенства до внесения ошибки**: `provenance.json` фиксирует каждое внесённое изменение (`table, id, field,
before, after`); обратное воспроизведение (`finaudit/generator/revert.py`) даёт книги, которые сходятся, содержат
проводки по каждому документу периода и в которых эталонный аудитор ничего не находит.

* Деньги: целые минимальные единицы (`total_minor: 1250000` = 12 500.00); экспоненты — в manifest (JPY = 0).
* Время: ISO-8601 со смещением; смещения намеренно различаются (местное или `+00:00`), момент времени верный.
* Курсы: десятичные строки с 6 знаками. Отсутствующие ссылки: явный `null`; в CSV **пустая ячейка = null**.
* Суммы в ledger — в базовой валюте; ровно одно из debit/credit > 0. Счета: AR, AP, REVENUE, EXPENSE,
  BANK, SUSPENSE, FX_GAIN_LOSS. Пары проводок без ссылок на документы дополняют ledger (банковские комиссии и т. п.).
* Расширения схемы (ничего обязательного не переименовано и не удалено): `invoices[].direction` ∈
  `receivable|payable`; `payments[].direction` ∈ `incoming|outgoing` (incoming — сторона покупателя; возврат — это
  входящий платёж с отрицательной суммой и отрицательной ссылкой); записи fx, возвращаемые инструментами, имеют
  дополнительное поле `fx_id`.
* Политика проводок: дата курса = местная календарная дата документа в `manifest.timezone`;
  `base = round_half_even(amount / 10^exp_src × rate × 10^exp_base)`; BANK — по курсу даты платежа, строки
  распределения AR/AP — по курсу даты счёта, разница — на FX_GAIN_LOSS. Ограничение: платёж всегда в валюте
  своего счёта (без кросс-валютных расчётов).

## Скрытые типы ошибок

| type | affected_ids | сумма и валюта | достаточные доказательства (любой один набор) |
|---|---|---|---|
| `DUPLICATE_INVOICE` | оба invoice_id | сумма копии, валюта счёта | оба doc_id + обе строки AR/AP в ledger |
| `PAYMENT_ALLOCATION` | invoice_id + payment_id | нераспределённая часть, валюта платежа | документ платежа + документ счёта + все строки ledger по платежу (+ строка `fx:` на дату счёта, если иностранный платёж проведён частично) |
| `FX_CONVERSION` | invoice_id или payment_id | \|проведено − по policy\| строки AR/AP (счёт) или BANK (платёж), базовая валюта | документ + строка `fx:` правильной даты + затронутая строка |
| `PERIOD_CUTOFF` | invoice_id | проведённая сумма AR/AP, базовая валюта | документ счёта + его строка AR/AP |

Распределение `(payment, invoice_ref)` **полное** (вывода нет) тогда и только тогда, когда проведённая для него
знаковая сумма AR/AP равна `fx_conversion(invoice_ref.amount_minor, курс даты счёта)` (для платежа в базовой
валюте — тождество). Только иначе нераспределённая часть = сумма ссылки − `round_half_even(posted_base / rate(дата
счёта))` в минимальных единицах валюты платежа. При независимом пересчёте соблюдайте этот порядок: одно обратное
преобразование не обратимо и дало бы ложные расхождения в 1 единицу на корректных книгах
(`finaudit/generator/reference_audit.py`, `_payment_checks`).
Два сценария взаимодействия добавляют по две связанные ошибки: **I1** — иностранный платёж покупателя поздно
вечером в последний день, BANK проведён по курсу UTC-даты (или следующего дня), затем частично отложен на SUSPENSE;
**I2** — продублированный счёт, единственный платёж по которому проведён 50/50 на оригинал и копию. Каждый эпизод
также содержит ≥ 3 вида корректных отвлекающих случаев (разбитые платежи, один платёж за несколько счетов,
переплата + возврат, еженедельно повторяющиеся суммы, документы около полуночи, чья UTC-дата вне периода,
непроведённые счета следующего месяца, строки FX gain/loss, остатки округления в 1 единицу). Чистые компании
(`configs/clean.json`) ошибок не содержат.

## Matcher и награда (`finaudit/grader/`)

Соответствует точным соглашениям matcher из определений проверок (`docs/CHECKS.txt`, тесты
`tests/test_jury_matcher.py`).

1. Структура (проверяется на исходных списках, до удаления повторов): точные ключи, совпадение `episode_id`,
   ≤ 30 выводов, строковый `type`, 1..10 строковых `affected_ids`, `claimed_amount_minor` — JSON-целое ≥ 0
   (bool/float/строка отклоняются), строковая `currency`, ≤ 10 строковых `evidence_ids`, `explanation` ≤ 1000
   Unicode code points. Любое нарушение → награда −1 (`INVALID_FINDINGS`), метрики null в `score_episode`.
2. Нормализация: для строк нет — `type`, `currency` и все ID сравниваются точно (регистр и пробелы важны).
   `affected_ids` и `evidence_ids` — множества. Неизвестная строка типа — валидный, но несопоставленный вывод (FP).
3. Пара (вывод, ошибка) допустима тогда и только тогда, когда совпадают тип, множества affected_ids, валюта,
   `|claimed − expected| ≤ τ(type)`, каждый ID доказательства существует в открытых записях и доказательства
   содержат полный допустимый набор (дополнительные существующие ID допустимы). `explanation` на оценку не влияет.
   ID доказательств — только канонические ID записей: `row_id` в ledger, `doc_id` документа, `fx:DATE:SRC:TGT`.
   Псевдонимы, которые также принимает `get_record` (`invoice_id`, `payment_id`, fx-ID без `fx:`), ID
   доказательств не являются.
4. τ — фиксированное неотрицательное целое для каждого типа, опубликованное в `policy.json → amount_tolerance_minor`
   (нет ключа → 0). Сданное значение: **0 для всех четырёх типов** — каждая ожидаемая сумма точно следует из формул
   в `policy.json` (`fx_conversion`, `payment_allocation_amount`, ROUND_HALF_EVEN).
5. Максимальное паросочетание в двудольном графе; выбор среди равных — как в определениях: ошибки в порядке
   Unicode `issue_id`, каждая берёт наименьший индекс вывода, сохраняющий максимальность. Повторы остаются
   отдельными FP.
6. `F1 = 2TP/(2TP+FP+FN)` (оба пустые → 1; эталон пуст, ответ нет → 0);
   `reward = clip(2·F1 − 1 − 0.002·inspection_steps, −1, 1)` вычисляется через `Fraction`, без округления;
   inspection_steps = все шаги до submit (включая ошибочные); submit учитывается только в лимите 100 действий.

## Адаптер жюри (`judge_adapter.py`)

Единая точка подключения из определений проверок. Рабочая директория в образе: `/app`; ничего доустанавливать не
нужно. Пример: `docker run --rm --network none finaudit python -c "import judge_adapter as j; print(j.make_env())"`.

| Точка входа | Поведение |
|---|---|
| `generate_episode(seed, config, output_dir)` | генератор команды → `output_dir/public/{manifest.json, ledger.csv, invoices.jsonl, payments.jsonl, fx.csv, policy.json}` и `output_dir/private/{truth.json, provenance.json, generation.json}`; `config` — конфиг команды (`configs/*.json`) или `{"team_config": {...}}` |
| `make_env()` → `reset(seed, config)` | `config = {"mode": "closed" \| "train", "episode_dir": ..., "team_config": {...}}`; с `episode_dir` загружается ровно этот эпизод (без перегенерации и смены ID); первое observation `{"task", "manifest", "policy", "remaining_steps": 100}` |
| `step({"name": ..., "args": {...}})` | имена `list_records(table, cursor, limit)`, `get_record(table, id)`, `get_document(doc_id)`, `calculator(expression)`, `submit(findings)`; observation `{"result", "error": null \| {"code", "message"}, "remaining_steps"}` |
| результаты | `list_records` → `{"records", "next_cursor"}`; `get_record`/`get_document` → объект записи/документа; `calculator` → десятичная строка (`"0.3"` для `0.1+0.2`); `submit` → `{"accepted": true}` или ошибка `INVALID_FINDINGS`, никогда не сигнал правильности |
| закрытый режим | любая награда 0 (и на завершении), `info` = только `{"steps_used"}`; истинную награду хранит оценщик |
| лимиты | 100 действий включая submit; 100 исследовательских действий → `truncated`, пустые findings; 60 с от `reset` (время политики включено) → `truncated`, пустые findings |
| `score_episode(episode_dir, findings, inspection_steps)` | `{"tp", "fp", "fn", "precision", "recall", "f1", "return"}`; невалидная структура → `return = -1`, остальные поля null, причина — в stderr (журнал оценщика) |

Таблицы: `ledger` (ID `row_id`), `invoices` и `payments` (ID `doc_id`; также принимаются `invoice_id`/`payment_id`),
`fx` (ID `fx:DATE:SRC:TGT`). Типы ошибок (кейс §02 → наш `type`): дубли счетов → `DUPLICATE_INVOICE`;
пропущенное/частичное распределение платежа → `PAYMENT_ALLOCATION`; неверная дата или курс конвертации →
`FX_CONVERSION`; неверный отчётный период → `PERIOD_CUTOFF`. Сценарии взаимодействия: `I1`, `I2` (см. выше).
Коды ошибок: `UNKNOWN_ACTION`, `BAD_ARGS`, `UNKNOWN_TABLE`, `NOT_FOUND`, `BAD_CURSOR`, `LIMIT_TOO_LARGE`,
`BAD_EXPRESSION`, `EPISODE_DONE`, `INVALID_FINDINGS`. Для парных проверок жюри правит копию каталога эпизода
(ID в открытых файлах, truth и provenance); загрузчик не зависит от хешей файлов или формата ID.
Новые ID должны быть уникальны во всех пространствах имён (`get_record` разрешает `doc_id` раньше псевдонимов
`invoice_id` / `payment_id`); полный список полей с ID — в `docs/JURY.txt`. Хеши `generation.json` и шаблоны ID
верификатора команды на таких правленых копиях ожидаемо не сойдутся; загрузка и оценка их не используют.
Лимит 60 с проверяется на каждом `step`; политику, которая больше не вызывает `step`, останавливает вызывающая сторона.
Только блоки жюри: `docker run --rm --network none finaudit python -m pytest -q tests/test_judge_adapter.py
tests/test_jury_matcher.py tests/test_hostile_input.py`.

## Измеренные сбои (найдено → причина → исправление → повторная проверка)

Перед сдачей среда была прогнана через `judge_adapter.py` и eval-runner с враждебным вводом. Каждый сбой ниже
воспроизведён, исправлен и перепроверяется `tests/test_hostile_input.py` (тесты падают на v1.2.0 и проходят сейчас).

| Измеренный сбой (v1.2.0) | Причина | Исправление |
|---|---|---|
| Курсор из `"["` × 1 100 (base64) заставлял `step` выбрасывать `RecursionError` вызывающему | `decode_cursor` не ловил `RecursionError` | перехват → `BAD_CURSOR`; любое неожиданное исключение обработчика → ограниченная `BAD_ARGS`, шаг всё равно засчитан |
| Агент, пишущий `{` без перевода строки или засыпающий действиями без чтения, вешал eval-runner дольше 60 с (убит на 120 с) | блокирующие `readline` / `stdin.write` на pipe | неблокирующие чтение/запись с дедлайном эпизода → `truncated`, пустые findings |
| Строка агента `"["` × 100 000 или целое из 5 000 цифр обрывала эпизод без оценки | ловился только `JSONDecodeError` | `ValueError`/`RecursionError` → неверное действие (ограниченная ошибка) |
| `reset` на копии без `private/truth.json` → `KeyError`; `step` до `reset` → `AttributeError` | не было защит | закрытый режим загружается с пустым truth (оценка — через `score_episode`); понятные `RuntimeError` / `FileNotFoundError` |

## Базовые политики (`finaudit/policies/`)

`oracle` (только для оценщика, читает truth, нужен `--allow-oracle`), `reconciler` (наивная сверка: дубли, период
по UTC-дате, распределение без курсов, без проверок FX — намеренно попадает в ловушки), `random_explorer`
(5–60 случайных допустимых действий, 0–3 случайных вывода), `flag_all` (каждый документ × каждый тип).
Результаты: `REPORT.txt`.

## Конфигурации

`configs/*.json` (у всех есть `config_version`). Отсутствующие ключи берут значения по умолчанию — в том числе
опущенные типы ошибок (`count [0, 2]`) и взаимодействия (`[0, 1]`), поэтому для эпизода с одним типом остальные
типы нужно явно обнулить (готовые рецепты D01–D20 — в `docs/JURY.txt`); `errors.<TYPE>` принимает `{"count": n}`,
`{"count": [a, b]}` или сокращения `n` / `[a, b]`; ключи, не описывающие данные (`mode`, `episode_dir`, `seed`,
`description`, …), при генерации игнорируются. Базовая валюта: любая из KZT, USD, EUR, GBP, JPY (при null —
случайная из первых трёх); часовой пояс: любой из шести в `world.TZ_POOL`. `reset(seed=None)` означает seed 0.

## Воспроизводимость

Один `random.Random` на эпизод с seed из `sha256(seed | канонический хеш config | ENV_VERSION | attempt)`; в
генерации нет часов, `hash()` и обхода множеств; везде канонический JSON; база часовых поясов зафиксирована
пакетом `tzdata`. `transform(episode, perm_seed)` перемешивает все таблицы и переименовывает все ID — награда
oracle не меняется (20/20 в `make jury`). Seed должны быть секретными и высокоэнтропийными (например, 64 бита):
генератор публичный, поэтому маленький или последовательный seed (как сданные 1001–1010) можно перебрать по
открытым данным гораздо быстрее 60 с. Seed train/dev открыты намеренно.

Версия данных и правил (`ENV_VERSION`) — 1.2.0: каждый байт эпизодов, награда, допуски, схемы и лимиты не
менялись; поверх добавлены исправления устойчивости из раздела «Измеренные сбои» и памятка жюри `docs/JURY.txt`.

Лицензия: MIT.
