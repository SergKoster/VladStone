# Глава 15. Распределённые системы, кэши и очереди

## Результат

Как только есть браузер, API и БД, система уже распределённая: сообщения
задерживаются, узлы падают независимо, часы расходятся, ответ может потеряться
после commit. Масштабирование добавляет не только throughput, но и состояния,
которых не было в одном процессе.

После главы ты сможешь:

- рассуждать о partial failure и неопределённом результате;
- проектировать idempotent command и delivery semantics;
- понимать outbox/inbox, queue и consumer retry;
- выбирать cache policy без превращения cache в случайную истину;
- объяснять границу DB lock, process lock и distributed coordination;
- спроектировать multi-instance realtime VladStone.

## Входной сценарий

API закоммитил resolve, отправил WS update, но HTTP response потерялся. Клиент
повторяет request. Был ли первый запрос успешен? Что должен сделать сервер,
если не может отличить повтор от новой команды?

## 1. Неопределённый результат

В локальной функции exception часто означает «эффекта нет». В сети timeout
означает только «ответ не пришёл вовремя»:

```text
client send
 → server computes
 → DB COMMIT
 → response lost
 → client timeout
```

Клиент не знает outcome. Поэтому:

- request имеет domain version/idempotency key;
- server хранит/выводит authoritative result;
- retry либо возвращает тот же result, либо conflict + refresh;
- side effects привязаны к durable dedupe.

## 2. Delivery semantics

Термины — свойства полного pipeline, не брокера:

- **at-most-once:** можно потерять, дубликатов обработки нет;
- **at-least-once:** retry уменьшает потери, consumer увидит дубли;
- **effectively-once effect:** дубли доставки возможны, но idempotent
  processing/dedupe создаёт один бизнес-эффект;
- «exactly once» требует очень конкретной границы и часто маркетингово
  скрывает дубли за ней.

WS update текущего процесса ближе к at-most-once notification: disconnect
теряет frame. Correctness держится snapshot/DB, не гарантией доставки.

## 3. Idempotency

Три инструмента:

1. **Natural key:** reward unique `(user_id, match_id)`.
2. **Version/precondition:** resolve только текущего `turn`/record version.
3. **Idempotency key:** client генерирует key на логическую команду; server
   хранит key + request fingerprint + outcome.

Идемпотентность должна охватывать side effects. Запись key после внешней
отправки оставляет crash window. DB changes и dedupe record лучше фиксировать
одной транзакцией.

Если тот же key пришёл с другим body — reject conflict, не возвращай старый
ответ молча.

## 4. Transactional outbox

Проблема dual write:

```text
COMMIT match
publish match.finished
```

Crash между ними: state есть, event нет. Если publish сначала — event может
сообщить state, который откатился.

Outbox:

1. в одной DB transaction записать match change и outbox row;
2. отдельный publisher читает pending rows и публикует;
3. после успеха помечает sent;
4. publish может повториться, consumer idempotent/inbox dedupe.

Outbox нужен, когда integration event должен надёжно покинуть DB boundary.
Для текущего Р1 WS update может быть недолговечным notification: GET snapshot
восстанавливает truth. Не внедряй outbox без требования durability.

## 5. Queue

Queue отделяет producer от consumer и сглаживает burst:

- producer быстро записывает job;
- bounded workers обрабатывают;
- ack после успешного эффекта;
- visibility timeout/redelivery после падения;
- dead-letter policy для poison messages;
- metrics age/backlog/retry.

Подходит для email, image compression, analytics, rewards projection.
Не подходит для синхронной команды, где пользователь обязан получить
немедленный authoritative result, если продукт не принимает async job API.

Job payload должен содержать stable ids/version, не огромный stale object.

## 6. Cache

Cache ускоряет чтение копией данных. Вопросы:

- source of truth;
- key и version;
- TTL;
- invalidation;
- miss/stampede;
- stale tolerance;
- memory bound/eviction;
- privacy/tenant separation.

Стратегии:

- cache-aside: app читает cache, на miss DB и заполняет;
- write-through: write обновляет cache вместе с storage path;
- invalidation event/versioned key;
- request coalescing/lock против stampede.

TTL ограничивает возраст, но не гарантирует согласованность. Security/hand/
ownership data с неверным cache key может утечь между users. Каталог карт —
лучший cache candidate, чем viewer-specific match payload.

Никогда не делай cache единственным местом durable reward/session, если loss
не разрешён.

## 7. Locks и coordination

- `asyncio.Lock` — tasks одного loop/process;
- thread lock — threads процесса;
- DB row/advisory lock — участники через одну DB;
- distributed lock (например Redis lease) — сложный протокол со сроком,
  fencing и failure modes.

Lease может истечь, пока старый worker ещё работает; новый получает lock, и
оба пишут. **Fencing token** — монотонная версия, которую resource отвергает,
если writer старый. Часто DB optimistic version проще и надёжнее.

Не добавляй distributed lock, если unique/version/queue partition решает
конкретный invariant.

## 8. Consistency и availability

При сетевом partition нельзя одновременно гарантировать любой read/write на
обеих сторонах и единую линейную истину для того же объекта. Но CAP не
выбирается одной галочкой «CP/AP» для всей системы; разные операции имеют
разные требования, а latency/normal-operation consistency тоже важны.

Для battle result предпочтительнее reject/delay conflicting write, чем
показать две победы. Для UI presence допустима временная stale информация.
Классифицируй invariant, не брендируй весь продукт.

## 9. Multi-instance VladStone

Проблемы при `api-1` и `api-2`:

- sockets разделены по process;
- timer workers оба находят due match;
- in-memory rate limit/heartbeat разделены;
- reconnect попадает в другой instance;
- DB connection count растёт.

Возможная архитектура:

```text
clients
   ↓ load balancer
api-1 ─ sockets A ┐
api-2 ─ sockets B ├─ Redis channel notification
                  ┘
       ↓
PostgreSQL: authoritative state + optimistic version
```

Resolve:

1. оба worker могут попытаться;
2. DB version выбирает commit winner;
3. winner публикует `match_id/turn/version`;
4. каждый instance получает notification;
5. instance перечитывает/viewer-safe payload или использует безопасный
   envelope и рассылает локальным sockets;
6. reconnect всегда получает DB snapshot.

Sticky sessions могут уменьшить cross-instance hops, но не решают restart,
worker coordination и durable truth.

## 10. Time и ordering

Wall clocks расходятся. Для expiry DB/app используют UTC, но сравнение зависит
от clock source. Для causal order лучше domain version/sequence, не timestamp.

`sequence` упорядочивает events хода. Timestamp полезен для наблюдаемости, но
два равных/переставленных network сообщения сортируют по `(turn, sequence)`.

NTP уменьшает drift, не превращает distributed clocks в один атомарный clock.

## Разобранный пример: reward

`UNIQUE(user_id, match_id)` + transaction дают effectively-once reward effect
для повторного claim через эту DB. Границы:

- если coins обновляются в другой системе без outbox/idempotency, гарантия
  обрывается;
- если код ловит IntegrityError после частичного внешнего side effect, поздно;
- если migration constraint отсутствует, Python check гоняется.

Всегда называй границу гарантии.

## PRIMM

### Predict

Классифицируй:

- WS animation update;
- reward claim;
- email send job;
- card catalog cache;
- match resolve.

Для каждого: truth, delivery semantics, duplicate policy, stale tolerance.

### Run

На бумаге разыграй два API instances и один match. Оба worker resolve. Пройди
SQL version, rollback loser, publish winner, local broadcasts.

### Investigate

Изучи `ARCHITECTURE §2.4, §6, §8.4, §8.19`. Для каждого in-memory компонента
напиши, что сломается при втором instance.

### Modify

В мини-проекте реализуй in-memory idempotency store:
`key → request_hash + response`. Проверь duplicate same body и same key/different
body. Затем объясни, почему in-memory реализация не production multi-instance.

### Make

Спроектируй durable email queue для login code:

- transaction/outbox;
- job schema;
- retry/backoff;
- provider idempotency;
- expiry;
- poison/DLQ;
- metrics;
- privacy.

Не внедряй; текущий email flow и провайдер — отдельное product/release решение.

## Самопроверка

1. Почему timeout не означает rollback?
2. At-least-once требует чего от consumer?
3. Как idempotency key обрабатывает другой body?
4. Какую crash window закрывает outbox?
5. Почему TTL не делает cache consistent?
6. Зачем fencing token?
7. Что Redis pub/sub решает, а что нет?
8. Почему timestamp слабее sequence для порядка?

<details>
<summary>Ответы</summary>

1. Server мог commit до потери/задержки response.
2. Idempotent effect или durable dedupe/inbox.
3. Reject conflict: key обозначает одну логическую команду.
4. Между commit state и publish external event.
5. Только ограничивает возраст; до expiry значение может быть stale/утечь при
   неверном key.
6. Resource отвергает writer со старым истёкшим lease.
7. Разносит notification между instances; не хранит authoritative/durable
   state и не гарантирует позднюю доставку.
8. Часы расходятся/совпадают, а domain sequence задаёт явный causal order.

</details>

## Мастерство

Спроектируй multi-instance resolve/reconnect с sequence diagram и failure
matrix: Redis down, API restart, duplicate publish, slow consumer, DB conflict.
Зачёт: DB остаётся truth, каждый retry bounded/idempotent, а animation может
деградировать без corruption.

- **+1:** delivery/idempotency.
- **+3:** outbox/cache.
- **+7:** lock/fencing.
- **+14:** multi-instance design без подсказки.

Углубление:
Martin Kleppmann, *Designing Data-Intensive Applications*;
[Redis data types and patterns](https://redis.io/docs/latest/develop/data-types/);
[PostgreSQL concurrency control](https://www.postgresql.org/docs/current/mvcc.html).
