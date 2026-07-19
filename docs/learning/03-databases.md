# Модуль 3. Базы данных: SQL, SQLAlchemy 2.0, Alembic

> Самый «профессиеобразующий» модуль для бэкендера. Цель — свободно читать и
> писать SQL, понимать ORM-слой проекта и уметь безопасно менять схему.

## Что нужно знать на выходе

- SQL: SELECT/JOIN/GROUP BY, индексы, транзакции, уровни изоляции (хотя бы
  READ COMMITTED), constraint'ы (unique, foreign key).
- Отличия SQLite и PostgreSQL и почему dev/prod у нас на разных БД (и какие
  баги из-за этого возможны).
- SQLAlchemy 2.0: engine, session, декларативные модели, `select()`-стиль
  запросов (унифицированный синтаксис 2.0 — не учить legacy 1.x стиль).
- Alembic: миграции как «git для схемы БД», autogenerate, upgrade/downgrade.
- Паттерны из нашего проекта: состояние матча как JSON-блоб (когда это
  хорошо/плохо), оптимистичная блокировка через колонку `version`,
  идемпотентность через unique constraint.

## Ресурсы

1. [SQLBolt](https://sqlbolt.com/) — интерактивный SQL с нуля; альтернатива на
   русском — тренажёр на [Stepik «Интерактивный тренажер по SQL»](https://stepik.org/course/63054/promo).
2. [SQLAlchemy 2.0 Unified Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/) —
   **главный ресурс**; официальный, большой, проходить в 2–3 захода.
3. [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html) +
   [Auto Generating Migrations](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).
4. [Пошаговый гайд: SQLAlchemy 2 + Alembic](https://dev.to/amverum/asynchronous-sqlalchemy-2-a-simple-step-by-step-guide-to-configuration-models-relationships-and-3ob3) —
   компактный сквозной пример (у нас синхронная SQLAlchemy, но структура та же).
5. [Postgres Tutorial](https://www.postgresqltutorial.com/) — по мере
   надобности, ближе к деплою.

## Где это у нас

- `VladStoneAPI/app/db/` — модели таблиц и настройка сессии. Прочитать все
  модели, сопоставить с ARCHITECTURE §2.3.
- `VladStoneAPI/alembic/versions/` — история миграций проекта; `alembic.ini` и
  `alembic/env.py` — как Alembic находит наши модели.
- `combat_matches.state_json` — JSON-блоб состояния матча: осознанное решение
  (быстрая эволюция правил без миграций), см. ARCHITECTURE §2.3 и риск §8.3.
- `combat_matches.version` + `version_id_col` — оптимистичная блокировка
  (ARCHITECTURE §8.6, тест `test_combat_resolve_race.py`).
- `combat_reward_claims` — идемпотентность наград через unique(user, match).

## Практика

1. Открыть dev-базу SQLite любым просмотрщиком (например, DB Browser for
   SQLite), посмотреть все таблицы, руками написать 3–4 SELECT'а
   (например: все матчи пользователя со статусом finished).
2. Трассировка: как `BattleStateV4` превращается в строку `state_json` и
   обратно; кто и когда коммитит транзакцию.
3. В песочной ветке: добавить в какую-нибудь таблицу тестовую колонку,
   сгенерировать миграцию autogenerate, прочитать её код, применить, откатить
   (`downgrade`), удалить ветку.
4. Разобрать гонку резолва: прочитать `test_combat_resolve_race.py` и
   объяснить сценарий «два процесса резолвят один ход» — кто выигрывает и
   почему проигравший не портит данные.
5. Ответить: почему награда за матч не может быть выдана дважды, даже если
   код вызовут два раза параллельно?

## Вопросы для самопроверки

- Чем оптимистичная блокировка отличается от пессимистичной (SELECT FOR
  UPDATE)? Почему нам хватает оптимистичной?
- Какие поля матча вынесены в колонки, а какие живут в JSON — и по какому
  принципу проведена граница?
- Что делает autogenerate и почему его вывод обязательно надо читать глазами?
- Какой известный риск у «dev на SQLite, prod на PostgreSQL»?
