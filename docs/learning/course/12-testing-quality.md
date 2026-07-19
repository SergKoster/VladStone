# Глава 12. Тестирование, статический контроль и CI

## Результат

Тест — исполняемое утверждение о поведении, а не доказательство отсутствия
всех багов. Хорошая стратегия выбирает самый дешёвый уровень, на котором
нужный риск наблюдаем.

После главы ты сможешь:

- формулировать test oracle из инварианта;
- различать unit/domain, integration, contract и end-to-end;
- использовать pytest fixtures, parametrize и test doubles;
- писать детерминированные тесты времени и конкуренции;
- оценивать coverage по риску, а не числу строк;
- понимать границы ruff, type checker, build и CI.

## Входной прогноз

Есть тест:

```python
def test_resolve():
    state = make_state()
    resolve(state)
    assert state.turn == 2
```

Он зелёный. Какие баги всё ещё возможны: двойная награда, утечка чужой руки,
недетерминированный порядок событий, race двух writers, PostgreSQL migration,
WS payload? Какой уровень нужен каждому?

## 1. Тест начинается с риска

Формула:

```text
Риск → наблюдаемое обещание → минимальная среда → вход → oracle
```

Пример:

```text
Риск: два resolver тихо перезапишут один match.
Обещание: второй commit получает conflict, state первого сохраняется.
Среда: реальная SQLAlchemy Session + test DB, две Session.
Oracle: StaleDataError и stored.turn == winner.turn.
```

Если тест не может красным показать риск, он проверяет не то.

## 2. Уровни

| Уровень | Что реально | Что подменено | Хорош для |
|---|---|---|---|
| Pure unit/domain | Python rules | DB/network/clock часто параметры | переходы, инварианты, combinatorics |
| Component/application | service + несколько adapters | внешние провайдеры | orchestration, transaction policy |
| DB integration | ORM + реальная DB | остальная сеть | constraints, query, migration, locks |
| HTTP contract | FastAPI/TestClient + schema | реальный socket/browser | status, auth, serialization |
| Realtime/E2E | запущенные процессы/browser | мало | handshake, reconnect, full wiring |

Пирамида — не закон количества. Чем выше тест, тем дороже диагностика и
нестабильнее среда; но нижний тест не проверяет wiring. Выбирай слой по риску.

Текущие API tests на temporary SQLite не являются PostgreSQL integration
suite. Это явная дыра для prod-specific поведения.

## 3. Arrange, Act, Assert

```python
def test_second_writer_loses():
    # Arrange: две Session видят одну version
    # Act: first commits, second attempts commit
    # Assert: second raises; durable state = first
```

Один тест может иметь несколько assert одного обещания. Не прячь act внутри
fixture так глубоко, что непонятно, что проверяется. Имя описывает behavior,
не implementation: `test_second_writer_gets_stale_data_error...`.

## 4. Fixtures

Fixture управляет setup/teardown и зависимостями:

```python
@pytest.fixture
def match():
    return create_v4_battle(...)
```

Yield-fixture:

```python
@pytest.fixture
def resource():
    value = acquire()
    yield value
    release(value)
```

Scope выбирай осторожно. Shared mutable session/module fixture создаёт
зависимость порядка. Каждый тест должен быть изолирован или явно работать с
immutable expensive setup.

`tests/conftest.py` проекта изолирует DB process-wide через уникальный
temporary file и ранний env. Но он не удаляет файл в teardown и сохраняет
`ENVIRONMENT=local` ради dev flows — это конкретные компромиссы, которые надо
понимать.

## 5. Parametrize и таблицы решений

```python
@pytest.mark.parametrize(
    ("turn", "expected"),
    [(1, "planning"), (15, "planning"), (...)]
)
def test_timer_policy(turn, expected):
    ...
```

Parametrize хорош, когда меняются данные, а обещание и путь одинаковы. Если
каждый case требует другого объяснения/fixture, отдельные тесты яснее.

Для state machine строй decision table: state × command × expected transition/
error. Это ловит пропущенные ветви лучше случайных примеров.

## 6. Test doubles

- **Stub** возвращает заданные данные.
- **Fake** имеет упрощённую рабочую реализацию, например in-memory store.
- **Mock/spy** проверяет взаимодействия.

Подменяй внешнюю недетерминированность/дороговизну, не саму логику под тестом.
Mock ORM calls часто цементирует implementation и не проверяет SQL. Для
repository contract полезно прогнать один набор тестов против fake и
SQLAlchemy implementation.

## 7. Время

`sleep` в тесте делает его медленным и flaky. Передавай `now`:

```python
resolve_expired_planning_match(db, record, now=fixed_time)
```

Текущий service уже принимает `now`. Это пример design for testability:
policy времени становится pure comparison. Интеграционный тест самого worker
может отдельно проверить tick/lifecycle.

## 8. Конкуренция без лотереи

`test_combat_resolve_race.py` не надеется случайно попасть в race:

- два Session заранее загружают одну version;
- первый commit детерминированно побеждает;
- второй commit обязан упасть.

API test monkeypatch'ит момент competitor update внутри resolve, создавая
конкретный interleaving. Это лучше ста потоков «пока иногда не упадёт».

Ограничение: такой тест доказывает выбранный interleaving и ORM behavior на
SQLite, но не все production races.

## 9. Regression test

Порядок фикса:

1. минимально воспроизвести симптом;
2. написать тест, который падает по правильной причине;
3. сделать минимальный fix;
4. убедиться, что тест зелёный и старые проверки живы;
5. при необходимости добавить higher-level contract test;
6. удалить временную instrumentation.

Тест должен пережить рефакторинг и умереть, когда обещание больше не нужно.

## 10. Property и metamorphic thinking

Даже без Hypothesis полезно формулировать свойства:

- порядок `ctx.units` не меняет canonical JSON;
- mana всегда в диапазоне;
- один unit на cell;
- viewer B никогда не видит hand A;
- повтор claim не меняет coins второй раз;
- равный initial state + intents даёт равный resolution.

Property-based framework генерирует cases и shrink'ит counterexample, но
oracle/invariant всё равно проектируешь ты. Не добавляй зависимость без
согласованной задачи; сначала можно параметризовать важные границы.

## 11. Quality gates

- Ruff ловит выбранные lint rules: syntax/import/style/bug patterns.
- Pytest проверяет исполняемые examples/properties.
- `npm run build` проверяет TypeScript и bundle frontend.
- Static type checker Python сейчас отдельным CI gate не настроен.
- Code review проверяет смысл, maintainability, threats, migration/release.
- CI воспроизводит известные команды в чистой среде.

Зелёный CI означает «эти проверки прошли на этом commit», не «система
правильна». В CI только push main и PR; branch/local gaps тоже учитывай.

## Разобранный пример: viewer-safe payload

Минимальный набор уровней:

1. pure payload test: viewer получает свою hand, у другого пусто, counts есть;
2. HTTP test: auth user не получает чужое через route;
3. WS test/contract: snapshot и update используют тот же viewer policy;
4. security review: никакое другое поле/snapshot event не содержит deck.

Один happy-path API test легко пропустит утечку в event snapshots.

## PRIMM

### Predict

Для багов выбери минимальный уровень: validator accepts half-cell; unique
reward; Caddy не проксирует WS; React дважды проигрывает envelope; resolver
недетерминирован.

### Run

Запусти:

```powershell
.\.venv\Scripts\python -m pytest tests/test_combat_resolve_race.py -q
.\.venv\Scripts\python -m ruff check .
```

До запуска запиши, какой риск каждая команда **не** проверяет.

### Investigate

Прочитай `conftest.py` и один domain/API/race test. Для каждого заполни:
real dependencies, fakes, oracle, возможный false confidence.

### Modify

Возьми существующий domain test и добавь один boundary case через
parametrize. Сначала искусственно сломай implementation в учебной ветке и
убедись, что новый case красный; затем верни.

### Make

Для будущего PlayerDeck составь test strategy:

- pure validation matrix;
- repository contract;
- Postgres constraint/race;
- HTTP auth/error schema;
- migration upgrade/backfill;
- E2E smoke.

## Самопроверка

1. Как вывести тест из риска?
2. Почему pure test не заменяет integration?
3. Когда fixture делает тест хуже?
4. Как тестировать время без sleep?
5. Как сделать race deterministic?
6. Что такое property?
7. Что доказывает зелёный CI?

<details>
<summary>Ответы</summary>

1. Сформулировать observable promise и минимальный environment, где риск
   проявляется.
2. Не проверяет wiring, SQL/driver/constraint/network/framework behavior.
3. Когда скрывает act, делит mutable state, создаёт order dependence или
   слишком широкую среду.
4. Инъецировать clock/`now`, сравнивать policy отдельно.
5. Явно выстроить interleaving/barrier/две Session, а не надеяться на scheduler.
6. Общее утверждение для множества входов, не один example.
7. Только прохождение конкретных настроенных checks на данном commit/env.

</details>

## Мастерство

Выбери открытый backend-риск и напиши test plan с уровнями и false-confidence
анализом. Реализуй минимальный падающий тест в учебной ветке, не исправляя
production rule без задачи. Зачёт: test падает только при нарушении обещания,
а не из-за сна/порядка/живой БД.

- **+1:** уровни и doubles.
- **+3:** time/race design.
- **+7:** property set для нового модуля.
- **+14:** полный test strategy вертикального среза.

Углубление:
[pytest](https://docs.pytest.org/en/stable/),
[FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/),
[Ruff](https://docs.astral.sh/ruff/),
Brian Okken, *Python Testing with pytest*.
