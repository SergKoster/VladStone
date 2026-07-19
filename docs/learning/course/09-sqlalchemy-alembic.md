# Глава 9. SQLAlchemy 2.0 и Alembic

## Результат

ORM отображает объекты на SQL, но не отменяет транзакции. Session — не
«подключение» и не глобальный cache, а unit of work с identity map и
transaction lifecycle. Alembic хранит историю преобразований schema.

После главы ты сможешь:

- объяснить Engine, connection pool, Session, identity map, flush и commit;
- читать SQLAlchemy 2.0 `select` и relationships;
- избегать N+1 и неявного lifecycle;
- объяснять optimistic locking VladStone;
- создавать, читать, применять и откатывать migration;
- планировать совместимую schema evolution.

## Входной прогноз

```python
with SessionLocal() as db:
    record = CombatMatchRecord(...)
    db.add(record)
    db.flush()
    print(record.id)
    raise RuntimeError
```

Строка уже попала в БД? Увидит ли её другое соединение? Останется ли она после
выхода? Чем `flush` отличается от `commit`?

## 1. Engine и Session

```text
Engine
 ├─ dialect (SQLite/PostgreSQL SQL)
 ├─ connection pool
 └─ создаёт/выдаёт DB connections

Session
 ├─ identity map: (model, PK) → Python object
 ├─ unit of work: new/dirty/deleted
 └─ transaction boundary
```

Session короткоживущая и принадлежит одному request/job. Она не thread-safe и
не должна бесконтрольно пересекать tasks. `get_db()` создаёт Session на request
и закрывает в `finally`.

`expire_on_commit=False` в проекте оставляет загруженные атрибуты доступными
после commit. Цена: Python-object может стать stale относительно чужих
транзакций; не считай его вечной истиной.

## 2. Declarative mapping

```python
class CombatMatchRecord(Base):
    __tablename__ = "combat_matches"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
```

`Mapped[T]` сообщает ORM и type tooling о persistent attribute.
`mapped_column` описывает DDL/mapping. Python default и `server_default`
различаются: первый вычисляет application, второй умеет применить БД, если
INSERT не передал значение.

Relationship — удобная object navigation, но FK/constraint живёт в schema.
Relationship без продуманной загрузки может создать N+1.

## 3. Query 2.0 style

```python
stmt = (
    select(CombatMatchRecord)
    .where(CombatMatchRecord.owner_user_id == owner_user_id)
    .where(CombatMatchRecord.status.in_(ACTIVE_MATCH_STATUSES))
    .order_by(CombatMatchRecord.updated_at.desc())
)
records = list(db.scalars(stmt))
```

Statement строит SQL expression; выполнение происходит в `db.scalars`.
Смотри сгенерированный SQL и plan при performance-вопросах. Не загружай ORM
entity, если нужен один aggregate/value.

## 4. flush, commit, rollback

- `add` регистрирует объект в unit of work;
- `flush` синхронизирует pending changes с DB в текущей транзакции, может
  получить generated id/constraint error;
- `commit` flush + фиксирует транзакцию;
- `rollback` отменяет транзакцию и восстанавливает usable Session state;
- `close` освобождает ресурсы, но не является синонимом успешного commit.

Autoflush может сработать перед query, чтобы query видел pending changes.
Поэтому constraint error может возникнуть «на чтении». Явный `flush` полезен,
когда надо проверить запись до следующих side effects.

После DB exception делай rollback перед повторным использованием Session.

## 5. Identity map и stale state

В одной Session повторный `get(Model, same_pk)` обычно возвращает тот же
Python-object. В разных Session — разные объекты одной domain identity.

`db.refresh(record)` перечитывает DB state. В обработке `StaleDataError`
VladStone делает rollback, refresh и принимает победившее authoritative
состояние.

Нельзя использовать identity map как cross-request cache: lifecycle короткий,
а согласованность ограничена транзакцией.

## 6. Optimistic locking

```python
version: Mapped[int] = mapped_column(...)
__mapper_args__ = {"version_id_col": version}
```

Два Session загрузили version 4:

```sql
UPDATE combat_matches
SET state_json = ..., version = 5
WHERE id = :id AND version = 4;
```

Первый обновил одну строку. Второй после commit первого обновляет ноль строк;
SQLAlchemy обнаруживает несоответствие ожидаемого rowcount и поднимает
`StaleDataError`. Второй обязан rollback и не broadcast свой рассчитанный
result.

Optimistic lock не предотвращает параллельный расчёт — он предотвращает
тихую потерю при записи. Это хорошо, когда conflicts редки и работа до commit
приемлема.

## 7. N+1

```python
users = db.scalars(select(User)).all()  # 1 query
for user in users:
    print(user.profile.nickname)        # возможно N lazy queries
```

Решения: explicit join, `selectinload`, `joinedload` — выбор зависит от
cardinality и объёма. Сначала включи SQL logging/метрики и посчитай queries.
Не делай eager-load всего графа «на всякий случай».

## 8. Alembic — код эволюции schema

Migration имеет `upgrade()` и `downgrade()`, revision id и parent revision.
Autogenerate сравнивает metadata с DB и предлагает diff; он не понимает
бизнес-смысл, data migration, rename и безопасный порядок deploy.

Workflow:

1. изменить model;
2. создать revision autogenerate;
3. прочитать каждую operation;
4. добавить data migration/constraints/order вручную;
5. применить на пустой и копии реальной schema;
6. проверить downgrade там, где он реально поддерживаем;
7. запустить приложение и тесты.

### Expand/contract

Для совместимого deploy:

1. expand — добавить nullable/new structure, старый код продолжает жить;
2. deploy dual-read/write или backfill;
3. переключить чтение;
4. contract — позже удалить старое.

Rename одной atomic migration может сломать старый процесс во время rolling
deploy. Даже на одном VPS полезно мыслить совместимостью и rollback.

## Разобранный пример: migration 0002

Открой `alembic/versions/0002_combat_match_version.py` и сопоставь:

- новая column `version`;
- default для существующих строк;
- model `version_id_col`;
- race regression test.

Schema без ORM-настройки — просто число. ORM-настройка без schema — код не
запустится. Тест связывает их в поведение.

## PRIMM

### Predict

Два раза `db.get(CombatMatchRecord, id)` в одной Session, затем один раз в
другой. Сколько Python objects и сколько возможных SELECT? От чего зависит?

### Run

Прогони `tests/test_combat_resolve_race.py -q`. Затем прочитай SQL-смысл теста
до деталей monkeypatch.

### Investigate

Трассируй `create_combat_match_record` → `db.add` → `audit` → `db.commit`.
Где flush может произойти неявно? Какие changes входят в одну transaction?

### Modify

В temporary учебной DB добавь простую table/model column через migration:
autogenerate, inspect, upgrade, downgrade. Не используй dev/prod DB.

### Make

Спланируй migration `PlayerDeck` из главы 8 и безопасный backfill starter deck.
Раздели schema change, data change и application deploy. Не выбирай состав
стартовых карт — это открытое решение владельца.

## Самопроверка

1. Чем Engine отличается от Session?
2. Что хранит identity map?
3. `flush` против `commit`?
4. Почему после DB error нужен rollback?
5. Что гарантирует optimistic version, а чего нет?
6. Как обнаружить N+1?
7. Почему autogenerate нельзя принимать вслепую?

<details>
<summary>Ответы</summary>

1. Engine управляет dialect/pool/connections; Session — unit of work,
   identity map и transaction lifecycle.
2. Один ORM object на `(mapping, primary key)` в пределах Session.
3. Flush отправляет SQL внутри незавершённой транзакции; commit делает её
   durable/видимой согласно isolation.
4. Transaction/Session находится в failed state и не может безопасно
   продолжать.
5. Не даёт второму writer тихо перезаписать state; не запрещает параллельный
   расчёт и не делает side effects до commit безопасными.
6. Посчитать SQL queries/log/trace на один request.
7. Он не понимает rename, данные, lock duration, deploy compatibility и
   бизнес-инварианты.

</details>

## Мастерство

На чистой temporary DB создай model + migration + query + конфликт двух
Session, объясняя каждый flush/commit. Зачёт: нет глобальной Session, migration
прочитана, conflict не создаёт внешний side effect.

- **+1:** Session lifecycle.
- **+3:** optimistic locking trace.
- **+7:** N+1 diagnosis.
- **+14:** expand/contract plan новой schema.

Углубление:
[SQLAlchemy Unified Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/),
[Session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html),
[Version counters](https://docs.sqlalchemy.org/en/20/orm/versioning.html),
[Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
[Autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).
