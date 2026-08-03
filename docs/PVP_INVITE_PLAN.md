# PvP invite — план реализации

> **Статус:** в работе (3 августа 2026). Backend PVP-1–PVP-4 и frontend
> deep-link/lobby UX PVP-5 реализованы; следующий срез — reconnect hardening.
> Цель этапа — довести существующий бой v4 до первого стабильного матча двух
> авторизованных игроков по ссылке-приглашению. Канон продукта: [DESIGN.md](DESIGN.md)
> §6.1–§6.2; место в релизе: [ROADMAP.md](ROADMAP.md), Фаза 4; целевая
> архитектура: [ARCHITECTURE.md](ARCHITECTURE.md) §5.2.

## 1. Результат этапа

Игрок A создаёт приглашение, копирует ссылку и остаётся на экране ожидания.
Игрок B открывает ссылку, при необходимости входит, присоединяется к матчу и
попадает на поле. Оба клиента:

- видят один и тот же серверный матч, но каждый — со своим `viewer_id`;
- видят только свою руку и только публичные счётчики соперника;
- независимо отправляют планы и готовность;
- получают один авторитетный резолв, когда готовы оба либо истёк дедлайн;
- могут перезагрузить страницу и вернуться именно в этот матч;
- получают понятные состояния для невалидной, просроченной, отменённой или уже
  использованной ссылки.

Первый вертикальный срез заканчивается внешним тестом в двух браузерных сессиях
и на двух устройствах. Матчмейкинг, друзья, чат, рейтинг, 2v2 и deck builder в
этот этап не входят.

## 2. Что уже готово

- `BattleStateV4` уже хранит N участников с командами, `user_id`, отдельными
  рукой, колодой и маной.
- Интент-стриминг (`/combat/plan`), готовность (`/combat/ready`), дедлайн,
  оптимистическая версия записи и timer-worker уже работают.
- HTTP/WS используют общий resolution-envelope, клиент дедуплицирует повторы,
  умеет восстанавливать один активный матч и переключаться на polling при
  разрыве WS.
- `v4_combat_response(..., viewer_id=...)` уже умеет скрывать чужую руку.
- Release blockers первого внешнего деплоя из ROADMAP закрыты.

То есть боевой движок переписывать не нужно: работа сосредоточена в lobby/
invite lifecycle, participant-aware авторизации, multi-human orchestration,
per-socket realtime и входном UX.

## 3. Найденные разрывы текущей реализации

| Область | Сейчас | Что требуется для PvP |
|---|---|---|
| Владение матчем | `combat_matches.owner_user_id` допускает одного владельца | Явное членство user ↔ match ↔ player seat |
| HTTP-авторизация | `_get_authorized_record` сравнивает только владельца | Пускать обоих участников и возвращать seat текущего пользователя |
| Выбор действующего | `/plan`, `/ready`, `/resolve` берут `human_players(state)[0]` | Применять намерение к seat авторизованного отправителя |
| Дедлайн | timer-worker передаёт план первого человека | Собирать сохранённые планы всех людей; отсутствующий план = пустой ход |
| Ранний резолв | Общее условие «все люди готовы» уже есть, но всегда ждёт bot-delay | В PvP резолвить после готовности обоих; bot-delay оставлять только матчу с ботом |
| WS | канал хранит только сокет и рассылает один payload с viewer по умолчанию | Хранить `viewer_id` у соединения и сериализовать update отдельно для каждого сокета |
| Active/reconnect | выборка идёт по `owner_user_id`, фронт берёт первый матч | Оба участника видят матч; invite-route открывает конкретный `match_id` |
| Фабрика | `create_v4_battle` всегда создаёт человек vs бот | Отдельные создание waiting-lobby и атомарная активация human vs human |
| Front routing | hash-route понимает только четыре статических имени | Deep link с непротекающим в access logs токеном и route конкретного матча |
| Случайность | монетка выводится из цифр `match_id`; shuffle использует process RNG | Персистентный случайный seed для нового PvP-матча |

## 4. Границы и решения, которые не надо придумывать в этом этапе

Подтверждённый канон: синхронный 1v1, одновременное планирование, пауз при
дисконнекте нет, AFK играет пустые ходы, отдельного AFK-штрафа нет. Поэтому
invite-система не вводит новые боевые правила.

Не блокируют первый вертикальный срез:

- **Колоды:** использовать текущую серверную дефолтную колоду. `deck_id`
  подключается позже через уже предусмотренную точку фабрики матча.
- **Награды:** не проектировать новую PvP-экономику. O1/O6 остаются открытыми;
  до решения владельца invite-flow не должен добавлять особое PvP-вознаграждение.
- **Concede:** полезный follow-up Фазы 4, но матч может корректно завершиться по
  обычным правилам/дедлайну без него.
- **Полный исторический replay:** не нужен для первого матча с другом.
  Дозагрузка оборванного текущего хода нужна в hardening-срезе ниже.

Технические значения TTL, длины токена и rate limits должны жить в config/
константах, а не дублироваться в документации. Перед реализацией UX владелец
согласует только внешний вид экрана ожидания; механика инвайта от этого не
зависит.

## 5. Целевая модель данных

### 5.1 `combat_match_participants`

Новая индексируемая проекция членства, чтобы не разбирать JSON боя ради auth и
active-query:

- `match_id` → `combat_matches.id`;
- `user_id` → `users.id`;
- `player_id` — стабильный seat из `BattleStateV4` (`p1`, `p2`);
- `team`, `joined_at`;
- unique `(match_id, user_id)` и `(match_id, player_id)`.

`PlayerState.user_id` остаётся доменной истиной внутри состояния боя, а таблица
— прикладной индекс/граница авторизации. Сервис создания и join обязан изменять
их в одной транзакции. `owner_user_id` на переходе сохраняется как создатель
матча и для совместимости, но больше не используется как единственное правило
доступа.

### 5.2 `match_invites`

- `id`, `match_id`, `created_by_user_id`;
- `token_digest` с unique index; сырой токен в БД не хранится;
- `status: pending|accepted|cancelled|expired`;
- `expires_at`, `created_at`, `accepted_at`, `accepted_by_user_id`.

Токен генерируется криптографически стойко, в БД ищется по SHA-256 digest.
Секрет нельзя писать в audit, application logs, telemetry или payload матча.
Hash-ссылка вида `/#invite/<token>` не попадает в HTTP/Caddy access logs. После
reload старую ссылку нельзя восстановить из digest: экран предлагает создать
новый токен, инвалидируя предыдущий.

### 5.3 Lifecycle

1. Create создаёт `BattleStateV4(status=waiting_for_opponent)` с seat создателя
   и пустым вторым human-seat; боевой дедлайн ещё не запущен.
2. Join под блокировкой invite/match проверяет token, TTL, статус, запрет
   self-join и членство пользователя.
3. Победитель гонки join занимает `p2`; сервис раздаёт обе стартовые руки,
   создаёт башни, ставит ману/дедлайн и переводит матч в `planning`.
4. Та же транзакция добавляет participant, помечает invite `accepted` и
   сохраняет состояние. Повтор join тем же пользователем идемпотентно
   возвращает матч; другому пользователю — `409`.
5. Cancel/expiry переводит waiting-матч в `expired`; timer-worker боевые ходы
   такого матча не резолвит.

Миграция — следующая после текущей Alembic head. Existing PvE-записи получают
participant-проекцию лениво/при миграции только для ненулевого владельца;
старые активные матчи не должны стать публичными.

## 6. API-контракт

Новый router `app/api/routes/matches.py` отделяет lobby lifecycle от боевых
намерений `/combat/*`.

| Метод | Путь | Назначение | Основные ответы |
|---|---|---|---|
| POST | `/matches/invite` | Создать waiting-матч и одноразовую ссылку | `201`: match id, token/link, expiry, lobby status |
| POST | `/matches/join` | Принять token текущим пользователем | `200`: viewer-specific combat envelope |
| GET | `/matches/{id}/lobby` | Статус ожидания для участника | waiting/active/expired без секрета |
| DELETE | `/matches/{id}/invite` | Отменить pending invite создателем | идемпотентный `204` |

Правила ошибок:

- `401` — нет авторизованной сессии во внешнем окружении;
- `403` — пользователь не участник lobby/match или отменяет чужой invite;
- `404` — невалидный токен возвращается без различия «не существовал»/
  «давно удалён»;
- `409` — self-join, invite уже принят другим пользователем, матч уже стартовал
  несовместимым способом;
- `410` — invite просрочен или отменён.

Create/join получают отдельные rate-limit buckets. Request/response schemas
ограничивают длину token/match id. API возвращает относительный share path;
публичный origin собирает фронт либо сервер из единственной настройки, без
доверия к произвольному `Host`.

## 7. Пакеты реализации

### PVP-1 — persistence и lobby factory

Файлы: `app/db/models.py`, новая Alembic migration,
`domain/combat/models.py`, `domain/combat/engine/battle.py`, новый
`services/match_invites.py`.

- Добавить таблицы, constraints и lifecycle enum.
- Разделить фабрики `create_v4_pve_battle`, `create_v4_pvp_lobby` и
  `activate_v4_pvp_battle`; старый `/combat/start` сохранить как PvE-фасад.
- Добавить персистентный `rng_seed` для PvP; одним локальным RNG честно
  определить первый spell-seat и раздать обе колоды. Seed не отдавать клиенту
  до появления отдельного replay-контракта.
- Сделать сервис create/join/cancel/expire с одной транзакционной границей.
- Просрочку применять лениво на join/lobby/active-query и ограниченным sweep в
  фоне, чтобы непрочитанные waiting-lobby не оставались активными навсегда.
- Проверить, что waiting-state проходит сериализацию, ruleset-gate и не
  выбирается timer-worker как planning.

Критерий: два разных user id атомарно превращают waiting-lobby в валидный
human-vs-human `BattleStateV4`; два конкурирующих join не занимают один seat.

### PVP-2 — participant-aware HTTP

Файлы: новый `api/routes/matches.py`, `api/schemas.py`, `main.py`,
`services/combat_matches.py`, `api/routes/combat.py`.

- Вынести helper, который по cookie + participant projection возвращает
  `(record, state, viewer_player_id)`.
- Перевести GET, active, plan и ready с owner-check/`humans[0]` на этот helper.
- `/combat/active` выбирать по participant table и сериализовать каждый матч с
  viewer конкретного пользователя.
- Ручной `/combat/resolve` не должен позволять одному PvP-клиенту досрочно
  применить пустой план соперника: оставить его только для local/PvE тестового
  пути либо направить через общий maturity-check.
- Аудит писать с actor user id и player id, не только с создателем матча.

Критерий: оба участника получают `200` и управляют только своим seat; третий
пользователь получает `403` во всех HTTP-путях.

### PVP-3 — multi-human resolution

Файлы: `domain/combat/engine/battle.py`,
`services/combat_turn_timers.py`, тесты engine/API.

- Обобщить `resolve_v4_turn` с одного `human_intents` до набора intents по
  player id; планы ботов по-прежнему строятся на сервере.
- На дедлайне собрать `pending_intents_for` для каждого human; отсутствующий
  план означает пустой ход только для этого игрока.
- Early resolve: pure PvP созревает, когда готовы все люди; bot-delay применяется
  только если в матче действительно есть бот.
- Добавить в viewer-safe payload публичный `ready` каждого участника (без
  содержимого плана); клиент не должен угадывать готовность соперника.
- Готовность/планы очищаются разом после успешного резолва; optimistic lock
  остаётся защитой от route/worker race.
- Не добавлять PvP-награды, пока владелец не закроет O1/O6. Техническую выдачу
  per-participant реализовать отдельным последующим изменением после решения.

Критерий: планы A и B одного turn попадают в один детерминированный резолв;
готовность одного игрока не запускает ход; дедлайн не теряет ни один сохранённый
план.

### PVP-4 — viewer-safe realtime

Файлы: `realtime/match_channels.py`, `api/routes/ws.py`,
`domain/combat/engine/payload.py`, `tests/test_match_channels.py`, WS API tests.

- `_Connection` хранит `viewer_id`; connect получает его после participant auth.
- Snapshot и каждый broadcast сериализуются отдельно через
  `v4_combat_response(..., viewer_id=connection.viewer_id)`.
- Join после commit отправляет lobby/update создателю; оба клиента после старта
  получают один resolution key, но разные руки.
- Публичные event snapshots оставляют только counts; новые viewer-only события
  в будущем фильтруются в payload-слое до постановки в outbound queue.
- Сохранить queue bound, send-timeout, дедуп HTTP/WS и polling fallback.

Критерий: сокет A никогда не получает руку B, сокет B — руку A; оба получают
одинаковые публичные units/events и свой корректный `viewer_id`.

### PVP-5 — frontend deep-link и lobby UX

Файлы: `src/shared/routing.ts`, `src/api.ts`, `src/main.tsx`,
`features/dashboard/Dashboard.tsx`, новая `features/invite/`, небольшая
адаптация `BattleV4.tsx`.

- Перевести route на discriminated value: обычные страницы,
  `invite/<token>`, `battle/<match_id>`.
- Dashboard: отдельное действие «Пригласить друга»; обычная кнопка боя всё ещё
  запускает PvE.
- Экран создателя: ссылка, copy/share, статус ожидания, отмена/перевыпуск,
  безопасный выход. Join-update автоматически ведёт в точный battle route.
- Экран получателя сохраняет token через login round-trip, вызывает join один
  раз и показывает отдельные сообщения invalid/expired/self/already used.
- Перед full-page Google OAuth сохранить pending invite route в `sessionStorage`,
  после возврата восстановить hash и удалить сохранённый token сразу после
  успешного join/явной отмены. Email-login остаётся в той же вкладке и route не
  теряет.
- `BattleV4` принимает конкретный initial match id и сначала грузит его; fallback
  на первый active нужен только для обычного `#battle`.
- В HUD показать «соперник готов/планирует» из публичного ready-state; свои
  локальные намерения не раскрывать.
- На mobile проверить копирование, native share (если доступен), длинную ссылку
  и возврат после OAuth redirect.

Критерий: ссылка переживает незалогиненный вход, две сессии автоматически
попадают в один матч, а наличие другого active PvE не уводит пользователя не
в тот бой.

### PVP-6 — reconnect и hardening перед внешним тестом

Файлы: payload/state событий, `ws.py`, `matchRealtime.ts`, `BattleV4.tsx`,
интеграционные тесты; точный контракт уже описан в ARCHITECTURE §5.2/§8.15.

- Реализовать snapshot начала последнего хода + events этого хода +
  `resume_from_sequence`; дедуп `(turn, sequence)`.
- Перезагрузка во время planning восстанавливает match, ready-state и
  server-stored plan. Клиент может не восстановить визуальный локальный план,
  но не должен затереть его пустым debounce до явного действия пользователя.
- Перезагрузка во время playback догоняет события и затем переходит к финальному
  состоянию без второго резолва.
- Expired/cancelled/finished lobby не остаётся «активным» и не создаёт вечный
  reconnect loop.
- Добавить audit-события `match.invite_created/joined/cancelled/expired` без
  token; метрики количества waiting lobby, join latency/errors и WS disconnect.
- Проверить cookie flags и `Origin` у state-changing HTTP/WS handshake. Invite
  token не считается заменой CSRF-защиты; общий CSRF-пункт Фазы 6 остаётся
  блокером публичного релиза, даже если закрытый тест с друзьями проводится
  раньше.

Критерий: kill/reload любого клиента не меняет исход боя и не раскрывает
секретные данные; второй клиент продолжает играть по дедлайну.

## 8. Матрица обязательных проверок

### Backend/domain

- create → waiting, без дедлайна и без участия timer-worker;
- join → ровно два human-seat, разные team/side, башни/руки/мана
  инициализированы один раз;
- invalid/expired/cancelled/self/replayed token;
- конкурентный join B/C: один успех, один конфликт, состояние не повреждено;
- A и B могут GET/plan/ready/WS, C не может;
- ready A ≠ resolve; ready A+B = один resolve; deadline применяет оба pending
  plan и пустой план только отсутствующему игроку;
- optimistic race worker/HTTP по-прежнему даёт один результат;
- active list и stale/ruleset expiry работают для обоих участников;
- viewer-specific HTTP, WS snapshot и WS update не раскрывают чужую руку/
  колоду/token;
- медленный сокет одного игрока не задерживает commit и второго игрока.

### Frontend/manual E2E

- две авторизованные вкладки с разными аккаунтами;
- invite через незалогиненную вкладку и возврат после login/OAuth;
- два разных устройства через production-like HTTPS origin;
- copy/share на desktop и mobile;
- reload обоих клиентов в waiting, planning, playback и finished;
- отключение WS у одного клиента: polling догоняет матч, второй не страдает;
- два active match: deep link всегда открывает указанный;
- expired/used/cancelled link даёт конечный экран и путь обратно на dashboard.

Финальные проверки репозитория: полный `pytest`, `ruff`, `npm run build`; затем
production-like smoke через Caddy/PostgreSQL, а не только SQLite/TestClient.

## 9. Порядок поставки

1. **Foundation:** PVP-1 + миграция + domain tests.
2. **Безопасный backend vertical:** PVP-2 + PVP-3 + PVP-4; проверить через два
   API/WS-клиента до UI.
3. **Пользовательский vertical:** PVP-5; invite → join → первый общий ход.
4. **Надёжность:** PVP-6; reload/disconnect/two-device matrix.
5. **Внешний P4 playtest:** деплой друзьям, запись проблем в PLAYTEST_NOTES,
   после чего вернуться к O10 и балансовым сценариям.

Каждый пакет поставляется отдельным осмысленным commit и сохраняет рабочий PvE-
путь. Миграция выкатывается до кода, который на неё опирается; rollback не
удаляет существующие бои. Feature flag для кнопки invite полезен до завершения
PVP-4: backend можно прогнать в staging, не показывая незавершённый flow всем.

## 10. Definition of Done первого PvP-invite этапа

- Ссылка создаётся, принимается вторым аккаунтом и не может быть захвачена
  третьим после join.
- В матче два человека, ни одного бота; оба плана участвуют в одном резолве.
- HTTP, WS, reconnect и active-query авторизуют по participant, а не по одному
  owner.
- Ни один payload/log не раскрывает token, чужую руку или порядок колоды.
- Reload/disconnect не создаёт второй резолв и не теряет server-stored plan.
- Пройдены backend/linters/frontend build и ручной тест с двух устройств.
- ROADMAP можно отметить выполненным только после внешнего матча с другом; сам
  факт появления endpoint `invite` завершением этапа не считается.
