# Code review VladStoneAPI и VladStoneWeb — 3 августа 2026

## Резюме

Проверены tracked-файлы `VladStoneAPI/` и `VladStoneWeb/`: API-роуты,
авторизация, хранение, timer worker, WebSocket-каналы, live-движок боя v4,
контракт событий, React-состояние боя, replay, API-клиент, Docker/config и тесты.
Бинарные арты оценивались только как часть сборки, не как код.

Точка ревью: ветка `master`, commit `e32257e`. В рабочем дереве до ревью уже
были посторонние изменения; они не входят в этот отчёт и не исправлялись.

Итог: архитектурная граница «сервер — источник истины» в целом выдержана,
боевой домен хорошо покрыт тестами, оптимистическая блокировка резолва и
viewer-safe HTTP payload реализованы аккуратно. При этом найдено **7 проблем
P1** и **4 проблемы P2**. Самая важная новая ошибка — сломанный цикл колоды
live-боя v4. Внешний деплой также пока нельзя считать безопасным из-за уже
известных, но подтверждённых кодом auth/DoS/WS-рисков.

Приоритеты в этом документе:

- **P1** — исправить до внешнего плейтеста/эксплуатации затронутого пути;
- **P2** — исправить до PvP или следующего расширения функциональности;
- **P3** — плановый технический долг.

## Находки

### CR-01 · P1 · NEW — цикл колоды v4 использует legacy-каталог и может прекратить добор навсегда

**Где:**

- `VladStoneAPI/app/domain/combat/engine/resolver.py:25-26,684-692`;
- `VladStoneAPI/app/domain/combat/engine/apply.py:19,626-641`;
- `VladStoneAPI/app/domain/combat/deck.py:18-27`;
- `VladStoneAPI/app/domain/combat/engine/content.py:294`.

Live-резолвер v4 и эффект `DrawCard` импортируют `draw_card` из legacy-модуля.
При пустой колоде тот восстанавливает её из `DECK_CARD_IDS`, где 11 карт,
тогда как v4 играет `DECK_CARD_IDS_V4` из 12 карт. В результате
`samurai_koster` после первого цикла больше не возвращается. Дополнительно
guards в `_draw_and_mana` и `_draw_card` не вызывают пересборку, когда пусты
одновременно и рука, и колода: такой участник больше никогда не получит карту.
Это противоречит зафиксированному в `COMBAT_REWORK.md` §19 I6 циклу
«перетасовка из карт вне руки».

Минимальные проверки на текущем коде дали:

```text
samurai_koster in recycled draw: False
v4 cards: 12; recycle source: 11

p2 hand after end-of-turn draw: []
p2 draw events: []
```

**Последствие:** длинный матч меняет фактический decklist, а при определённой
последовательности розыгрышей игрок или бот остаётся без добора до суда.
Существующие 162 backend-теста этот путь не фиксируют.

**Рекомендация:** отвязать deck-cycle от глобального legacy-списка. Передавать
исходный decklist/пул конкретного матча (в перспективе — `CardInstance`) либо
хранить его в participant/match state; «участника без цикла» обозначать явным
полем, а не эвристикой `not deck and not hand`. Добавить регрессии на полный
цикл всех 12 карт, `samurai_koster`, пустые `deck+hand`, полный hand cap и
`DrawCard`-эффект.

### CR-02 · P1 · NEW — заявленного polling fallback нет, а полный GET-envelope после 409 отбрасывается

**Где:**

- `VladStoneWeb/src/features/battle/matchRealtime.ts:20-77`;
- `VladStoneWeb/src/features/battle/BattleV4.tsx:359-413,645-668`;
- `docs/ARCHITECTURE.md:164-168,542-550`.

`connectMatchRealtime` умеет только бесконечно переподключать WebSocket; polling
там отсутствует. После ошибки `readyCombat` клиент делает `getCombat`, но
коммитит результат только при `fresh.events.length === 0`. Полный envelope с
событиями намеренно не применяется в ожидании WS, которого в рассматриваемом
сценарии нет.

**Сценарий:** заблокировать/уронить WS, оставить HTTP доступным, нажать
«Готов». Сервер резолвит ход, но UI может остаться на старом ходе бессрочно.
Это расходится с заявленным в архитектуре fallback polling 8 с.

**Рекомендация:** включать polling при любом статусе кроме «подключен» и
пропускать HTTP/WS/polling envelopes через одну функцию `consumeResolution`.
В catch-пути обрабатывать и полный GET-envelope, полагаясь на существующий
playback key для дедупликации. Покрыть тестом «WS недоступен весь ход».

### CR-03 · P1 · NEW — realtime-update теряется, если replay предыдущего хода ещё занят

**Где:**

- `VladStoneWeb/src/features/battle/useTurnPlayback.ts:96-109`;
- `VladStoneWeb/src/features/battle/BattleV4.tsx:386-401`.

`playTurn` возвращает `"busy"`, если уже идёт replay. В вызывающем коде новый
`payload.match` коммитится только при результате, отличном от `"busy"`; очереди
или повторной обработки нет. В фоновой вкладке, при throttling таймеров или при
нескольких быстрых server updates следующий авторитетный snapshot теряется.
Следующее сообщение может принести только ленту ещё более позднего хода, то
есть промежуточное состояние и события уже не восстановить.

**Рекомендация:** держать bounded-очередь envelopes либо single-slot
`pendingLatest`, который запускается сразу после текущего replay; snapshots без
полной непрерывной ленты безопасно проматывать к серверному финалу. До PvP
дополнить это спроектированным `resume_from_sequence`.

### CR-04 · P1 · CONFIRMED — production auth нельзя выпускать в текущем виде

**Где:**

- `VladStoneAPI/app/services/google_oauth.py:43-80`;
- `VladStoneAPI/app/services/auth.py:29-53`;
- `VladStoneAPI/app/api/routes/auth.py:40-70`;
- `VladStoneAPI/app/api/schemas.py:15-17`.

Google `id_token` только base64-декодируется; проверяются `aud` и `iss`, но не
JWT signature, `exp`, `iat` и `kid`. Комментарий о том, что TLS token exchange
делает проверку подписи ненужной, расходится с официальной рекомендацией
Google: сервер должен проверить подпись, audience, issuer и expiration и
предпочтительно использовать готовую библиотеку. См.
[Verify the Google ID token on your server side](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

Email-код имеет 1 000 000 вариантов, но `/email/verify` не ограничен ни rate
limit, ни счётчиком ошибок на записи кода; длина `code` тоже не ограничена.
Provider скрыт UI вне local, однако сами `/email/request` и `/email/verify`
остаются доступны в любом environment.

**Рекомендация:** использовать `google-auth`/проверенный JWT verifier с JWKS
cache; добавить тесты на поддельную подпись и истёкший token. Email endpoints
жёстко выключить вне поддерживаемого environment; перед включением — per-IP и
per-identity лимиты, 3–5 попыток на code row с инвалидированием кода и строгий
формат `^\d{6}$`.

### CR-05 · P1 · CONFIRMED — несколько публичных путей позволяют расходовать память, БД, CPU и диск без лимитов

**Где:**

- `VladStoneAPI/app/api/routes/combat.py:56-73,336-348`;
- `VladStoneAPI/app/api/routes/ws.py:16-28,53-56`;
- `VladStoneAPI/app/api/schemas.py:34-62`;
- `VladStoneAPI/app/api/routes/telemetry.py:9-16`;
- `VladStoneAPI/app/services/dev_logging.py:12-20`;
- `VladStoneAPI/app/services/rate_limit.py:6-20`.

`/combat/start` создаёт ownerless-матчи без авторизации, а HTTP и WS разрешают
доступ любому к записи с `owner_user_id=None`. Placements/spells, строки и
telemetry payload не имеют разумных bounds; WS принимает JSON без лимита
частоты/сообщения. Telemetry без auth всегда пишет в бесконечный JSONL, в том
числе вне local. `/auth/email/request` создаёт code и audit rows, а in-memory
rate limiter ключуется только по email и никогда не удаляет опустевшие keys —
уникальные адреса обходят лимит и растят `_attempts`.

**Последствие:** до доменной валидации внешний клиент может плодить матчи и
записи, нагружать timer worker, удерживать WS и заполнять диск.

**Рекомендация:** требовать auth для реального combat/WS, demo вынести в
изолированный endpoint; поставить proxy body limit, Pydantic bounds и максимум
intents по физическому hand cap; ограничить WS message size/rate. Dev telemetry
отключать вне local или заменить bounded structured logging с allowlist,
ротацией и auth/rate limit. Rate limiter должен иметь IP/global слой и удалять
пустые buckets либо жить во внешнем TTL-store.

### CR-06 · P1 · CONFIRMED — один медленный WebSocket блокирует HTTP resolve и все следующие timer broadcasts

**Где:**

- `VladStoneAPI/app/realtime/match_channels.py:74-85`;
- `VladStoneAPI/app/api/routes/combat.py:312-323`;
- `VladStoneAPI/app/services/combat_timer_worker.py:26-32`.

`_broadcast` последовательно ждёт `websocket.send_json` без timeout/очереди и
ловит только `RuntimeError`. HTTP уже закоммитил матч, но не отдаёт ответ до
окончания broadcast; worker так же последовательно рассылает матчи. Один
нечитающий клиент способен задержать сокеты своего матча, HTTP-ответ и затем
обработку остальных матчей timer worker.

**Рекомендация:** bounded outbound queue и sender task на соединение,
send-timeout, отключение при overflow/любой send-ошибке; commit/HTTP response и
обработка следующего матча не должны ждать медленного клиента. Нужен тест с
WS-клиентом, который перестал читать.

### CR-07 · P1 · CONFIRMED — коллекция и live-бой читают разные каталоги

**Где:**

- `VladStoneAPI/app/services/accounts.py:18-42,86-104`;
- `VladStoneAPI/app/api/routes/me.py:94-125`;
- `VladStoneAPI/app/domain/combat/engine/payload.py:60-96`;
- `VladStoneWeb/src/features/collection/Collection.tsx:17-20,55-61`.

Live-бой и `/combat/catalog` читают 12 v4-карт из `engine/content.py`, а seed,
DB projection, коллекция и rarity продолжают читать legacy-каталог из 11 карт
с другими статами. `samurai_koster` отсутствует в коллекционном источнике; detail
карты открывается только при совпадении id в обоих каталогах. Одновременно UI и
API всё ещё реализуют отменённое дизайном возвышение.

**Рекомендация:** выполнить уже описанную в `ARCHITECTURE.md` §8.18 миграцию на
единый versioned application catalog до deck builder: seed существующих БД,
starter grant, collection, combat и будущая deck validation должны читать один
источник. Добавить contract-тест равенства публичных metadata. Ascension route/UI
закрыть отдельно по R9.

### CR-08 · P2 · NEW — активный бой не восстанавливается после reload или ухода со страницы

**Где:**

- `VladStoneWeb/src/api.ts:327-329`;
- `VladStoneWeb/src/features/battle/BattleV4.tsx:689-696`;
- `VladStoneWeb/src/main.tsx:200-205`.

`getActiveCombats` определён, но нигде не используется. `BattleV4` хранит match
только локально и после нового mount показывает «Старт боя». Reload либо переход
на другой route размонтирует компонент и оставляет серверный матч активным до
stale TTL; пользователь может плодить новые матчи вместо reconnect.

**Рекомендация:** при входе на route боя сначала запрашивать `/combat/active`,
восстанавливать один актуальный матч (или показывать выбор), затем подключать WS
и проигрывать сохранённый envelope согласно reconnect-контракту.

### CR-09 · P2 · NEW — event snapshot не позволяет replay показать актуальные статусы и эффективные статы

**Где:**

- `VladStoneAPI/app/domain/combat/engine/apply.py:163-204`;
- `VladStoneWeb/src/features/battle/turnPlayback.ts:112-139`.

Server snapshot содержит HP, max HP, стойку и action budgets, но не statuses,
damage, move steps и attacks per turn. Клиент при каждом кадре сохраняет эти
поля из предыдущего/full состояния. Поэтому после `status_applied`,
`status_expired` или `stat_buffed` попап уже проигран, а токен и инспектор до
самого `settleOnFinal` показывают старые значения. Это особенно заметно в
длинной цепочке эффектов одного хода.

**Рекомендация:** расширить server-authoritative snapshot публичными status
instances и эффективными статами либо применять структурные event deltas в
одном протестированном reducer. Первый вариант проще сохраняет основной
инвариант проекта: фронт ничего не вычисляет из текста/каталога.

### CR-10 · P2 · NEW — lock содержит уязвимый PostCSS 8.5.15

**Где:** `VladStoneWeb/package-lock.json:1445-1446,1639`.

`npm audit --omit=dev` на дату ревью сообщает одну high-уязвимость:
`GHSA-r28c-9q8g-f849`, path traversal при автозагрузке previous source map;
затронуты версии `<=8.5.17`, исправлено в `8.5.18`. См.
[GitHub Advisory](https://github.com/advisories/GHSA-r28c-9q8g-f849).

Текущий VladStone не обрабатывает пользовательский CSS, поэтому это риск
build/dev toolchain, а не эксплуатация игрового SPA из браузера. Тем не менее
lock надо обновить и повторить build/audit до внешнего релиза.

### CR-11 · P2 · NEW — сложный frontend replay не имеет автоматических тестов

**Где:** `VladStoneWeb/package.json:6-10`; вся папка
`VladStoneWeb/src/features/battle/`.

Frontend имеет только TypeScript/build check. Нет unit/integration-тестов для
dedup HTTP/WS, busy replay, watchdog, event snapshots, plan debounce, timer
deadline, reconnect и drag/touch. Именно в этих местах уже были реальные гонки,
а CR-02/03/08/09 не ловятся `tsc`.

**Рекомендация:** добавить Vitest + React Testing Library и детерминированные
fake timers. Первый минимальный набор: reducer snapshots, два источника одного
envelope, update во время busy, WS-down polling, 409 с полным GET-envelope,
unmount/remount активного матча и watchdog.

## Подтверждённые долги, не дублированные как отдельные находки

Во время ревью также подтверждены пункты `ARCHITECTURE.md` §8: один in-process
instance без Redis, отсутствие полного reconnect/resume-контракта,
недетерминированный replay без сохранённого RNG seed/journal, heartbeat/jitter
timer worker, незакреплённые Python production dependencies, неиспользуемый
`access_token`. В `TODO.md` уже корректно записаны UI слотов разрушенных башен и
редизайн руки. Эти пункты не повышали счётчик выше, чтобы отчёт не выдавал
известный roadmap за новые дефекты.

Низкоприоритетная гигиена репозитория: tracked `VladStoneAPI/vladstone_api.egg-info/`
является generated metadata и может расходиться с `pyproject.toml`; его лучше
удалить из Git в отдельной уборке после проверки packaging flow.

## Проверки

| Проверка | Результат |
|---|---|
| `VladStoneAPI/.venv/Scripts/python -m pytest` | **161 passed, 1 skipped**; skip уже находился в пользовательском изменении `tests/test_combat_api.py` |
| `VladStoneAPI/.venv/Scripts/python -m ruff check .` | **failed**: `I001` в уже изменённом пользователем `tests/test_combat_api.py:3`; код в рамках ревью не исправлялся |
| `VladStoneWeb/npm run build` | **passed**, 64 modules transformed |
| `npm audit --omit=dev` | **1 high**: PostCSS `8.5.15`, GHSA-r28c-9q8g-f849 |
| Точечный repro deck-cycle | **failed invariant**: recycle 11/12, `samurai_koster` отсутствует; пустые `deck+hand` не добирают |

Замечание: общий pytest зелёный с одним skip, но это не отменяет CR-01 — тесты
не проходят полный цикл именно v4-колоды. Ruff failure относится к исходному
грязному дереву, не к файлу отчёта.

## Рекомендуемый порядок исправлений

1. Закрыть CR-01 и добавить deck-cycle regressions — это уже live-геймплей.
2. Объединить обработку envelopes и закрыть CR-02/03/08; затем добавить первые
   frontend-тесты из CR-11.
3. До доступа из интернета закрыть CR-04/05/06 и обновить PostCSS (CR-10).
4. До deck builder выполнить CR-07; при этом удалить ascension UI/API по R9.
5. Расширить replay snapshot (CR-09) перед новым контентом со status/stat
   цепочками, чтобы анимации оставались проекцией серверных событий.

## Что сделано хорошо

- Optimistic lock `combat_matches.version` и единый resolution envelope
  существенно уменьшают риск двойного резолва и потери ленты событий.
- `v4_combat_response` не сериализует порядок/состав колоды и отдаёт руку только
  viewer; HTTP/PvE anti-cheat контракт соблюдён.
- Live-движок отделён от API/I/O, фазовый resolver имеет явные state validation
  checkpoints и широкое backend-покрытие.
- Клиент строит анимации по server events, а не угадывает боевой результат;
  replay key и синхронный re-entrancy lock правильно закрывают дубль одного и
  того же HTTP/WS envelope.
- Docker production path использует same-origin `/api`/`/ws`, а dev-login и
  `create_all` привязаны к environment.
