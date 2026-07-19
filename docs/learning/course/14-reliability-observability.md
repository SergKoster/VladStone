# Глава 14. Надёжность, наблюдаемость и производительность

## Результат

Надёжная система не «никогда не падает». Она ограничивает отказ, сохраняет
истину, обнаруживает деградацию и даёт оператору ответ, что делать. Быстрая
система измеряется под реалистичной нагрузкой, а не ощущением.

После главы ты сможешь:

- различать fault, error и user-visible failure;
- задавать SLI/SLO для важного пути;
- проектировать logs, metrics и traces как связанную диагностику;
- применять timeout, retry, backoff, jitter, bulkhead и graceful degradation;
- профилировать CPU, DB, event loop и память;
- строить безопасный capacity/load test и rollout.

## Входной сценарий

Timer worker умер, но API health возвращает 200, HTTP запросы работают, а
матчи перестали автоматически переходить по дедлайну.

Почему «процесс жив» — недостаточный health signal? Какие три наблюдения
отличат: worker умер, DB медленная, backlog растёт из-за совпавших дедлайнов?

## 1. Fault → error → failure

- **Fault:** причина внутри системы — exception одного match, slow socket,
  недоступная DB.
- **Error:** внутреннее состояние отклонилось — worker task завершилась,
  очередь переполнена.
- **Failure:** нарушено внешнее обещание — ход не resolved в допустимый срок.

Fault не обязан стать failure, если boundary сработала:

```text
unreadable match
 → per-record ValidationError
 → expire only that match
 → commit
 → worker resolves the rest
```

Надёжность строится fault containment и recovery, а не широким `except pass`.

## 2. SLI, SLO и error budget

**SLI** — измеряемый показатель. **SLO** — целевой уровень за окно.

Для VladStone важнее product paths, чем uptime процесса:

- доля ходов, resolved не позже deadline + допустимая задержка;
- p95/p99 latency `/ready`;
- доля успешных reconnect со snapshot;
- error rate auth callback;
- число double reward/conflicting truth — целевое ноль;
- backlog просроченных planning matches.

Пример учебного SLO, не утверждённая production цифра:

```text
99% ходов за 7 дней переходят из planning в resolved
не позднее X секунд после server deadline.
```

X выбирают после product expectation и load test. Не копируй число из
учебника в production.

Error budget — допустимая доля нарушения SLO. Он помогает выбирать между
новыми features и reliability work, но не разрешает security/data loss.

## 3. Health: liveness и readiness

- **Liveness:** процесс не застрял безвозвратно; restart может помочь.
- **Readiness:** instance сейчас способен обслуживать traffic.
- **Dependency/deep health:** DB/worker/backlog; использовать осторожно,
  чтобы краткий сбой зависимости не вызвал restart storm.

Текущий `/health` простой и не доказывает heartbeat worker. Открытый риск
`ARCHITECTURE §8.14` предлагает heartbeat metric. Хорошая метрика:

```text
combat_timer_last_success_timestamp
combat_timer_tick_duration_seconds
combat_timer_due_matches
combat_timer_resolved_total{outcome=...}
```

Alert строится на симптоме: timestamp старше порога **и** есть due matches.

## 4. Logs, metrics, traces

### Structured logs

Событие как поля:

```json
{
  "event": "combat.turn_resolved",
  "match_id": "m1",
  "turn": 7,
  "duration_ms": 42,
  "events_count": 12,
  "outcome": "committed"
}
```

Нужны level, timestamp, service/version, request/correlation id. Не логируй
token, code, full cookie, hidden deck или unlimited user payload.

### Metrics

Counter только растёт (`resolved_total`), gauge меняется (`ws_connections`),
histogram распределяет latency/size. Не ставь `match_id`/`user_id` label:
высокая cardinality уничтожает metrics backend; ids остаются в logs/traces.

### Traces

Trace связывает spans одного запроса:

```text
HTTP /ready
 ├─ auth lookup
 ├─ load match
 ├─ domain store plan
 ├─ DB commit
 └─ response
```

Для async deadline resolve trace может начинаться worker-ом, а correlation
идёт через match/turn. Observability должна позволять перейти
metric alert → exemplar/trace → structured logs.

## 5. Timeout, retry, backoff

Каждый внешний wait должен иметь deadline. Timeout без retry policy только
меняет вид failure.

Retry допустим, когда:

- ошибка transient;
- операция idempotent или защищена key/version;
- общий deadline ещё не исчерпан;
- backoff + jitter не создают stampede;
- число попыток bounded.

Не ретраить validation/authz/most 4xx. `409 stale turn` требует refresh state,
а не слепого повторения того же plan.

Exponential backoff:

```text
delay = min(base * 2^attempt, cap) + random_jitter
```

Jitter распределяет synchronized clients. Frontend reconnect уже имеет
exponential cap, но без jitter — после общего outage клиенты могут вернуться
синхронной волной.

## 6. Bulkhead и graceful degradation

Bulkhead отделяет ресурсы, чтобы одна нагрузка не утопила всё:

- bounded queue на WS connection;
- per-match error boundary worker;
- DB pool limits;
- rate limit telemetry/combat;
- отдельный concurrency cap expensive work.

Graceful degradation VladStone:

- WS упал → polling;
- worker задержан → lazy deadline resolve в HTTP;
- ruleset сменился → expire match, не undefined behavior;
- animation зависла → frontend watchdog до final snapshot.

Degradation корректна, если truth сохраняется; «пропустить DB commit, чтобы
ответить быстрее» — corruption, не degradation.

## 7. Performance model

Раздели:

- CPU: resolver, serialization, JSON, validation;
- I/O: DB query/commit, socket send, disk log;
- contention: DB locks/version conflicts, event loop blocking;
- memory: match state, event envelopes, socket queues;
- frontend/network payload.

Начни с budget:

```text
request latency = queue wait + app CPU + DB wait + serialization + network
```

Percentile p95/p99 важнее среднего для realtime UX. Throughput без latency и
error rate бессмыслен.

Little's Law для устойчивого участка:

```text
concurrency ≈ arrival_rate × average_time_in_system
```

Если приходит 20 requests/s и среднее время 0.2 s, в среднем около 4 in-flight.
Tail и burst требуют запаса.

## 8. Профилирование

Порядок:

1. воспроизводимый workload;
2. baseline CPU/wall/queries/memory;
3. профиль;
4. одна гипотеза;
5. изменение;
6. тот же benchmark + correctness tests;
7. сравнение и решение.

Инструменты:

- `time.perf_counter` для узкого wall-time;
- `cProfile`/`py-spy` для CPU call stacks;
- SQL logging/`EXPLAIN ANALYZE` для queries;
- event-loop lag metric для blocking;
- `tracemalloc`/process RSS для памяти;
- нагрузочный клиент с latency/errors, включая slow WS.

Не benchmark debug server с reload и не смешивай сеть/DB/CPU, если ищешь
конкретную причину.

## 9. Capacity test VladStone

До внешнего deploy нужны сценарии, а не одна цифра:

- 100–200 соединений idle + ping;
- совпавшие deadlines;
- обычные `/plan` debounce и `/ready`;
- медленный/нечитающий WS consumer;
- reconnect burst после restart;
- DB restart/latency;
- payload с максимальным легальным числом events/intents;
- soak test на утечки connections/tasks/memory.

Наблюдай latency, event-loop lag, DB pool, worker tick, backlog, CPU/RAM,
disconnect/reconnect, errors. Начинай на staging/test data, с безопасным
пределом, не на аккаунтах друзей.

## Разобранный пример: slow socket

Текущий последовательный `_broadcast`:

```text
commit done
 → send socket A (fast)
 → send socket B (stalls)
 → socket C waits
 → HTTP response or next worker match delayed
```

Truth не теряется, но latency/fairness деградируют. Diagnosis:

- span `broadcast` большой;
- per-send histogram показывает outlier;
- worker tick duration растёт;
- DB commit уже завершён;
- due backlog растёт.

Fix design — bounded per-connection sender queue/timeout — требует метрик
overflow/disconnect и теста slow consumer.

## PRIMM

### Predict

Как изменятся logs/metrics при:

1. DB slow;
2. resolver CPU spike;
3. dead worker;
4. slow WS;
5. reconnect storm?

### Run

Измерь локально время одного domain resolve и API request отдельно. Это не
production benchmark; цель — научиться разделять scope и фиксировать env.

### Investigate

Для рисков `ARCHITECTURE §8.14, §8.19, §8.20` выпиши SLI, signal и mitigation.
Проверь, что signal видит user impact, а не только exception count.

### Modify

В мини-программе добавь structured log и histogram-like сбор latency вокруг
batch. Искусственно сделай один item медленным. Покажи, почему среднее скрывает
tail.

### Make

Напиши load-test plan 100–200 CCU: workload, ramp, duration, safety stop,
metrics, acceptance, cleanup. Не запускай разрушительный тест без отдельной
подготовленной среды.

## Самопроверка

1. Fault/error/failure?
2. Чем SLI отличается от SLO?
3. Liveness против readiness?
4. Почему id нельзя metric label?
5. Когда retry опасен?
6. Что делает bulkhead?
7. Почему средняя latency скрывает UX?
8. Как доказать performance improvement?

<details>
<summary>Ответы</summary>

1. Причина; неверное внутреннее состояние; нарушенное внешнее обещание.
2. Измерение; целевое значение/окно.
3. Стоит ли restart; можно ли сейчас направлять traffic.
4. Высокая cardinality раздувает time series.
5. Неидемпотентный эффект, permanent error, нет deadline/backoff, retry storm.
6. Ограничивает область и ресурсы одного класса отказа.
7. Небольшая доля очень медленных запросов теряется; важны p95/p99.
8. Один workload/env, baseline, profile/hypothesis, correctness, повторное
   измерение и статистически/практически значимый результат.

</details>

## Мастерство

Спроектируй observability и load test для deadline resolve. Зачёт: SLO
user-facing, signals различают пять причин, labels bounded, тест имеет stop
conditions, а retry не создаёт двойной resolve.

- **+1:** signals и percentiles.
- **+3:** retry/bulkhead cases.
- **+7:** instrumentation plan.
- **+14:** capacity plan новой feature.

Углубление:
[Google SRE book](https://sre.google/sre-book/table-of-contents/),
[OpenTelemetry concepts](https://opentelemetry.io/docs/concepts/),
[Python profiling](https://docs.python.org/3/library/profile.html),
[PostgreSQL EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html).
