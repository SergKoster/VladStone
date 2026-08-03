# Аудит готовности к деплою «Для друзей»

Дата среза: 3 августа 2026. Базовый HEAD: `02c8592`
(`fix(pvp): persist plans across reload`); проверки запускались на текущем
worktree поверх этого commit, включая незавершённые изменения владельца.

Подробный эксплуатационный runbook вынесен в [DEPLOY.md](DEPLOY.md). Этот
документ фиксирует именно состояние проекта на дату аудита, найденные риски и
условия, после которых можно давать ссылку друзьям.

## 1. Короткий вердикт

**Полный Релиз 1 «Для друзей» из DESIGN §11.1 пока не готов.** Не реализованы
deck builder и выбранная колода, расширение до 20–30 карт, ежедневки,
онбординг, мобильная полировка, SFX, concede и часть result UX. Это ожидаемое
состояние roadmap, а не регрессия.

**Контролируемый внешний alpha-тест PvP почти готов, но сейчас — NO-GO до
закрытия P0 ниже.** Invite/reconnect vertical slice реализован, unit/API-тесты
и frontend build проходят. Однако production rate-limit может заблокировать
обычный длинный PvP-матч, а production-контейнеры и реальный Google OAuth ещё
не прошли smoke в целевой среде.

После P0 допустим следующий формат:

- 2–10 заранее предупреждённых тестировщиков;
- один VPS, один API-процесс, один домен;
- оператор присутствует во время первой сессии и смотрит логи;
- данные считаются alpha-данными, но перед обновлениями уже делается backup;
- никаких обещаний про 100–200 CCU до отдельного нагрузочного smoke.

## 2. Что проверено

### 2.1 Автоматические проверки

| Проверка | Результат | Вывод |
|---|---|---|
| `pytest` | 180 passed, 1 skipped, 12 warnings | Backend и домен в целом зелёные |
| `npm run build` | Успешно; production bundle собран | TypeScript/Vite gate зелёный |
| `docker compose ... config --no-interpolate` | Успешно | Production Compose синтаксически валиден |
| `pip check` | No broken requirements | Установленный Python dependency set согласован |
| `ruff check .` | 1 ошибка `I001` | Текущий worktree выкладывать нельзя до зелёного lint |
| `npm audit --omit=dev` | 1 high | Уязвимый `postcss` приходит через Vite; см. P1 |
| Docker image build | Не запущен | Docker CLI есть, но локальный Docker daemon выключен |

`ruff` падает в уже изменённом до аудита
`VladStoneAPI/tests/test_combat_api.py` на сортировке import-блока. Это не
исправлялось в рамках отчёта, чтобы не затереть параллельную работу владельца.

### 2.2 Что подтверждено по реализации

- Production topology уже подготовлена:
  [docker-compose.prod.yml](../deploy/docker-compose.prod.yml),
  [Caddyfile](../deploy/Caddyfile), multi-stage Dockerfiles.
- Caddy обслуживает SPA и same-origin проксирует `/api/*` и `/ws/*`; наружу
  публикуются только 80/443, PostgreSQL остаётся во внутренней Docker network.
- Production включает `ENVIRONMENT=production` и `COOKIE_SECURE=true`;
  dev-login, email-code UI и dev telemetry выключаются.
- Google ID token проверяется через `google-auth`: подпись, audience, expiry и
  issuer.
- Alembic содержит миграции до `0003_pvp_invites`; API image запускает
  `alembic upgrade head` до uvicorn.
- PvP participant authorization, viewer-safe HTTP/WS payload, optimistic
  locking, timer worker, reconnect cursor и server-side plan persistence
  реализованы.
- Секрет invite хранится в URL fragment и в БД только как digest; чужая рука и
  порядок колоды не сериализуются.
- Есть bounded WS queue и send timeout: медленный сокет не держит commit и
  второго игрока.
- Python production dependencies зафиксированы hash-verified lock-файлом.

## 3. Блокеры и риски

### P0 — закрыть до первой внешней PvP-сессии

#### P0.1. PvP-игроки делят один rate-limit

`POST /combat/plan` и `POST /combat/ready` используют ключ
`combat-turn:{record.owner_user_id}`
([combat.py](../VladStoneAPI/app/api/routes/combat.py)). Для PvP это id
создателя, поэтому действия обоих игроков складываются в один process-local
bucket. Frontend отправляет `/plan` при каждом изменении плана и отдельный
`/ready`. В результате нормальный матч целевой длины может получить `429` до
завершения.

Нужно:

1. Лимитировать по фактическому authenticated actor, а не по owner матча.
2. Развести buckets для plan/ready/start/invite/join либо обосновать общий.
3. Добавить production-mode API-тест: оба участника не блокируют друг друга и
   легальный матч не исчерпывает лимит.
4. Отдельно ограничить `POST /matches/invite` и `POST /matches/join`:
   в [matches.py](../VladStoneAPI/app/api/routes/matches.py) limiter сейчас
   отсутствует, хотя он заложен в PVP_INVITE_PLAN §6.

#### P0.2. Нет production-like container smoke

Успешны Python/TS проверки и parse Compose, но не подтверждены фактические:

- сборка обоих Docker images на Linux;
- старт PostgreSQL 17 и применение всех Alembic migrations;
- Caddy certificate issuance и proxy WebSocket upgrade;
- Google callback на реальном домене;
- два устройства через публичный HTTPS origin.

Локально image build остановился до чтения Dockerfile: Docker Desktop daemon
не был запущен. Это ограничение среды аудита, но до приглашения друга smoke из
[DEPLOY.md](DEPLOY.md#8-приёмочный-smoke-перед-ссылкой-друзьям) обязателен.

#### P0.3. Конкретный deploy commit должен иметь все gates зелёными

Нельзя выкладывать грязный worktree или commit с красным CI. Для выбранного SHA
обязательны `pytest`, `ruff` и `npm run build`. Текущий lint красный из-за
незавершённого пользовательского изменения, указанного в §2.1.

#### P0.4. Нужно явно выбрать границу доступа

Приложение не содержит email/domain allowlist. Любой пользователь, которого
пропустит Google OAuth, сможет создать аккаунт, PvE-матчи и invite lobby.
Google `Testing` не следует считать security boundary: текущий flow просит
только basic identity scopes `openid email`, для которых Google описывает
исключение из обычного test-user ограничения.

До закрытого релиза владелец должен выбрать одно:

- **рекомендуется:** app-level allowlist Google email для alpha;
- временно принять, что сервис технически открыт любому Google account,
  не публиковать домен и считать это осознанным риском;
- внешний access gate перед приложением — только если отдельно проверен полный
  OAuth callback и WS flow.

Список Google test users всё равно полезен для управляемого теста, но не
заменяет авторизацию приложения.

### P1 — до постоянного friends-сервера

| Риск | Фактическое состояние | Что сделать |
|---|---|---|
| Backup/restore | Только Docker volume, backup automation нет | Daily `pg_dump -Fc`, off-host копия, тест восстановления |
| Наблюдаемость | Uvicorn/Docker logs; Sentry и метрик нет | Error tracking, uptime probe, worker heartbeat, disk alert |
| Healthcheck | `/api/health` не проверяет БД; у API нет Compose healthcheck | Readiness с `SELECT 1` + Compose healthcheck |
| Логи | Docker default может расти без лимита | Включить rotation на сервисах/daemon |
| Supply chain frontend | `postcss 8.5.15` имеет high advisory | Обновить lock-файл, прогнать build/audit; runtime Caddy image Node не содержит |
| Base images | Floating `python:3.12-slim`, `node:22-alpine`, `caddy:2-alpine`, `postgres:17-alpine` | Зафиксировать patch/digest или собирать проверенный image один раз и продвигать его |
| Config safety | `environment` — произвольная строка; обязательные prod values не валидируются fail-fast | Literal env + production validator для OAuth, HTTPS URLs, secure cookie, CORS |
| Rate limiter | In-memory, исчезает при restart и не общий между instances | Для одного процесса допустимо; перед scale-out перенести в Redis/DB |
| Container privilege | API image не задаёт non-root user | Перевести runtime на непривилегированного пользователя |
| Release artifact | VPS делает `git pull` и локальный build | Деплоить exact SHA/tag; позже — immutable images из CI |

High advisory для PostCSS относится к build dependency Vite. В финальный Caddy
runtime Node modules не копируются, а CSS проекта не поступает от
неавторизованных пользователей, поэтому это не P0 эксплуатации. Но красный
dependency audit нельзя оставлять нормой.

### P2 — не блокирует supervised alpha, но блокирует заявленную ёмкость

- Нет smoke/load test на 100–200 CCU.
- Timer worker раз в тик перебирает planning matches одним процессом; heartbeat
  и cap/jitter из ARCHITECTURE §8.14 не завершены.
- Нет frontend automated tests; критичный invite/reconnect UX покрыт только
  backend-тестами и ручными browser smoke.
- Нет staging: первый настоящий container/OAuth/HTTPS test фактически
  совпадает с production.
- Нет автоматизированного rollback и проверки совместимости миграций.
- Caddy config не задаёт явные security headers и отдельную access-log policy.

## 4. Покрытие матрицы PvP

Текущие тесты хорошо фиксируют основной happy path:

- два seat и viewer-safe hands;
- один ready не резолвит, два ready резолвят;
- per-viewer WebSocket snapshot;
- reconnect resume и cursor;
- unknown WS Origin отклоняется;
- slow socket отключается.

Но обязательная матрица PVP_INVITE_PLAN §8 покрыта не полностью. Не найдены
отдельные автоматические регрессии для:

- invalid/expired/cancelled/replayed token как полного набора;
- конкурентного join B/C;
- deadline с двумя разными сохранёнными PvP-планами;
- participant authorization для всех plan/ready/lobby/cancel/active/WS путей;
- lobby reload/expiry sweep;
- HTTP/WS payload leak scan по token, `user_id` и opponent hand;
- production `429` semantics;
- frontend deep-link после реального Google round-trip.

Это не отменяет существующие 180 тестов, но объясняет, почему внешний
two-device smoke остаётся release gate.

## 5. Готовность продуктового Релиза 1

| Требование DESIGN §11.1 | Статус |
|---|---|
| Стабильная v4-боёвка, способности, статусы, заклинания | Реализовано; внешний PvP playtest не пройден |
| PvE с ботом | Реализовано |
| PvP по invite | Core реализован локально; P0 и внешний smoke открыты |
| 20–30 карт | Сейчас стартовый batch из 12 |
| Колода 12 без дублей + deck builder | Не реализовано |
| Старт с выбранной колодой | Не реализовано |
| Стартовый набор новичка | Не завершён |
| Daily quests и гарантированные награды | Не реализовано |
| Concede | Не реализовано |
| Онбординг первых 15 минут | Не реализован |
| Mobile polish | Не завершён |
| Минимальные SFX | Не реализованы |
| Result overlay/выход/новый бой | Требует полировки |
| Infrastructure на 100–200 CCU | Skeleton готов; load/ops proof отсутствует |

Итого: текущую выкладку правильно называть **закрытой PvP alpha для
верификации Фазы 4**, а не завершённым Релизом 1.

## 6. Решение Go/No-Go

### Go для supervised PvP alpha, когда одновременно выполнено

- [ ] P0.1 rate-limit исправлен и покрыт тестом.
- [ ] Deploy SHA чистый, CI/pytest/ruff/frontend build зелёные.
- [ ] Production images реально собрались.
- [ ] `deploy/.env` заполнен и проверен без вывода секретов.
- [ ] Google callback и `/api/auth/providers` проверены на реальном домене.
- [ ] Владелец осознанно выбрал access boundary.
- [ ] Сделан хотя бы ручной backup после первого успешного старта.
- [ ] Пройден двухаккаунтный smoke на двух устройствах и разных сетях.
- [ ] Оператор смотрит API/Caddy/Postgres logs во время первого матча.

### Go для постоянного сервера «для друзей», когда дополнительно

- [ ] Ежедневный off-host backup и restore drill.
- [ ] Uptime/error/disk monitoring и ротация логов.
- [ ] API/DB readiness healthcheck.
- [ ] Закрыт или принят владельцем весь обязательный продуктовый scope
      DESIGN §11.1.
- [ ] Проведён UX-прогон «15 минут без объяснений».

### No-Go для 100–200 CCU

До отдельного нагрузочного сценария нельзя обещать эту ёмкость. Архитектурный
single-instance режим ей не обязательно противоречит, но текущий timer/WS/DB
профиль под такой нагрузкой не измерялся.

## 7. Источники и границы аудита

Внутренние источники:
[DESIGN.md](DESIGN.md),
[ROADMAP.md](ROADMAP.md),
[ARCHITECTURE.md](ARCHITECTURE.md),
[PVP_INVITE_PLAN.md](PVP_INVITE_PLAN.md),
[DEPLOY.md](DEPLOY.md),
[TODO.md](../TODO.md), production config и код auth/combat/realtime.

Внешние требования сверены по официальным материалам:

- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
  (включая предупреждение, что published container ports могут обходить UFW);
- [Caddy Automatic HTTPS quick-start](https://caddyserver.com/docs/quick-starts/https)
  (DNS и публичные 80/443);
- [Google OAuth app audience](https://support.google.com/cloud/answer/15549945)
  и [точное совпадение redirect URI](https://developers.google.com/identity/protocols/oauth2/web-server);
- [PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html)
  и custom archive format.

Не проверялись из этой среды: реальный VPS, DNS, certificate issuance,
Google Cloud credentials, off-host backup, восстановление и сетевой
two-device flow. Они вынесены в обязательный runbook smoke.
