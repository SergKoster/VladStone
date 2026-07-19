# Глава 8. SQL, PostgreSQL и транзакции

## Главная идея

База данных — конкурентный хранитель инвариантов, а не persistence-словарь.
ORM удобна только после понимания таблиц, запросов, индексов и транзакций.

После главы ты сможешь:

- моделировать сущности ключами, constraints и отношениями;
- писать `SELECT`, `JOIN`, aggregate и изменения;
- объяснять план запроса и роль индекса;
- рассуждать об atomicity, isolation и конкурентных аномалиях;
- понимать разницу SQLite dev и PostgreSQL prod;
- проводить границу колонок и JSON.

## Входной сценарий

Два запроса одновременно выдают награду за один match. Код сначала делает
`SELECT`, не находит награду, затем оба делают `INSERT`.

Почему проверка `if not exists` не гарантирует уникальность? Какой механизм
должен быть последним арбитром?

## 1. Relation и ключ

Таблица — множество строк одного отношения. Primary key стабильно
идентифицирует строку. Foreign key связывает существование. Constraint
задаёт истину, которую обязаны соблюдать все writers.

В проекте:

```text
users(id PK, email UNIQUE)
auth_identities(user_id FK, provider, provider_user_id,
                UNIQUE(provider, provider_user_id))
combat_reward_claims(user_id FK, match_id,
                     UNIQUE(user_id, match_id))
combat_matches(id PK, owner_user_id FK, status, state_json, version, ...)
```

Unique reward constraint делает повторную/конкурентную выдачу наблюдаемым
конфликтом на общей точке истины. Application check полезен для сообщения, но
constraint закрывает гонку.

## 2. SQL мыслит наборами

```sql
SELECT id, status, updated_at
FROM combat_matches
WHERE owner_user_id = :user_id
  AND status IN ('planning', 'resolving')
ORDER BY updated_at DESC;
```

Логический порядок понимания:

```text
FROM/JOIN → WHERE → GROUP BY → HAVING → SELECT → ORDER BY → LIMIT
```

Пример aggregate:

```sql
SELECT owner_user_id, COUNT(*) AS active_count
FROM combat_matches
WHERE status IN ('planning', 'resolving')
GROUP BY owner_user_id
HAVING COUNT(*) > 3;
```

Не вытаскивай все строки в Python ради фильтра/aggregate, которые БД умеет
выполнить ближе к данным.

## 3. JOIN и cardinality

```sql
SELECT u.email, p.nickname
FROM users AS u
JOIN player_profiles AS p ON p.user_id = u.id;
```

Перед JOIN предскажи cardinality:

- один user → максимум один profile из-за `player_profiles.user_id UNIQUE`;
- user без profile исчезнет при INNER JOIN;
- LEFT JOIN сохранит user и даст NULL profile.

Неверное ожидание cardinality создаёт дубли, неверные суммы и N+1 запросы.

## 4. Индекс

Индекс — дополнительная структура для поиска/порядка с ценой:

- место на диске/в памяти;
- работа на INSERT/UPDATE/DELETE;
- обслуживание и статистика.

Полезен, когда predicate/order/join начинается с подходящих колонок и
селективность оправдывает обход. Индекс на boolean/низкокардинальное поле
может не помочь. Composite index `(owner_user_id, status, updated_at)` имеет
порядок; это не три независимых индекса.

Проверяй `EXPLAIN (ANALYZE, BUFFERS)` в PostgreSQL на безопасной среде.
`ANALYZE` реально выполняет query — не применяй бездумно к изменяющим
командам/production.

## 5. Транзакция

ACID:

- **Atomicity:** всё или ничего;
- **Consistency:** constraints переводят допустимое состояние в допустимое;
- **Isolation:** конкурентное выполнение имеет определённые гарантии;
- **Durability:** подтверждённый commit переживает сбой в рамках гарантий БД.

```text
BEGIN
  update match
  insert reward claim
  insert audit log
COMMIT
```

До commit изменения не являются окончательным внешним фактом. При исключении
Session требует rollback, чтобы вернуться к используемому состоянию.

### Isolation mental model

PostgreSQL по умолчанию READ COMMITTED: каждый statement видит snapshot на
начало statement. Два чтения в одной транзакции могут увидеть разное после
чужого commit. Более сильный уровень меняет аномалии и цену, но не заменяет
constraints/locking.

Типичные аномалии:

- lost update;
- non-repeatable read;
- phantom;
- write skew.

VladStone закрывает lost update матча optimistic version: UPDATE содержит
условие старой версии; второй writer изменяет 0 строк, ORM поднимает
`StaleDataError`.

## 6. MVCC очень кратко

PostgreSQL хранит версии строк, чтобы readers и writers меньше блокировали друг
друга. Snapshot определяет видимую версию. Старые версии позже убирает VACUUM.
Отсюда важность коротких транзакций: долгая транзакция удерживает старый
snapshot, мешает уборке и держит ресурсы.

Не держи транзакцию открытой во время внешнего HTTP/долгого WebSocket send.

## 7. SQLite и PostgreSQL — не одно и то же

SQLite прекрасна для локальной простоты, но различаются:

- типизация и некоторые SQL-функции;
- concurrency/locking;
- timezone/JSON;
- DDL и migrations;
- isolation details;
- query planner.

Зелёный SQLite-тест не доказывает PostgreSQL-correctness. Критичные migration,
locking, constraint и query behavior требуют integration-теста на Postgres
перед production.

## 8. Колонки или JSON

`combat_matches` выносит `status`, owner, winner, timestamps и version в
колонки, а быстро меняющееся battle state хранит JSON text.

Выноси в колонку, если поле:

- участвует в частом filter/join/order/constraint;
- независимо обновляется;
- требует DB-типа/индекса;
- нужно для lifecycle без парса старой schema.

JSON хорош для эволюционирующего агрегата, который грузится целиком. Цена:
слабее DB constraints, сложнее partial query/update/migration и совместимость
старых форматов. Ruleset gate — компенсационный механизм.

## Разобранный пример: ровно одна награда

Надёжная последовательность:

1. попытаться создать claim с `(user_id, match_id)`;
2. unique constraint выбирает единственного победителя;
3. winner обновляет награду/профиль в той же транзакции;
4. loser обрабатывает conflict как «уже выдано», а не повторяет side effect;
5. commit делает оба факта атомарными.

Если сначала начислить coins, а claim вставить потом вне транзакции, crash
между ними создаст повторяемую награду.

## PRIMM

### Predict

Для `users LEFT JOIN player_profiles` с двумя users и одним profile предскажи
строки. Затем добавь `WHERE p.nickname = 'A'`: останется ли user без profile?

### Run

На dev SQLite только для чтения посмотри schema и выполни SELECT активных
матчей. Не меняй живые данные. Лучше используй temporary/test DB.

### Investigate

Открой `app/db/models.py`. Для каждого unique/FK/index ответь, какой режим
отказа он закрывает. Найди поле, которое индексировано, но не unique.

### Modify

В temporary DB создай `reward_claims` с/без unique. Двумя Session/соединениями
воспроизведи логическую гонку или хотя бы два последовательных insert.
Сравни место обнаружения ошибки.

### Make

Спроектируй таблицы PlayerDeck:

- stable id/owner;
- список 12 card ids без дублей;
- ровно одна active deck;
- version/timestamps;
- FK и unique constraints.

Предложи минимум две модели (deck_cards rows против JSON/array), сравни query,
constraints и миграции. Сверь игровые инварианты с документами; не выбирай
новые правила.

## Самопроверка

1. Почему application `if not exists` не заменяет unique?
2. Чем WHERE отличается от HAVING?
3. Что надо предсказать перед JOIN?
4. Почему индекс не бесплатен?
5. Что видит READ COMMITTED?
6. Как version закрывает lost update?
7. Когда JSON state оправдан и чем оплачен?

<details>
<summary>Ответы</summary>

1. Между check и insert другой writer может пройти; constraint сериализует
   общую истину.
2. WHERE фильтрует строки до grouping, HAVING — группы после aggregate.
3. Cardinality и судьбу отсутствующих связей.
4. Занимает место и замедляет writes/maintenance.
5. Snapshot на начало каждого statement, не обязательно один на всю
   транзакцию.
6. UPDATE succeeds только при старой version; второй writer не находит строку
   этой версии и получает conflict.
7. Для целиком загружаемого быстро меняющегося агрегата; платим constraints,
   queryability и эволюцией формата.

</details>

## Мастерство

Спроектируй PlayerDeck, напиши пять SQL queries и три конкурентных сценария.
Зачёт: инварианты держатся в БД, а не только комментариями Python; объяснён
план Postgres integration checks.

- **+1:** ACID и reward race.
- **+3:** JOIN/cardinality задачи.
- **+7:** index review одного query.
- **+14:** schema design с constraints без ORM.

Углубление:
[PostgreSQL tutorial](https://www.postgresql.org/docs/current/tutorial.html),
[Transactions](https://www.postgresql.org/docs/current/tutorial-transactions.html),
[MVCC](https://www.postgresql.org/docs/current/mvcc.html),
[Indexes](https://www.postgresql.org/docs/current/indexes.html),
[SQLBolt](https://sqlbolt.com/) для тренировки синтаксиса.
