# Готовность к PvP-деплою для игры с другом

Дата среза: 3 августа 2026. Базовый HEAD аудита: `02c8592`
(`fix(pvp): persist plans across reload`). Проверки запускались на текущем
worktree поверх этого commit.

Цель этого аудита узкая: **выложить VladStone в интернет, войти двумя
Google-аккаунтами и сыграть один или несколько PvP-матчей по invite-ссылке**.
Готовность полного Релиза 1 из DESIGN §11.1 здесь не оценивается.

Пошаговая инструкция: [DEPLOY.md](DEPLOY.md).

## Вердикт

**Проект почти готов к такому деплою. Перед выкладкой нужно исправить один
кодовый блокер: общий production rate-limit двух PvP-игроков.**

После исправления можно поднимать один VPS, проходить production smoke и сразу
играть с другом. Deck builder, ежедневки, 20–30 карт, Sentry, нагрузочное
тестирование и полноценная release-инфраструктура для этой цели не нужны.

## Что уже готово

- PvP lobby и одноразовая invite-ссылка.
- Вход второго игрока по deep link, включая возврат после Google OAuth.
- Два human seat без бота.
- Одновременное планирование и resolve после готовности обоих или дедлайна.
- Своя рука для каждого viewer; рука и порядок колоды соперника не отдаются.
- Viewer-relative поле: своя сторона у обоих игроков снизу.
- WebSocket updates и polling fallback.
- Reload/reconnect в lobby, planning и после resolve.
- Серверное сохранение последнего плана.
- Защита от двойного resolve через optimistic locking.
- Production Compose: Caddy + FastAPI + PostgreSQL.
- Same-origin HTTPS/WSS.
- Реальный Google OAuth.
- Alembic migrations до `0003_pvp_invites`.
- Production guards: без сессии нельзя создавать внешний бой, dev telemetry
  выключена, размеры HTTP/WS payload ограничены.

## Единственный блокер перед деплоем

`POST /combat/plan` и `POST /combat/ready` используют rate-limit key на основе
`record.owner_user_id` в
[combat.py](../VladStoneAPI/app/api/routes/combat.py). В PvP это id создателя
матча, поэтому запросы обоих игроков попадают в один общий bucket.

Frontend отправляет `/plan` после каждого изменения расстановки и отдельный
`/ready`. В длинном матче лимит может закончиться и один из игроков получит
`429 Too Many Requests`.

Перед деплоем нужно:

1. Считать turn-action limit по authenticated user, который отправил запрос.
2. Не заставлять двух участников делить один bucket.
3. Добавить production-mode regression test для двух участников.

Это техническое исправление, а не вопрос игрового дизайна.

## Фактические проверки

| Проверка | Результат |
|---|---|
| Backend `pytest` | 180 passed, 1 skipped |
| Frontend `npm run build` | Успешно |
| Production Compose parse | Успешно |
| `pip check` | No broken requirements |
| `ruff check .` | Падает на import order в локально изменённом владельцем `tests/test_combat_api.py` |
| Docker image build | Не проверен: локальный Docker daemon был выключен |

Ошибка `ruff` относится к незакоммиченному пользовательскому worktree и не
доказывает, что базовый commit красный. Перед деплоем проверки нужно повторить
в чистом clone exact deploy SHA.

## Что проверится непосредственно при деплое

Следующие вещи невозможно подтвердить без реального VPS и домена:

- Linux-сборка API и web Docker images;
- старт PostgreSQL и применение migrations;
- получение HTTPS-сертификата Caddy;
- реальный Google callback;
- WebSocket через публичный `wss://`;
- матч с двух устройств и разных сетей.

Это не отдельный проектный этап: проверки входят в первый запуск по
[DEPLOY.md](DEPLOY.md#7-проверка-перед-матчем).

## Что не блокирует игру с другом

Для этого узкого теста не требуются:

- deck builder и выбранная пользовательская колода;
- полный набор 20–30 карт;
- ежедневные задания и финальная экономика;
- concede, SFX и законченный онбординг;
- Sentry и structured logging;
- автоматические ежедневные backup;
- frontend test suite;
- load test на 100–200 CCU;
- app-level email allowlist.

Сервер технически сможет принять другого Google-пользователя, если тот узнает
адрес. Для короткого теста достаточно не публиковать домен и после игры
остановить containers. Это не модель безопасности для публичного релиза, но
для текущей задачи отдельное решение владельца не требуется.

## Go-чеклист

Можно отправлять invite другу, когда:

- [ ] Исправлен общий PvP rate-limit и добавлен regression test.
- [ ] В чистом deploy SHA зелёные `pytest`, `ruff` и frontend build.
- [ ] На VPS успешно собрались оба images.
- [ ] `/api/health` показывает `environment=production`.
- [ ] `/api/auth/providers` показывает Google и не показывает dev-login.
- [ ] Оба Google-аккаунта успешно входят.
- [ ] Создатель создаёт invite, друг принимает его на втором устройстве.
- [ ] Ready обоих даёт один resolve без `409`/`429`/traceback.
- [ ] Reload и краткий обрыв сети не теряют матч.

После удачного матча результат записывается в
[PLAYTEST_NOTES.md](PLAYTEST_NOTES.md), после чего можно вернуться к O10.

## Источники

Внутренние:
[PVP_INVITE_PLAN.md](PVP_INVITE_PLAN.md),
[ARCHITECTURE.md](ARCHITECTURE.md),
[ROADMAP.md](ROADMAP.md),
production config в [`deploy/`](../deploy/).

Внешние:

- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Caddy Automatic HTTPS](https://caddyserver.com/docs/quick-starts/https)
- [Google OAuth redirect URI](https://developers.google.com/identity/protocols/oauth2/web-server)
