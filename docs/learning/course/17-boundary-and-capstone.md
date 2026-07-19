# Глава 17. Frontend-граница и выпускная работа

## Результат

Python backend-разработчик не обязан быть React-специалистом, но обязан
понимать потребителя контракта: runtime validation, network races, cache
state, reconnect и backward compatibility. Выпускная работа проверяет весь
цикл delivery, а не объём прочитанного.

После главы ты сможешь:

- читать TypeScript contract и отличать static type от runtime truth;
- понимать React state/effect/ref ровно настолько, чтобы расследовать границу;
- проектировать backend change с совместимым frontend rollout;
- выполнить feature от requirements до commit, observability и runbook;
- защитить решения как профессиональный backend-разработчик.

## Часть I. Frontend-грамотность

### Входной прогноз

```ts
export async function request<T>(path: string): Promise<T> {
  const response = await fetch(path);
  return response.json() as Promise<T>;
}
```

Проверяет ли `as Promise<T>` JSON во время выполнения? Что произойдёт, если
server удалит обязательное поле?

## 1. TypeScript исчезает в runtime

TypeScript проверяет source перед build. Browser исполняет JavaScript.
`as T` — утверждение компилятору, не parser/validator. Текущий `request<T>`
доверяет server JSON после `response.ok`.

Следствия для backend:

- OpenAPI/TS type generation полезна, но runtime schema evolution всё равно
  требует совместимости;
- новый optional field обычно безопаснее удаления/rename;
- enum variant может сломать exhaustive frontend logic;
- error body сейчас теряется: `apiClient` бросает только status;
- malformed payload даст ошибку далеко в component, если нет boundary parser.

На критичной недоверенной границе frontend может использовать runtime schema
library, но source of truth и generation strategy надо выбрать проектно.

## 2. React mental model

Component function вычисляет UI из props/state. `setState` планирует новый
render; нельзя мутировать старый state и ждать корректного reconciliation.

- `useState` — данные, влияющие на UI;
- `useEffect` — синхронизация с внешней системой после commit render;
- `useRef` — mutable identity между renders без самостоятельного render;
- cleanup effect закрывает socket/timer/listener;
- list `key` определяет identity DOM/component.

В `BattleV4` refs защищают playback от re-entrancy и хранят timers/current
match; state рисует visible UI. Backend-разработчику важно понять, почему
двойной/переупорядоченный envelope способен дважды анимироваться даже при
правильном final snapshot.

## 3. Effect race

Упрощённый resource hook:

```ts
const refresh = async () => {
  setIsLoading(true);
  const next = await load();
  setData(next);
  setIsLoading(false);
};
```

Два refresh могут завершиться не по порядку:

```text
request A (старый) ───────── response after B
request B (новый) ─ response
```

A перезапишет новое state старым. Решения: abort previous request,
generation/request id, version compare, server sequence. Backend помогает
монотонной `turn/version/sequence`, но frontend обязан применить её.

## 4. Fetch, cookie и WS

`credentials: "include"` прикладывает cookie согласно browser policy.
`deriveWsBaseUrl` преобразует:

```text
http → ws
https → wss
/api удаляется, /ws добавляется caller
```

Frontend reconnect использует exponential cap, очищает ping/reconnect timers
в returned cleanup. При connect сервер сразу даёт snapshot; `onSnapshot` и
`onUpdate` обязаны сохранять monotonicity/dedupe.

## 5. Контракт анимации

Backend обещает:

- server-authoritative final match;
- `resolved_turn`, `last_sequence`, ordered events;
- event snapshots/viewer privacy;
- структурные cause fields;
- last envelope для reconnect.

Frontend обещает:

- не вычислять исход rules;
- dedupe envelope;
- применять events по sequence;
- watchdog заканчивает в authoritative final state;
- не показывать hidden data;
- cleanup старого playback/socket.

Contract test должен проверять обе стороны schema/fixture, а E2E —
реальный replay/reconnect.

## 6. Совместимая эволюция

Предпочитай:

1. backend добавляет optional/new field и старое сохраняет;
2. frontend начинает читать новое с fallback;
3. наблюдение adoption/errors;
4. backend позже удаляет старое.

Для lockstep single deploy можно менять атомарнее, но cache старого JS,
открытая вкладка и reconnect делают клиентов временно разноверсионными.
Version/schema gate и tolerant reader всё равно нужны.

## PRIMM frontend

### Predict

Что случится, если:

- сервер добавит unknown event type;
- удалит `last_sequence`;
- пришлёт update turn 8, затем delayed turn 7;
- socket cleanup не очистит reconnect timer;
- UI отсортирует events по timestamp?

### Run

Прочитай `shared/apiClient.ts`, `matchRealtime.ts`, `serverState.ts`,
`useTurnPlayback.ts`. Для каждого async callback назови owner и stale-result
guard.

### Investigate

Проследи один `match.updated`: frame → JSON cast → callback → playback key →
React state → CSS. Отметь runtime validation, dedupe и final snapshot.

### Modify

В мини TypeScript-файле напиши type guard для простого envelope и тесты на
missing/unknown fields. Сравни `as T` и реальную проверку.

### Make

Спроектируй additive изменение event contract: новое поле причины. Дай
backend schema, old/new frontend behavior, fixtures, rollout и rollback.

### Самопроверка frontend-границы

1. Почему `as T` не защищает от сломанного JSON?
2. Как delayed response старого request может перезаписать новый state?
3. Зачем effect cleanup?
4. Что должны дать backend version/turn/sequence?
5. Почему lockstep deploy не исключает старого клиента?

<details>
<summary>Ответы</summary>

1. Assertion удаляется при компиляции и не выполняет runtime parsing.
2. Promises завершаются не в порядке запуска; без abort/generation/version
   старый callback всё ещё вызывает `setData`.
3. Закрыть socket/timer/listener прошлой версии component и не допустить
   двойных callbacks/утечек после unmount.
4. Монотонный domain order для rejection/dedupe; timestamp и arrival order
   этого не гарантируют.
5. Вкладка может оставаться открытой, а старый JS — жить в browser cache и
   reconnect после server deploy.

</details>

## Часть II. Выпускная работа

### Цель

Выбери **одну** среднюю backend-задачу из согласованного ROADMAP/TODO, которая
не требует нового игрового решения владельца. Хорошие кандидаты:

- release blocker безопасности с чётким принятым expected behavior;
- observability/heartbeat worker;
- ограничение input/body с тестами;
- reproducible Python dependencies;
- repository/application extraction в рамках реальной feature;
- Postgres integration test/migration harness.

Не бери сразу PvP, новую экономику или механику карты: там сначала нужны
решения владельца.

### Этап 0. Baseline без AI

За 45 минут:

- нарисуй текущий flow;
- назови invariants/trust boundaries;
- предскажи файлы и риски;
- запусти baseline checks;
- запиши, чего не знаешь.

Это измерит собственную модель. После baseline AI разрешён по протоколу главы
1, но финальная защита снова без него.

### Этап 1. Постановка

Одна страница:

```text
Проблема / пользовательский ущерб
In scope / out of scope
Текущее наблюдаемое поведение
Целевое поведение и acceptance criteria
Инварианты и threat model
Совместимость / migration / rollback
Signals после deploy
Открытые решения владельца (если есть)
```

Если acceptance нельзя наблюдать тестом/метрикой, уточни до кода.

### Этап 2. Design

Подготовь:

- sequence/data diagram;
- API/schema/domain changes;
- transaction и concurrency;
- failure matrix;
- test strategy по уровням;
- observability;
- rollout.

Для значимого выбора запиши мини-ADR: context, options, decision,
consequences. Не делай архитектурный фреймворк ради диплома.

### Этап 3. Vertical thin slice

Сделай самый маленький end-to-end путь, доказывающий главный риск:

1. падающий тест;
2. domain/application behavior;
3. adapter/schema;
4. integration/contract;
5. log/metric;
6. docs.

Коммиты маленькие и осмысленные. Следуй правилу репозитория: любые итоговые
изменения закоммичены, игровые правила/архитектура отражены в обязательных
документах.

### Этап 4. Adversarial review

Попытайся сломать:

- duplicate/retry;
- concurrent writer;
- stale client;
- anonymous/other user;
- max/empty/malformed input;
- dependency timeout;
- restart между side effects;
- old/new schema;
- logging secrets;
- slow consumer/backpressure.

Не все cases применимы; объясни исключённые.

### Этап 5. Проверки

Минимум проекта:

```powershell
# из VladStoneAPI
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .

# из VladStoneWeb, если затронут contract/UI
npm run build
```

Дополнительно по риску: Postgres integration, migration upgrade/downgrade,
load/smoke, security negative cases. Зафиксируй команды и результат.

### Этап 6. Handoff

Итог должен ответить:

- что изменилось для пользователя/оператора;
- какие invariants теперь доказаны;
- какие checks прошли;
- как наблюдать после deploy;
- как откатить;
- какие риски остались.

### Этап 7. Устная защита без AI

Ответь и покажи:

1. путь запроса/события;
2. transaction boundary;
3. главный race;
4. почему выбран уровень теста;
5. где runtime validation;
6. что происходит при retry после потерянного response;
7. какие данные нельзя логировать/отдавать;
8. p95/SLO signal;
9. backward compatibility;
10. самый сильный контраргумент решению.

Если не можешь объяснить строку, ты пока не владеешь изменением, даже если CI
зелёный.

## Проверка мастерства: рубрика выпускной работы

Оцени 0–2:

| Область | 0 | 1 | 2 |
|---|---|---|---|
| Requirements | размыто | happy path | наблюдаемые criteria + out of scope |
| Модель | пересказ кода | основные сущности | invariants/переходы/границы |
| Correctness | ручная проверка | unit tests | уровни по риску + race/failure |
| Security | «auth есть» | basic authz | threat model + negative cases/secrets |
| Data | ORM-магия | transaction ясна | constraints/migration/rollback |
| Reliability | exception log | retry/timeout | SLI, containment, degradation |
| Performance | «быстро» | одно измерение | workload/baseline/profile/tail |
| Delivery | код готов | CI/docs | deploy/smoke/observability/rollback |
| Объяснение | с AI/текстом | объясняет что | объясняет почему, границы, альтернативы |

Зачёт: минимум 14/18 и ни одного нуля. Через 14 дней повтори защиту по
незнакомому фрагменту; это настоящий delayed transfer test.

## Финальная самопроверка курса

Без материалов нарисуй:

```text
Browser intent
 → DNS/TLS/HTTP
 → Caddy/uvicorn/ASGI/FastAPI
 → Pydantic/DI/authz
 → application/domain
 → SQLAlchemy transaction/Postgres
 → commit
 → WS/polling envelope
 → TypeScript/React playback
 → logs/metrics/traces
```

Для каждой стрелки назови:

- контракт;
- owner;
- failure;
- retry/idempotency;
- test;
- observable signal.

Это и есть итоговая mental model Python backend VladStone.

## Дальше

После выпуска не начинай ещё десять курсов. Выбери слабую строку рубрики и
сделай 2–3 реальные задачи с feedback code review. Внешние материалы теперь
используй как справочник к конкретному пробелу:

- Python/FastAPI/SQLAlchemy/PostgreSQL official docs;
- *Architecture Patterns with Python*;
- *Designing Data-Intensive Applications*;
- *Release It!*;
- Google SRE book;
- OWASP Cheat Sheet Series.
