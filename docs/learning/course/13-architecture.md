# Глава 13. Архитектура домена и игрового сервера

## Результат

Архитектура — распределение решений и зависимостей так, чтобы изменение имело
предсказуемый радиус. Diagram без enforcement — намерение, а не свойство.

После главы ты сможешь:

- разделять domain, application/service и adapters;
- объяснять dependency inversion через нужное поведение;
- определять transaction/aggregate boundary;
- различать domain fact, integration event и UI animation event;
- защищать server-authoritative и deterministic design;
- оценивать coupling, cohesion и стоимость абстракции.

## Входная задача

Новая карта «при розыгрыше выдаёт +1 ману». Где должны жить:

- описание эффекта;
- validation контента;
- выполнение;
- DB сохранение матча;
- HTTP intent;
- WS animation;
- frontend text?

Если ответ «в route» или «в одном классе Card», какие изменения начнут
размазываться?

## 1. Слои и направление зависимости

Упрощённая карта:

```text
API / WS adapters
        ↓
application services / orchestration
        ↓
domain combat rules

DB adapter ─ implements persistence capability
payload adapter ─ translates domain → viewer-safe transport
frontend ─ consumes public contract
```

Внутренний domain не должен импортировать FastAPI, SQLAlchemy или WebSocket.
Причина не эстетическая:

- rules тестируются без I/O;
- transport/storage можно менять отдельно;
- доменная модель не принимает случайные lifecycle semantics фреймворка;
- dependency direction следует от volatile details к stable rules.

Проверь enforcement:

```powershell
rg -n "fastapi|sqlalchemy|WebSocket" `
  VladStoneAPI\app\domain\combat\engine
```

Нулевой результат — конкретное архитектурное свидетельство.

## 2. Domain, application, adapter

**Domain** отвечает: какой ход легален и какой state следует.

**Application service** отвечает: загрузить какой агрегат, вызвать какое
правило, в какой transaction, что делать при conflict, когда публиковать.

**Adapter** переводит внешний протокол: HTTP/Pydantic, SQLAlchemy, WS JSON.

Пример resolve:

```text
route validates transport/current user
service loads match / handles deadline + transaction
domain resolve_v4_turn(state, intents) → state + facts
repository saves
commit
payload translates viewer-safe response
channel broadcasts
```

В текущем коде route местами сам выполняет значительную orchestration. Это
нормальный MVP-компромисс, но при PvP/нескольких входах duplication подскажет
выделить application use case.

## 3. Aggregate и transaction boundary

Aggregate — согласованный кластер domain objects с одним входом изменения.
`BattleStateV4` фактически aggregate матча: players, units, turn, result,
pending plans и last events меняются согласованно и сохраняются одним JSON.

Инварианты матча проверяются внутри aggregate/resolver. Межагрегатные действия
вроде profile reward требуют application transaction и idempotency.

Не делай один aggregate «вся игра»: огромная transaction boundary увеличит
conflicts и coupling. Но разделение матча на независимо сохраняемые units без
coordination усложнит атомарный deterministic turn.

## 4. Repository и service

Repository даёт collection-like доступ к aggregates и скрывает mapping:

```python
class CombatMatchStore(Protocol):
    def get(self, match_id: str) -> CombatMatchRecord | None: ...
    def save(self, record, match) -> None: ...
```

Service/use case оркестрирует repository, domain и commit policy. Сам
repository не должен решать «выдать награду» или «просрочить ruleset», если
это application/domain policy.

Abstraction окупается, если:

- есть стабильное понятие способности;
- несколько adapters/tests используют контракт;
- она убирает volatile dependency из core.

Интерфейс для каждой функции создаёт ceremony без decoupling.

## 5. Server-authoritative

Клиент отправляет намерение, не готовый state:

```json
{"card_id":"mage","row":2,"col":1}
```

Сервер проверяет identity, turn, hand, mana, target и сам вычисляет result.
Иначе клиент может:

- прислать бесплатную карту;
- скрыть урон;
- получить другой result из-за version;
- рассинхронизировать соперников.

UI может оптимистично показать **план**, но authoritative state приходит от
сервера. Анимация строится по server events, не предсказывает outcome.

## 6. Детерминизм

Для одинакового initial state и intents resolver должен дать одинаковый
result/event order. Требования:

- полный порядок players/units/ties;
- контролируемый RNG seed и одинаковое число/порядок draws;
- отсутствие wall clock внутри pure resolution;
- canonical serialization;
- data-driven scripts с валидированным конечным словарём primitives;
- state validation на phase boundaries.

Seed недостаточен, если порядок обхода set/dict/queries различается или одна
ветка делает лишний RNG call.

Детерминизм облегчает replay, тесты, debugging и fairness. Он не означает,
что transport arrival order игнорируется: application layer фиксирует
authoritative input/version до resolver.

## 7. События: три разных смысла

- **Domain fact:** в resolution произошло `unit_damaged`, `card_drawn`.
- **Integration event:** другим bounded context надо узнать `match_finished`.
- **UI animation event:** viewer-safe данные для воспроизведения кадра.

Один объект может временно обслуживать несколько ролей, но требования
различаются: durability, privacy, versioning, audience. `message` для UI не
должен быть источником бизнес-логики; структурные `effect_kind`,
`wait_reason`, sequence безопаснее.

Event ≠ event sourcing. VladStone хранит authoritative snapshot JSON и
последний envelope; не восстанавливает всю жизнь матча только из вечного
event log.

## 8. Data-driven content

Новая карта собирается из:

- CardDefinition;
- UnitBlueprint/SpellScript;
- selector/pattern;
- конечных Effect primitives;
- validation registry.

Плюсы:

- контент отделён от engine control flow;
- можно валидировать весь каталог на startup/tests;
- меньше произвольного кода на карту;
- serialization/tooling проще.

Цена: DSL тоже язык. Нужны schema, semantics, versioning, error messages и
ограничение выразительности. Когда каждый новый эффект требует обходного
хака, либо расширяй primitive осознанно, либо признай, что модель не выражает
домен.

## 9. Ruleset version

Сохранённый JSON state зависит от code semantics. После изменения правил
старый active match может стать непарсируемым или разрешиться иначе.
`RULESET_VERSION` gate читает raw version и gracefully expires чужой формат
до current parser/resolver.

Это решение availability/product policy:

- не мигрировать живые матчи сложной evolving schema;
- не рисковать неверным result;
- честно завершить без поражения/награды;
- сохранить понятное сообщение.

Version — не замена backward-compatible API versioning для долгоживущих
клиентов, а boundary конкретного state machine.

## 10. Coupling и cohesion

Высокая cohesion: модуль содержит решения одной причины изменения.
Coupling измеряй не импортами только, а знаниями:

- frontend знает mana formula? лишнее coupling;
- route знает семь фаз resolver? лишнее;
- domain знает cookie? лишнее;
- payload знает viewer privacy? правильная cohesion adapter.

Duplication иногда дешевле преждевременной общей абстракции. Объединяй, когда
видна общая policy и изменения действительно должны происходить вместе.

## Разобранный пример: скрытая deck

Инвариант проходит несколько слоёв:

1. domain PlayerState хранит deck для rules;
2. persistence сериализует полный aggregate server-side;
3. payload adapter **никогда** не включает порядок deck;
4. viewer получает свою hand, чужая скрыта;
5. event snapshots несут только counts;
6. frontend не имеет альтернативного каталога secret state;
7. tests проверяют каждый transport path.

«Не рендерить deck» на frontend не архитектурная защита.

## PRIMM

### Predict

Если domain начинает принимать `Request` FastAPI, назови четыре последствия
для tests, reuse, security и evolution.

### Run

Выполни dependency scan выше. Затем найди обратный путь imports:
routes → services/domain. Сравни фактический код с `ARCHITECTURE.md`.

### Investigate

Возьми `resolve_combat_turn`. Пометь каждую строку цветом: transport,
application, domain, persistence, integration. Где orchestration смешана и
какой реальный повтор use case оправдал бы extraction?

### Modify

На бумаге вынеси use case `ResolveCombatTurn` с входом/результатами
`Resolved | Conflict | NotFound | Forbidden`. Route только переводит HTTP.
Определи repository/clock/publisher dependencies и transaction boundary.

### Make

Спроектируй PlayerDeck vertical slice:

- domain model/invariants;
- application commands;
- repository/schema;
- HTTP contract;
- auth;
- events/observability;
- tests;
- migration/deploy.

Сверь `ARCHITECTURE §5.3`; не решай состав starter deck.

## Самопроверка

1. За что отвечает каждый из трёх слоёв?
2. Что делает BattleState агрегатом?
3. Когда repository abstraction окупается?
4. Почему server-authoritative — и security, и consistency?
5. Почему seed не гарантирует детерминизм?
6. Event log и event sourcing — разница?
7. Что защищает ruleset gate?
8. Как отличить полезную абстракцию от ceremony?

<details>
<summary>Ответы</summary>

1. Правила; orchestration/transactions; перевод внешней технологии.
2. Общие инварианты и атомарное изменение/сохранение state через один entry.
3. Когда скрывает volatile adapter за стабильной нужной core способностью.
4. Недоверенный клиент не задаёт result; все участники получают один version.
5. Нужны одинаковые order/branches/RNG calls и отсутствие внешней
   недетерминированности.
6. Facts для потребителей не означают восстановление всего state только из
   append-only log.
7. Current parser/resolver от state с другой schema/semantics.
8. Есть несколько реальных consumers/изменений общей policy; иначе только
   дополнительный переход.

</details>

## Мастерство

За 60 минут сделай architecture proposal PlayerDeck с diagram, invariants,
dependencies, transaction, failures и tests. Зачёт: domain не знает adapters,
privacy server-side, migration совместима, открытые игровые решения помечены,
а не выдуманы.

- **+1:** layers/aggregate.
- **+3:** determinism checklist.
- **+7:** classify events.
- **+14:** reverse-engineer новую feature boundary.

Углубление:
[Architecture Patterns with Python](https://www.cosmicpython.com/book/preface.html),
[Client-server game architecture](https://www.gabrielgambetta.com/client-server-game-architecture.html),
проектные [ARCHITECTURE.md](../../ARCHITECTURE.md) и
[COMBAT_REWORK.md](../../COMBAT_REWORK.md).
