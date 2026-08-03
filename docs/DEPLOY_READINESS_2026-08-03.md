# Готовность к PvP-деплою для игры с другом

Дата среза: 3 августа 2026. Базовый HEAD аудита: `02c8592`
(`fix(pvp): persist plans across reload`). Проверки запускались на текущем
worktree поверх этого commit.

Цель этого аудита узкая: **выложить VladStone в интернет, войти двумя
Google-аккаунтами и сыграть один или несколько PvP-матчей по invite-ссылке**.
Готовность полного Релиза 1 из DESIGN §11.1 здесь не оценивается.

Пошаговая инструкция: [DEPLOY.md](DEPLOY.md).

## Вердикт

**Кодовый блокер закрыт. Проект готов к первому production smoke на VPS и
последующему матчу с другом.**

Теперь можно поднимать один VPS, проходить production smoke и играть с другом.
Deck builder, ежедневки, 20–30 карт, Sentry, нагрузочное
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

## Исправленный риск: PvP rate-limit

Раньше `POST /combat/plan`, `POST /combat/ready` и ручной resolve использовали
rate-limit key на основе `record.owner_user_id`. В PvP запросы обоих игроков
попадали в bucket создателя.

Frontend отправляет `/plan` после каждого изменения расстановки и отдельный
`/ready`, поэтому в длинном матче общий лимит мог закончиться.

Исправлено в [combat.py](../VladStoneAPI/app/api/routes/combat.py):

- turn-action key строится по authenticated user, который отправил запрос;
- создатель и присоединившийся друг расходуют независимые buckets;
- production-mode regression в
  [test_pvp_invites.py](../VladStoneAPI/tests/test_pvp_invites.py) исчерпывает
  bucket создателя и проверяет, что план второго игрока всё равно принимается.

Лимит и его защитная функция сохранены: один игрок по-прежнему получает `429`
после собственного превышения, но больше не может исчерпать лимит друга.

## Фактические проверки

| Проверка | Результат |
|---|---|
| Backend `pytest` | 181 passed, 1 skipped |
| Frontend `npm run build` | Успешно |
| Production Compose parse | Успешно |
| `pip check` | No broken requirements |
| `ruff check app tests/test_pvp_invites.py` | Успешно |
| Полный `ruff check .` | В локальном worktree остаётся чужой import-order diff в `tests/test_combat_api.py` |
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

- [x] Исправлен общий PvP rate-limit и добавлен regression test.
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
