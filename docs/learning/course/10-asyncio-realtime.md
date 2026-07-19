# Глава 10. asyncio, WebSocket и realtime

## Результат

Realtime — это не «быстро», а своевременное согласование нескольких
независимых участников при задержках, разрывах, повторах и гонках.

После главы ты сможешь:

- различать concurrency и parallelism;
- точно объяснять coroutine, Task, event loop и точку переключения;
- проектировать cancellation, timeout и ownership задач;
- находить async race даже в одном потоке;
- строить snapshot + event/reconnect protocol;
- рассуждать о heartbeat, дедупликации, backpressure и multi-instance.

## Входной прогноз

```python
counter = 0

async def increment():
    global counter
    before = counter
    await asyncio.sleep(0)
    counter = before + 1

await asyncio.gather(increment(), increment())
print(counter)
```

Предскажи результат. Если event loop выполняет один Python-фрагмент за раз,
откуда берётся гонка?

## 1. Concurrency не parallelism

**Concurrency** — несколько работ находятся в прогрессе и чередуются.
**Parallelism** — работы физически исполняются одновременно на нескольких
ядрах/процессорах.

Один asyncio event loop обычно выполняет одну Python-task за раз. На `await`,
если результат не готов, task приостанавливается, loop запускает другую.
Именно поэтому I/O concurrency эффективна: вместо ожидания сети поток делает
полезную работу.

```text
Task A: CPU ─ await DB ............ CPU
Task B:       CPU ─ await socket .... CPU
Task C:             CPU ─ await timer .. CPU
```

Если между `await` много CPU или blocking `time.sleep`, все полосы стоят.

## 2. Coroutine и Task

Вызов `async def` создаёт coroutine object; он ещё не обязан выполняться:

```python
coro = run_combat_timer_worker()
```

`await coro` выполняет и ждёт завершения. `asyncio.create_task(coro)` планирует
конкурентное выполнение и возвращает Task — handle результата/ошибки/отмены.

Каждая созданная task должна иметь владельца:

- кто ждёт её результат;
- кто отменяет;
- куда попадает исключение;
- когда task считается завершённой.

Fire-and-forget без strong reference и наблюдения ошибки — потерянный
lifecycle. В `lifespan` owner сохраняет `timer_task`, отменяет и await на
shutdown.

## 3. Переключение и гонка

Между двумя `await` Python-код task исполняется без кооперативного
переключения на другую task этого loop. Но state, прочитанный **до** `await`,
может устареть **после** него.

```python
if match.turn == requested_turn:
    await external_call()
    match.apply(plan)  # предпосылка уже может быть ложной
```

Решения зависят от источника истины:

- переставить await за atomic state transition;
- lock для in-memory critical section;
- transaction/optimistic version в БД;
- повторная проверка после await;
- idempotent command.

`asyncio.Lock` защищает только tasks одного процесса. Он не закрывает второй
uvicorn instance или DB writer; VladStone использует DB version.

## 4. Cancellation и timeout

`task.cancel()` запрашивает отмену. На ближайшем cancellable await внутрь
обычно бросается `CancelledError`. Корутине нужен `finally` для cleanup, после
чего она должна пробросить отмену, если нет очень особой причины её поглотить.

```python
try:
    while True:
        await tick()
finally:
    await close_resource()
```

Timeout — policy ожидания, не гарантия, что удалённая операция перестала
выполняться. После client timeout сервер мог commit. Поэтому retry требует
idempotency key/version, а не предположения «раз ответа нет — эффекта нет».

Современный Python:

```python
async with asyncio.timeout(2):
    await operation()
```

После timeout приведи локальное состояние к ясному виду и реши, можно ли
повторять.

## 5. Фоновый timer worker VladStone

```text
lifespan owns worker Task
  → sleep tick interval
  → new DB Session
  → SELECT planning matches
  → per match:
       ruleset/readability/deadline
       resolve
       optimistic commit
  → after commits: WS broadcasts
```

Три fault-containment границы:

1. `CancelledError` останавливает worker при shutdown;
2. ошибка одного match rollback'ит его и не теряет batch;
3. неожиданная ошибка tick логируется, бесконечная task живёт.

Commit выполняется до broadcast. Если broadcast падает, state остаётся в БД,
а клиент восстановится через snapshot/polling. Обратный порядок мог бы
показать недолговечный result.

## 6. WebSocket application protocol

`/ws/matches/{id}`:

1. HTTP Upgrade и авторизация cookie;
2. ruleset/deadline gate;
3. accept и подписка в match channel;
4. начальный `match.snapshot`;
5. ping → pong;
6. `match.updated` после резолва;
7. disconnect cleanup.

WebSocket доставляет frames по живому соединению, но не гарантирует
application-level «клиент обработал событие ровно один раз». Соединение может
оборваться после server send и до client processing.

## 7. Snapshot, events и reconnect

Надёжная модель:

- **snapshot** отвечает «каково authoritative состояние сейчас?»;
- **events** отвечают «как анимировать переход?»;
- envelope связывает `match`, `resolved_turn`, `last_sequence`, `events`;
- client dedupe key предотвращает повтор playback;
- последние events хранятся в match state, чтобы reconnect после резолва не
  получил eventless final snapshot.

```text
DB state truth
   ├─ HTTP GET / lazy resolve
   ├─ WS snapshot/update
   └─ polling fallback
          ↓
одинаковый resolution envelope
```

Нельзя полагаться только на event log без snapshot: пропуск/смена version
может сделать восстановление невозможным. Нельзя полагаться только на snapshot
для UI-анимаций: промежуточные причинные переходы потеряны.

## 8. Heartbeat, reconnect и backoff

Ping/pong обнаруживает мёртвое соединение, но интервалы и timeout должны быть
согласованы с proxy/network. Reconnect:

- exponential backoff;
- jitter, чтобы клиенты не вернулись одной волной;
- верхний cap;
- немедленный authoritative snapshot после connect;
- отмена старых timers/listeners.

Polling fallback — graceful degradation: хуже latency/нагрузка, но игра
остаётся корректной.

## 9. Backpressure

Текущий `_broadcast` последовательно await'ит каждый socket. Если один клиент
медленный, он задерживает остальных. Варианты будущего:

- per-connection bounded queue + sender task;
- timeout send;
- coalescing snapshots;
- disconnect chronic slow consumer;
- concurrency с контролем исключений.

Нельзя просто `gather` бесконечно: fan-out создаёт память/tasks, порядок и
ошибки требуют policy. Bounded queue заставляет выбрать: блокировать, терять
промежуточное update или отключать клиента.

## 10. Multi-instance

In-memory `dict[match_id, sockets]` видит только соединения процесса. При двух
instances worker A не может напрямую broadcast socket'у в B. Нужен общий
канал (например, Redis pub/sub/streams) или routing/ownership.

Redis pub/sub доставляет online subscribers, но сам по себе не durable event
log. Источником истины остаётся БД/snapshot; pub/sub — wake-up/notification.

## PRIMM

### Predict

1. Что случится, если в worker заменить `await asyncio.sleep(1)` на
   `time.sleep(1)`?
2. Что случится, если broadcast сделать до commit?
3. Клиент получил один envelope через HTTP и WS. Что предотвращает двойную
   анимацию?

### Run

Запусти тесты worker/reconnect, затем локальный бой. В DevTools отключи
соединение и наблюдай polling/reconnect. До опыта запиши ожидаемую
последовательность.

### Investigate

Прочитай `main.py`, `combat_timer_worker.py`, `combat_turn_timers.py`,
`match_channels.py`, `routes/ws.py`, frontend `matchRealtime.ts`. Нарисуй
ownership каждой task/socket/session/timer.

### Modify

В отдельном мини-файле воспроизведи lost update входного примера. Исправь
сначала `asyncio.Lock`, затем версией состояния. Объясни, почему lock не
подходит multi-process.

### Make

Спроектируй per-socket bounded queue:

- размер;
- кто создаёт sender task;
- shutdown;
- overflow policy для snapshot/update;
- сохранение порядка;
- метрики slow consumer.

Не внедряй без отдельной задачи: это открытый архитектурный риск.

## Самопроверка

1. Coroutine object и Task — в чём разница?
2. Где task может уступить loop?
3. Почему один поток не исключает async race?
4. Что гарантирует `cancel()`, а что `await task`?
5. Почему commit до broadcast?
6. Зачем и snapshot, и events?
7. Почему Redis pub/sub не становится источником истины?

<details>
<summary>Ответы</summary>

1. Coroutine — приостанавливаемое вычисление; Task планирует его и хранит
   lifecycle/result.
2. На await, когда ожидаемое не готово, и в framework-controlled точках.
3. Предпосылка, прочитанная до await, устаревает, пока работает другая task.
4. Cancel запрашивает отмену; await подтверждает завершение и наблюдает
   outcome/cleanup.
5. Наружу нельзя сообщать state, который ещё может откатиться.
6. Snapshot восстанавливает truth, events объясняют/анимируют переход.
7. Он обычно недолговечен и не даёт позднему subscriber полную truth; БД и
   snapshot переживают пропуск.

</details>

## Мастерство

На бумаге разыграй: deadline, одновременный `/ready`, worker, HTTP retry, WS
disconnect и reconnect. Для каждого await/commit отметь возможный interleave.
Зачёт: ровно один durable resolve, клиент восстанавливается, двойной playback
не возникает.

- **+1:** task/cancellation.
- **+3:** race trace.
- **+7:** reconnect protocol.
- **+14:** multi-instance/backpressure design.

Углубление:
[asyncio conceptual overview](https://docs.python.org/3/library/asyncio.html),
[Tasks and cancellation](https://docs.python.org/3/library/asyncio-task.html),
[FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/),
[MDN WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API).
