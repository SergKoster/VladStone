# Глава 7. FastAPI, Pydantic и ASGI

## Результат

FastAPI связывает HTTP с Python через ASGI, type hints, Pydantic и dependency
injection. Цель — видеть полный lifecycle и знать, где нельзя смешивать
валидацию, orchestration и blocking I/O.

После главы ты сможешь:

- объяснить ASGI scope/receive/send и роль uvicorn;
- проследить request через middleware, route, dependencies и response;
- строить Pydantic v2 модели с осмысленными validators;
- управлять lifecycle через lifespan и generator dependencies;
- выбрать `def`/`async def` по фактическому I/O;
- реализовать и протестировать маленький vertical slice.

## Входной прогноз

```python
@router.post("/x")
async def x(db: DbSession):
    return db.execute(slow_sync_query()).all()
```

Что происходит с event loop во время синхронной DB query? Исправится ли это
простым превращением тела в `await db.execute(...)` при обычной sync
SQLAlchemy Session?

## 1. ASGI mental model

Uvicorn принимает сеть и вызывает ASGI-приложение примерно так:

```python
await app(scope, receive, send)
```

- `scope` описывает соединение/request: type, path, headers;
- `receive` даёт входящие события/body/WS frames;
- `send` отправляет response/frames.

ASGI поддерживает долгоживущие соединения и async lifecycle, в отличие от
старого синхронного WSGI-контракта. FastAPI строится на Starlette и добавляет
маршрутизацию по annotations, DI, validation и OpenAPI.

```text
uvicorn
 → middleware (CORS)
 → router match
 → dependency graph
 → request Pydantic validation
 → endpoint
 → response serialization
 → ASGI send
```

## 2. Создание приложения

`app/main.py`:

1. читает settings;
2. в local/test создаёт таблицы;
3. создаёт `FastAPI(..., lifespan=lifespan)`;
4. добавляет CORS middleware;
5. подключает routers;
6. module-level `app` служит entry point uvicorn.

В production миграции выполняются отдельно на старте контейнера; `init_db`
ничего не делает. `create_all` не заменяет историю миграций.

Lifespan владеет ресурсами на срок приложения. Startup «при импорте» плох:
импорт должен быть безопасен для тестов/tools, а cleanup и порядок запуска
становятся неявными.

## 3. Dependency injection

```python
DbSession = Annotated[Session, Depends(get_db)]

@router.get("/active")
def list_active_combat(db: DbSession, ...):
    ...
```

FastAPI строит dependency graph, вызывает `get_db`, передаёт yielded Session и
выполняет cleanup. Польза:

- единый lifecycle;
- переиспользование auth/config/DB;
- тестовая подмена dependency;
- endpoint описывает нужные возможности.

DI не делает код автоматически чистым. Если dependency создаёт глобальный
singleton при импорте или endpoint содержит всю бизнес-логику, coupling
остаётся.

## 4. Pydantic v2 на границе

```python
class ResolveTurnRequest(BaseModel):
    match_id: str
    turn: int = Field(ge=1)
    placements: list[PlacementRequest] = Field(default_factory=list)
    spells: list[SpellRequest] = Field(default_factory=list)
```

Pydantic:

- парсит JSON-compatible data;
- валидирует типы/constraints;
- создаёт JSON Schema для OpenAPI;
- сериализует через `model_dump`/`model_dump_json`.

`default_factory=list` создаёт новый список на instance. Validator должен
проверять локальную форму. Запрос к БД внутри validator смешивает слои,
затрудняет тесты и может выполняться неожиданно часто.

Для строгого публичного контракта реши судьбу extra fields. Pydantic по
умолчанию может игнорировать лишнее; `extra="forbid"` ловит typo, но усложняет
forward compatibility. Это контрактное решение, не универсальная настройка.

## 5. `def` или `async def`

В FastAPI:

- обычный `def` endpoint/dependency framework запускает в thread pool;
- `async def` исполняется на event-loop thread и обязан не блокировать;
- async библиотеку надо `await`;
- sync библиотека внутри `async def` не становится неблокирующей.

Текущий проект использует sync SQLAlchemy Session и местами `async def`
endpoint, потому что после DB работы нужен `await broadcast`. Синхронные DB
вызовы внутри такого endpoint потенциально блокируют event loop. Для малого
релизного масштаба это может быть приемлемым долгом, но путь к нагрузке:

- вынести sync DB section в threadpool/синхронный service с аккуратным
  ownership Session; или
- перейти на SQLAlchemy AsyncSession/async driver;
- измерить, а не механически переписать.

Нельзя передавать одну sync Session между произвольными threads/tasks:
lifecycle и thread-safety должны быть явными.

## 6. HTTPException и перевод ошибок

Endpoint — adapter: переводит транспорт в application command и доменный
результат обратно в HTTP.

```python
if payload.turn != state.turn:
    raise HTTPException(409, "Combat turn is no longer current")
```

Домену не нужен импорт FastAPI. Если чистый resolver бросает domain exception,
route/service переводит его. Не позволяй `HTTPException` протечь в
`domain/combat/engine`.

## Разобранный vertical slice: start combat

```text
POST /api/combat/start
 → router prefix /combat + app prefix /api
 → get_db yields Session
 → cookie optional
 → auth service resolves user
 → domain create_v4_battle
 → persistence creates record
 → audit record
 → db.commit
 → viewer-safe v4_combat_response
 → JSON response
 → get_db closes Session
```

Это хороший exercise на границы:

- FastAPI знает HTTP/cookie/DI;
- domain factory знает правила начального state;
- service/repository знает DB mapping;
- payload adapter знает, что можно показать viewer.

## PRIMM

### Predict

Для `turn="abc"` и отсутствующего `placements` предскажи endpoint body,
status и момент, когда route body начнёт выполняться.

### Run

Открой локальный `/docs`; найди schema `ResolveTurnRequest`. Отправь invalid
body или воспроизведи через `TestClient`. Сравни с прогнозом.

### Investigate

Проследи `/combat/start` по схеме выше. На каждом шаге ответь:

- кто создаёт объект;
- кто им владеет/закрывает;
- какое исключение может выйти;
- commit уже произошёл или ещё нет.

### Modify

В учебной ветке или отдельном мини-приложении создай:

```text
POST /debug/echo
body: {value: int 1..100}
response: {value, doubled}
```

Сначала напиши четыре TestClient-теста: min, max, 0, строка. Затем endpoint.
Не вливай debug route в продукт.

### Make

С чистого листа реализуй мини FastAPI-приложение с:

- lifespan-ресурсом;
- generator dependency;
- Pydantic request/response;
- domain-функцией без FastAPI;
- обработкой domain conflict в 409;
- тестами без реального сервера.

## Частые ошибки

- Делать runtime side effect при импорте.
- Считать DI service locator-магией и не понимать ownership.
- Писать blocking call внутри `async def`.
- Делать validator зависимым от DB/HTTP.
- Возвращать ORM object без явного viewer-safe schema.
- Смешивать domain exception и HTTP transport.
- Доверять `/docs` вместо тестов контракта.

## Самопроверка

1. Какие три аргумента концептуально получает ASGI app?
2. Что делает uvicorn, а что FastAPI?
3. Как живёт generator dependency?
4. Почему sync call блокирует `async def`?
5. Где должен переводиться domain conflict в 409?
6. Что Pydantic проверяет, а чего не знает?
7. Почему commit должен предшествовать authoritative success/broadcast?

<details>
<summary>Ответы</summary>

1. scope, receive, send.
2. Uvicorn обслуживает сеть/ASGI server; FastAPI маршрутизирует, валидирует,
   внедряет зависимости и формирует response.
3. До yield acquire, yielded value получает endpoint, after-yield/finally —
   cleanup.
4. Event loop не может переключить task, пока обычная функция не вернёт
   управление.
5. На adapter/application boundary, не в чистом домене.
6. Форму/локальные constraints; не владельца, актуальный state и правила БД/
   домена без дополнительного слоя.
7. До commit успех может откатиться; наружу ушёл бы state, которого нет в
   источнике истины.

</details>

## Мастерство

Нарисуй и защити незнакомый route от ASGI request до DB cleanup. Затем создай
vertical slice с тестами в мини-приложении. Зачёт: нет blocking-иллюзии,
домен не импортирует FastAPI, lifecycle полностью закрыт.

- **+1:** ASGI и DI flow.
- **+3:** invalid payload cases.
- **+7:** новый vertical slice без образца.
- **+14:** аудит `async def` на blocking I/O.

Углубление:
[FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/),
[Advanced guide](https://fastapi.tiangolo.com/advanced/),
[Pydantic](https://docs.pydantic.dev/latest/),
[ASGI specification](https://asgi.readthedocs.io/en/latest/specs/main.html).
