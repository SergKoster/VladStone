# CODEX — ревью проекта VladStone от 2026-07-08

## Что проверялось

Это ревью текущей рабочей копии проекта: документы, backend, frontend, тесты,
CI, Docker/deploy и краткосрочный backlog.

Прочитаны:

- `AGENTS.md`
- `README.md`
- `TODO.md`
- `docs/DESIGN.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/DESIGN_QUESTIONS.md`
- `docs/PLAYTEST_NOTES.md`
- `docs/COMBAT_REWORK.md`
- `docs/UX_DETAILS.md`

Тесты, линтеры и frontend build не запускались: пользователь явно попросил
ничего не менять, а такие команды могут создать кэши и артефакты. Это статический
код-ревью проход по файлам на диске.

На момент ревью рабочее дерево уже было с незакоммиченными изменениями:

- изменён `.claude/launch.json`
- изменён `TODO.md`
- изменён `VladStoneWeb/src/features/battle/Battle.tsx`
- изменён `VladStoneWeb/src/features/collection/Collection.tsx`
- изменён `docs/PLAYTEST_NOTES.md`
- новый `AGENTS.md`
- новый `VladStoneWeb/src/features/collection/CardDetail.tsx`

Отчёт учитывает текущее состояние файлов, включая эти изменения.

## Короткий вывод

Проект сейчас находится между двумя состояниями:

1. Рабочий MVP боя: 3 колонки x 5 рядов, один герой/башня на сторону,
   `player` против `bot`, фиксированная тестовая колода.
2. Новый дизайн боя v4: 5x5, 5 башен, стойки, статусы, заклинания, эффекты,
   новый фазовый резолвер.

Backend для MVP выглядит крепко: сервер авторитетен, порядок колоды скрыт,
combat events действительно ведут анимации, есть таймерный дорезолв,
WebSocket-каналы и оптимистическая блокировка гонки резолва.

Главная проблема сейчас — рассинхрон документов и кода. Часть документов уже
говорит “v4 заморожен, начинаем реализацию”, часть всё ещё описывает старую
боёвку как текущий канон, а код пока остаётся старым MVP.

Самые опасные зоны перед деплоем друзьям:

- backend боевых эндпоинтов допускает анонимные матчи;
- публичная telemetry пишет произвольные payload в `.dev` без лимитов;
- email-code verify можно брутфорсить;
- `RULESET_VERSION` есть, но не проверяется;
- frontend-анимации пока предполагают, что HP в ходе только уменьшается, а v4
  требует лечение/рост HP;
- ascension и монеты всё ещё активны, хотя дизайн уже говорит их убрать/считать
  placeholder.

## Текущее фактическое состояние проекта

### Backend

Фактическая модель боя:

- поле: `BOARD_ROWS = 5`, `BOARD_COLS = 3`;
- у игрока есть один `HeroState`, не 5 башен;
- `MatchState.players` уже список, но логика всё ещё завязана на `"player"` и
  `"bot"`;
- `player_deck` и `player_hand` лежат на уровне матча, не внутри `PlayerState`;
- состояние бота — `bot_spawn_count` на уровне матча;
- текущий каталог — 11 карт, у всех временные статы `1`;
- состояние матча хранится JSON-блобом в `combat_matches.state_json`;
- `CombatMatchRecord.version` уже есть и используется для защиты от гонки
  резолва.

Ключевые места:

- `VladStoneAPI/app/domain/combat/constants.py:1`
- `VladStoneAPI/app/domain/combat/models.py:88`
- `VladStoneAPI/app/domain/combat/models.py:129`
- `VladStoneAPI/app/domain/combat/models.py:146`
- `VladStoneAPI/app/domain/combat/cards.py:3`
- `VladStoneAPI/app/domain/combat/cards.py:27`
- `VladStoneAPI/app/db/models.py:145`

### Frontend

Фактический frontend:

- React/Vite SPA с экранами auth, dashboard, collection, battle, profile;
- бой восстанавливает активный матч, подключает WebSocket и имеет polling
  fallback;
- есть auto-submit расстановки перед дедлайном;
- в анимациях есть watchdog, re-entrancy guard, generation-token и стабильная
  сортировка юнитов по id для фикса двойной коллизии;
- добавлен `CardDetail`, но CSS для него не добавлен;
- i18n пока частичный: маленький `t`-объект, большая часть текста в компонентах.

Ключевые места:

- `VladStoneWeb/src/main.tsx:33`
- `VladStoneWeb/src/features/battle/Battle.tsx:190`
- `VladStoneWeb/src/features/battle/Battle.tsx:276`
- `VladStoneWeb/src/features/collection/Collection.tsx:15`
- `VladStoneWeb/src/features/collection/CardDetail.tsx:47`
- `VladStoneWeb/src/i18n.ts:1`

## Расхождения документов и кода

### 1. Канон боёвки сейчас описан по-разному

`AGENTS.md` говорит: дизайн боёвки v4 заморожен, начинаем реализацию, первый
шаг — фикс анимационного конвейера.

`COMBAT_REWORK.md` описывает v4 как актуальный план: 5x5, 5 башен, стойки,
эффекты, порядок реализации.

`DESIGN.md` при этом всё ещё говорит, что текущий канон — реализованное поле
3x5, а 5 башен “не промотано в канон до плейтеста”.

Код соответствует старому MVP, не v4.

Ссылки:

- `AGENTS.md:18`
- `AGENTS.md:19`
- `AGENTS.md:20`
- `docs/DESIGN.md:61`
- `docs/DESIGN.md:66`
- `docs/DESIGN.md:115`
- `docs/DESIGN.md:122`
- `docs/COMBAT_REWORK.md:308`
- `docs/COMBAT_REWORK.md:962`
- `VladStoneAPI/app/domain/combat/constants.py:1`
- `VladStoneAPI/app/domain/combat/models.py:88`

Что сделать:

- решить, что сейчас главный канон: `COMBAT_REWORK.md` или старый раздел
  `DESIGN.md`;
- если v4 уже заморожен, перенести базовые решения v4 в `DESIGN.md`, а старые
  правила пометить как “текущая реализация, будет заменена”.

### 2. “Первый шаг — фикс анимаций” уже выглядит сделанным

`AGENTS.md` и `COMBAT_REWORK.md` всё ещё называют фикс анимационного конвейера
первым шагом. Но `TODO.md` и `PLAYTEST_NOTES.md` уже говорят, что корневые
причины найдены и устранены. В `Battle.tsx` действительно есть новые защитные
механизмы.

Ссылки:

- `AGENTS.md:18`
- `docs/COMBAT_REWORK.md:900`
- `TODO.md:28`
- `TODO.md:34`
- `docs/PLAYTEST_NOTES.md:63`
- `VladStoneWeb/src/features/battle/Battle.tsx:276`
- `VladStoneWeb/src/features/battle/Battle.tsx:782`

Что сделать:

- пометить P0.1 как завершённый;
- явно указать следующий фокус: тайминги итераций, стилизация подробной карточки,
  drag-and-drop, подсветка зон.

### 3. Roadmap отстаёт от нового плана v4

`ROADMAP.md` всё ещё говорит: плейтесты -> модель участников -> движок
способностей. `COMBAT_REWORK.md` уже добавляет P0-фронтовую полировку и P1:
закрыть C1-C5, сделать `RULESET_VERSION`-гейт, затем модель участников.

Ссылки:

- `docs/ROADMAP.md:25`
- `docs/ROADMAP.md:30`
- `docs/COMBAT_REWORK.md:891`
- `docs/COMBAT_REWORK.md:898`
- `docs/COMBAT_REWORK.md:910`
- `docs/COMBAT_REWORK.md:914`

Что сделать:

- оставить `ROADMAP.md` как крупный план, но добавить, что точный порядок
  реализации боёвки теперь задаёт `COMBAT_REWORK.md` §20.

### 4. Возвышение отключено по дизайну, но включено в коде и UI

`DESIGN.md` и `ROADMAP.md` говорят: возвышение отключить, коллекция = карта +
количество копий. В коде всё ещё есть `/me/collection/{card_id}/ascend`, кнопка
“Возвысить” и тест, который проверяет успешное возвышение.

Ссылки:

- `docs/DESIGN.md:167`
- `docs/DESIGN.md:230`
- `docs/ROADMAP.md:60`
- `docs/ARCHITECTURE.md:95`
- `docs/ARCHITECTURE.md:304`
- `VladStoneAPI/app/api/routes/me.py:46`
- `VladStoneWeb/src/features/collection/Collection.tsx:18`
- `VladStoneWeb/src/features/collection/Collection.tsx:43`
- `VladStoneAPI/tests/test_auth.py:35`

Что сделать:

- до R1 скрыть UI, закрыть или feature-flag route, поменять тесты;
- колонки БД можно пока оставить, проблема именно в доступности механики.

### 5. Монеты за бой всё ещё реальная награда

Дизайн говорит, что экономика монет открыта, а текущая награда монетами —
placeholder. Roadmap говорит убрать монеты как награду за бой. Сейчас код
выдаёт 5 монет за победу и 1 за поражение, а UI показывает это в result overlay.

Ссылки:

- `docs/DESIGN.md:251`
- `docs/DESIGN.md:253`
- `docs/ROADMAP.md:81`
- `docs/ARCHITECTURE.md:357`
- `VladStoneAPI/app/domain/combat/board.py:31`
- `VladStoneAPI/app/services/rewards.py:25`
- `VladStoneWeb/src/features/battle/Battle.tsx:989`
- `VladStoneWeb/src/i18n.ts:16`
- `VladStoneWeb/src/i18n.ts:17`

Что сделать:

- либо временно явно подписать это как dev-placeholder;
- либо до более широкого плейтеста убрать начисление и UI монет.

### 6. Deck builder и колода 12 карт ещё не реализованы

Дизайн требует R1 deck builder: 12 карт, без дублей, серверная валидация.
Сейчас используется предсобранная тестовая колода из каталога, а рука/колода
хранятся прямо в `MatchState`.

Также текущий каталог содержит 11 карт, а дизайн стартовой коллекции говорит
про 12+ карт.

Ссылки:

- `docs/DESIGN.md:194`
- `docs/DESIGN.md:196`
- `docs/DESIGN.md:198`
- `docs/ROADMAP.md:57`
- `docs/ROADMAP.md:58`
- `VladStoneAPI/app/domain/combat/models.py:146`
- `VladStoneAPI/app/domain/combat/deck.py:7`
- `VladStoneAPI/app/domain/combat/cards.py:27`

Что сделать:

- не начинать deck builder параллельно с v4, если сейчас фокус на боёвке;
- но в документах держать его как явный релизный блокер, а не “почти есть”.

### 7. README устарел про Google OAuth

`README.md` говорит, что пока работает только локальный dev-вход через Google-
кнопку, а настоящий OAuth ещё нужно сделать. `ROADMAP.md` и `DEPLOY.md` говорят,
что реальный Google OAuth уже реализован и включается env-переменными.

Ссылки:

- `README.md:106`
- `README.md:108`
- `docs/ROADMAP.md:86`
- `docs/DEPLOY.md:38`

Что сделать:

- обновить README: dev-login работает локально, реальный OAuth уже есть и
  включается через `GOOGLE_OAUTH_*`.

### 8. i18n пока только зачаток

Документы говорят, что все строки фронта должны быть вынесены в каталог.
Сейчас `i18n.ts` покрывает только малую часть интерфейса, остальные строки
лежат прямо в компонентах.

Ссылки:

- `docs/DESIGN.md:308`
- `docs/ARCHITECTURE.md:155`
- `docs/ARCHITECTURE.md:306`
- `docs/ROADMAP.md:94`
- `VladStoneWeb/src/i18n.ts:1`
- `VladStoneWeb/src/features/battle/Battle.tsx:869`
- `VladStoneWeb/src/features/collection/CardDetail.tsx:82`

Что сделать:

- считать i18n не реализованным, а начатым;
- при выносе строк сначала брать auth, battle, result overlay и ошибки.

## Код-ревью: важные находки

### High: боевые эндпоинты доступны без авторизации

`POST /combat/start` принимает отсутствие refresh-cookie и создаёт матч с
`owner_user_id=None`. `_get_authorized_record` разрешает доступ к матчам без
owner. WebSocket делает ту же проверку.

Frontend показывает игру только после логина, но backend это не enforcing.
В production это даёт возможность анонимно создавать матчи, грузить БД и
таймер-воркер, а также открывать/резолвить любой anonymous match при знании id.

Ссылки:

- `VladStoneAPI/app/api/routes/combat.py:59`
- `VladStoneAPI/app/api/routes/combat.py:65`
- `VladStoneAPI/app/api/routes/combat.py:128`
- `VladStoneAPI/app/api/routes/combat.py:270`
- `VladStoneAPI/app/api/routes/ws.py:20`
- `VladStoneAPI/app/api/routes/ws.py:22`
- `VladStoneWeb/src/main.tsx:135`

Что сделать:

- требовать auth для настоящих `/combat/start`, `/combat/{id}`,
  `/combat/resolve` и WS;
- оставить `/combat/demo` или local-only anonymous mode отдельно;
- добавить rate limit на старт/резолв до публичного теста.

### High: telemetry публичная и пишет произвольные данные в `.dev`

`POST /telemetry/client-events` без авторизации пишет payload в `.dev`.
Нет лимита размера, rate limit, проверки environment, allowlist событий или
ротации. Боевые routes тоже пишут dev-логи независимо от окружения.

Это риск заполнения диска и мусорных логов на проде.

Ссылки:

- `VladStoneAPI/app/api/routes/telemetry.py:9`
- `VladStoneAPI/app/api/routes/telemetry.py:11`
- `VladStoneAPI/app/services/dev_logging.py:9`
- `VladStoneAPI/app/services/dev_logging.py:12`
- `VladStoneAPI/app/api/routes/combat.py:73`
- `VladStoneAPI/app/api/routes/combat.py:148`
- `VladStoneWeb/src/shared/apiClient.ts:32`

Что сделать:

- выключать dev logging вне `environment=local` или заменить на bounded
  structured logging;
- добавить лимиты размера и частоты;
- telemetry либо закрыть auth, либо принимать только маленький allowlist событий.

### High: email-code verify можно брутфорсить

Это уже записано в `ARCHITECTURE.md`, и код подтверждает риск. Rate limit есть
на запрос кода, но не на verify. У `EmailLoginCode` нет счётчика попыток.
Плюс providers скрывает email-login в production, но сами routes
`/auth/email/request` и `/auth/email/verify` всё равно существуют.

Ссылки:

- `docs/ARCHITECTURE.md:379`
- `VladStoneAPI/app/api/routes/auth.py:42`
- `VladStoneAPI/app/api/routes/auth.py:57`
- `VladStoneAPI/app/api/routes/auth.py:62`
- `VladStoneAPI/app/services/auth.py:29`
- `VladStoneAPI/app/db/models.py:44`

Что сделать:

- rate limit на verify по email/IP;
- счётчик попыток на коде, например 3-5 ошибок и код сгорает;
- в production отключить email-code routes, пока нет провайдера и защиты.

### High: `RULESET_VERSION` есть, но не используется как защита

Версия правил записывается в матч, но старые матчи не отклоняются при новом
коде. Перед v4 это критично: старый JSON-матч может попасть в новый resolver.

Ссылки:

- `docs/ARCHITECTURE.md:373`
- `docs/COMBAT_REWORK.md:860`
- `docs/COMBAT_REWORK.md:914`
- `VladStoneAPI/app/domain/combat/constants.py:5`
- `VladStoneAPI/app/domain/combat/factory.py:92`
- `VladStoneAPI/app/domain/combat/models.py:129`

Что сделать:

- до v4 добавить gate: если `match.ruleset_version != RULESET_VERSION`, матч
  корректно завершается/истекает, а клиент получает понятное сообщение.

### Medium/High: WS connect может дорезолвить ход без broadcast другим клиентам

HTTP routes после deadline-resolve делают broadcast. Timer worker тоже делает
broadcast. Но `ws.py` при подключении может сам дорезолвить просроченный матч,
закоммитить его и отправить snapshot только новому сокету. Уже подключённые
сокеты этого матча `match.updated` не получат.

Для текущего PvE это терпимо, но для PvP/reconnect может оставить второго
клиента в устаревшем состоянии. На frontend polling выключен, когда realtime
подключён.

Ссылки:

- `VladStoneAPI/app/api/routes/ws.py:26`
- `VladStoneAPI/app/api/routes/ws.py:28`
- `VladStoneAPI/app/api/routes/ws.py:34`
- `VladStoneAPI/app/api/routes/combat.py:122`
- `VladStoneAPI/app/api/routes/combat.py:137`
- `VladStoneAPI/app/services/combat_timer_worker.py:22`
- `VladStoneWeb/src/features/battle/Battle.tsx:202`

Что сделать:

- если WS connect дорезолвил матч, после commit разослать update;
- или убрать дорезолв из WS connect и доверить это worker/HTTP path.

### Medium: новый CardDetail почти наверняка визуально сломан

`Collection.tsx` добавил кнопку `.card-open` и `CardDetail`. Сам `CardDetail`
использует классы `.card-detail-*`, `.coverage-grid`, `.coverage-cell`.
В `styles.css` этих классов нет.

Из-за глобальных стилей `button` карточка в коллекции может выглядеть как
зелёная кнопка, а detail view — как обычный неоформленный блок, не модалка.

Ссылки:

- `VladStoneWeb/src/features/collection/Collection.tsx:35`
- `VladStoneWeb/src/features/collection/CardDetail.tsx:47`
- `VladStoneWeb/src/features/collection/CardDetail.tsx:94`
- `VladStoneWeb/src/styles.css:28`
- `VladStoneWeb/src/styles.css:193`

Что сделать:

- добавить стили для detail modal;
- сбросить button-стили для `.card-open`;
- проверить desktop/mobile скриншотом.

### Medium: animationState пока несовместим с v4-heal

`animationState.ts` прямо говорит, что HP в ходе только уменьшается, и зажимает
значение через `Math.min`. Документы v4 уже требуют heal/HP-up события и
немонотонный HP.

Сейчас это не баг MVP, но это обязательный фикс до эффектов лечения.

Ссылки:

- `docs/ARCHITECTURE.md:77`
- `docs/COMBAT_REWORK.md:818`
- `docs/COMBAT_REWORK.md:927`
- `VladStoneWeb/src/features/battle/animationState.ts:6`
- `VladStoneWeb/src/features/battle/animationState.ts:16`
- `VladStoneWeb/src/features/battle/animationState.ts:35`

Что сделать:

- разделить event-семантику damage/heal;
- убрать общий “min HP wins” после появления heal;
- добавить replay fixtures/тесты на damage, death, heal.

### Medium: `player`/`bot` хардкод влияет не только на бой, но и на награды

Это известно в документах, но важно: `finish_match_if_needed` ищет `"player"`
для расчёта награды, а `rewards.py` пишет result как win/loss по
`winner_id == "player"`.

Ссылки:

- `docs/ARCHITECTURE.md:267`
- `docs/ARCHITECTURE.md:343`
- `VladStoneAPI/app/domain/combat/lifecycle.py:36`
- `VladStoneAPI/app/domain/combat/lifecycle.py:38`
- `VladStoneAPI/app/services/rewards.py:31`
- `VladStoneAPI/app/api/routes/combat.py:179`

Что сделать:

- вынести награды из combat domain в service layer;
- domain должен возвращать winner/team/result, а user reward должен считаться
  по реальным participant/user связям.

### Medium: dashboard показывает коллекцию как 2/2

На главной метрика коллекции захардкожена как `Math.min(collectionCount, 2) / 2`.
Сейчас каталог уже 11 карт, а релизная цель — 20-30.

Ссылки:

- `VladStoneWeb/src/features/dashboard/Dashboard.tsx:23`
- `VladStoneAPI/app/domain/combat/cards.py:27`
- `docs/DESIGN.md:150`

Что сделать:

- временно убрать метрику или показывать реальные owned/catalog counts.

### Medium: access token выдаётся, но нигде не используется

Auth response возвращает `access_token`, но backend проверяет только
refresh-cookie, а frontend не хранит и не отправляет access token.

Ссылки:

- `VladStoneAPI/app/api/schemas.py:25`
- `VladStoneAPI/app/services/auth.py:68`
- `VladStoneAPI/app/api/routes/auth.py:67`
- `VladStoneAPI/app/api/routes/combat.py:22`
- `VladStoneWeb/src/api.ts:8`

Что сделать:

- либо убрать access token из контракта до необходимости;
- либо реализовать настоящий bearer-token flow.

### Low/Medium: realtime сейчас отбрасывает сообщения, если клиент busy

`matchRealtime.ts` игнорирует любое сообщение, если `isBusy()` true. Сейчас это
защита от двойного проигрывания. Для будущего PvP/reconnect, возможно, нужен
не drop, а “latest pending update”.

Ссылки:

- `VladStoneWeb/src/features/battle/matchRealtime.ts:43`
- `VladStoneWeb/src/features/battle/Battle.tsx:190`
- `VladStoneWeb/src/features/battle/Battle.tsx:535`

Что сделать:

- перед PvP определить очередь/буфер одного последнего server state.

## Тестовое покрытие

Хорошо покрыто:

- базовые правила боя;
- deck cycle;
- старт/резолв боя через API;
- active match restore;
- deadline auto-resolve;
- базовый WebSocket snapshot/update;
- гонка резолва через optimistic lock;
- auth и Google OAuth happy/failure paths.

Не хватает:

- frontend-тестов анимационного конвейера;
- browser/screenshot-проверок battle/collection/card detail;
- теста на запрет anonymous combat в production;
- теста на rate limit verify email-code;
- теста на `RULESET_VERSION` mismatch;
- теста на лимиты telemetry/dev logging;
- тестов heal/HP-up поведения до v4;
- тестов card lifecycle disablement (`is_active`);
- тестов deck builder, потому что его ещё нет.

## Blindspot pass

### 1. Нужна явная политика публичных API

Перед показом друзьям стоит расписать, какие endpoints:

- public;
- требуют auth;
- доступны только local/dev;
- доступны только admin.

Минимально:

- public: health, catalog, Google OAuth login/callback;
- auth required: profile, collection, combat start/get/resolve/ws;
- local-only: dev-login, email-code dev response, verbose dev logs;
- bounded/guarded: telemetry.

### 2. Нужны retention и cleanup

Сейчас есть истечение active matches, но не видно политики для:

- finished/expired matches;
- reward claims;
- audit logs;
- `.dev` logs;
- telemetry.

Если публичные/анонимные endpoints останутся, это быстро станет проблемой БД
и диска.

### 3. Нужна production observability, не только dev telemetry

Sentry, structured logging и понятные animation error reports лучше считать
частью подготовки к friend test, а не поздней полировкой. Иначе “у друга
завис бой на телефоне” будет трудно расследовать.

### 4. Детерминированный replay/debug ещё не до конца спроектирован

Сейчас порядок колоды хранится в state после shuffle, этого достаточно для
живого матча. Но нет seed, по которому можно воспроизвести матч из начальных
условий. v4 документы уже требуют явный seed для рандома.

До способностей стоит решить, что является источником replay:

- полные snapshots;
- combat events;
- seed + submitted intents;
- или комбинация.

### 5. API/frontend контракт может начать расходиться

TS-типы в `VladStoneWeb/src/api.ts` поддерживаются вручную. v4 добавит много
event types и state fields. Ручная синхронизация легко сломает анимации.

Стоит подумать о generated types из OpenAPI или хотя бы о payload fixtures,
которые используются и backend tests, и frontend tests.

### 6. Политика вечного `card_id` требует технических ограждений

Документы правильно говорят: `card_id` вечен. Но пока нет проверок, которые
поймают удаление/переименование карты или потерянный арт.

Полезные ограждения:

- test/check на стабильность ids;
- check “все catalog cards имеют ожидаемые assets или сознательный fallback”;
- release checklist для изменений карт.

### 7. Mobile acceptance нужно проверять реально

Документы говорят, что мобильная полировка важнее десктопа. CSS уже
адаптивный, но нет регулярной проверки узкого viewport. Battle, hand, result
overlay, card detail и auth нужно смотреть на телефоне/эмуляции до friend test.

### 8. PvP privacy надо проектировать вместе с participant model

Текущий `owner_user_id` годится для solo PvE. PvP требует модель “этот user —
участник матча и видит только свою руку/колоду”, а не “у матча один владелец”.

Это лучше решить вместе с R12, а не во время invite flow.

### 9. Бэкапы без restore drill — слабая защита

Документы уже упоминают Postgres backups. Нужно добавить проверку восстановления.
Бэкап, который ни разу не восстанавливали, может оказаться бесполезным в момент
аварии.

### 10. Нужны feature flags / local-only gates

То, что удобно локально, опасно на проде:

- anonymous combat;
- dev-login;
- email-code без провайдера;
- verbose dev logs;
- telemetry endpoint;
- placeholder coins;
- ascension.

Лучше сделать явные settings-флаги, чтобы release build случайно не утащил
dev-поведение наружу.

## Рекомендуемый следующий порядок

1. Сначала синхронизировать документы:
   - отметить P0.1 animation fix как done;
   - решить и записать, v4 уже канон или ещё draft;
   - выровнять `DESIGN.md`, `ROADMAP.md`, `COMBAT_REWORK.md`, `TODO.md`,
     `AGENTS.md`.
2. До любого более широкого деплоя:
   - закрыть anonymous combat;
   - ограничить/gate telemetry и dev logs;
   - закрыть brute-force email verify;
   - добавить `RULESET_VERSION` mismatch handling.
3. Завершить P0 frontend polish:
   - стили `CardDetail`;
   - тайминги итераций;
   - drag-and-drop расстановки;
   - подсветка зон.
4. Потом идти в P1 backend:
   - закрыть C1-C5;
   - participant model;
   - per-player deck/hand;
   - награды вне старых `player`/`bot` предположений.

