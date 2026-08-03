# Деплой VladStone на VPS

Этот файл — эксплуатационный runbook первого внешнего PvP alpha и последующих
обновлений. Датированный вердикт и найденные блокеры:
[DEPLOY_READINESS_2026-08-03.md](DEPLOY_READINESS_2026-08-03.md).

## 1. Какой деплой описан

Один Linux VPS и один домен:

~~~text
Браузер ── HTTPS/WSS ──> Caddy (контейнер web)
                           ├─ SPA из /srv
                           ├─ /api/* ──> api:8000
                           └─ /ws/*  ──> api:8000
                                          └─> postgres:5432
~~~

Production-файлы находятся в [`deploy/`](../deploy/):

- [`docker-compose.prod.yml`](../deploy/docker-compose.prod.yml);
- [`Caddyfile`](../deploy/Caddyfile);
- [`.env.prod.example`](../deploy/.env.prod.example).

Ограничения текущей архитектуры:

- ровно один API container и один uvicorn worker;
- WebSocket channels и timer worker живут в памяти API-процесса;
- PostgreSQL не публикуется на host;
- Redis в production не нужен;
- выкладку лучше делать между матчами: рестарт API разорвёт WS, после чего
  клиент переподключится, но менять ruleset во время матча не следует.

Этот профиль подходит для нескольких друзей и supervised alpha. Ёмкость
100–200 CCU ещё не подтверждена нагрузочным тестом.

## 2. Что потребуется

### Инфраструктура

- VPS с Ubuntu 24.04 LTS x86_64.
- Для первого теста: минимум 2 ГБ RAM; практичнее 2 vCPU и 4 ГБ RAM, если
  Docker images будут собираться прямо на VPS. Это запас на сборку, а не
  доказательство игровой ёмкости.
- Не менее 20 ГБ SSD и контроль свободного места.
- Публичный IPv4.
- Домен или поддомен, например `play.example.com`.
- Доступ снаружи к TCP 80/443; SSH — только с доверенных адресов, если
  provider firewall это позволяет.

Не публиковать 5432, 6379 или 8000. В текущем production Compose наружу
выставлены только 80/443.

### Аккаунты и секреты

- Google Cloud project и OAuth client типа `Web application`.
- Два разных Google account для PvP smoke.
- Read-only способ получить private repository на VPS: GitHub deploy key
  предпочтительнее персонального token в URL.
- Случайный пароль PostgreSQL.
- Отдельное место для backup вне VPS.
- Решение владельца о границе доступа: сейчас app-level email allowlist нет.

### Перед стартом

Не деплоить, пока P0 из
[аудита](DEPLOY_READINESS_2026-08-03.md#p0--закрыть-до-первой-внешней-pvp-сессии)
не закрыты.

## 3. Подготовить exact release commit

В локальном чистом checkout:

~~~powershell
git status --short
git rev-parse HEAD

cd VladStoneAPI
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .

cd ..\VladStoneWeb
npm ci
npm run build
~~~

Условия:

1. `git status --short` ничего не выводит.
2. Все три quality gates зелёные.
3. Известен exact SHA, который поедет на сервер.
4. CI этого SHA зелёный; не выкладывать просто «последний master» без фиксации
   SHA.

Production secrets не должны находиться в commit, shell history, remote URL
или скриншотах.

## 4. Подготовить VPS

Подключиться по SSH-ключу и обновить систему:

~~~bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl git
~~~

Установить Docker Engine и Compose plugin из официального apt repository.
Актуальные команды брать из
[Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
Короткая последовательность для Ubuntu:

~~~bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc" |
  sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
~~~

Не полагаться только на UFW для published Docker ports: Docker отдельно
предупреждает, что такие порты могут обходить правила UFW. Надёжнее сначала
ограничить входящие соединения provider firewall/security group:

- 80/tcp и 443/tcp — из интернета;
- 22/tcp — с IP владельца, если адрес стабилен;
- всё остальное — deny.

Создать каталог и получить код:

~~~bash
sudo mkdir -p /opt/vladstone
sudo chown <linux-user>:<linux-user> /opt/vladstone
git clone git@github.com:SergKoster/VladStone.git /opt/vladstone
cd /opt/vladstone
git fetch --prune origin
git checkout <deploy-sha>
git status --short
~~~

Для private repository добавить public half отдельного read-only SSH key в
GitHub Deploy keys. Private key остаётся только на VPS. Не вставлять PAT в
`git remote -v`.

## 5. Настроить DNS

У DNS-провайдера:

1. Создать `A` record: `play.example.com` → публичный IPv4 VPS.
2. Не создавать `AAAA`, пока IPv6 действительно не настроен и 80/443 по нему
   доступны. Неверный AAAA может сломать достижимость и получение сертификата.
3. Дождаться обновления DNS.

Проверка с локального компьютера:

~~~bash
nslookup play.example.com
~~~

Caddy получает и продлевает сертификат автоматически, если имя в Caddyfile
разрешается в VPS и публичные 80/443 доступны. См.
[Caddy HTTPS quick-start](https://caddyserver.com/docs/quick-starts/https).

## 6. Настроить Google OAuth

В Google Cloud:

1. Создать OAuth consent screen.
2. Создать OAuth client типа `Web application`.
3. Добавить точный Authorized redirect URI:
   `https://play.example.com/api/auth/google/callback`.
4. Для управляемого alpha добавить аккаунты тестировщиков в audience/test
   users.
5. Сохранить Client ID и Client Secret только в `deploy/.env`.

Scheme, host, path и trailing slash redirect URI должны совпасть точно, иначе
Google вернёт `redirect_uri_mismatch`. Текущий backend запрашивает только
`openid email` и создаёт собственную refresh-session.

Важно: Google test users не считать полноценным allowlist приложения.
Текущий backend сам не ограничивает email. Если alpha должна быть реально
закрытой, до публикации нужен отдельный app-level allowlist либо явно принятый
владельцем риск открытого входа через Google.

## 7. Заполнить конфигурацию и выполнить первый старт

На VPS:

~~~bash
cd /opt/vladstone/deploy
cp .env.prod.example .env
chmod 600 .env
openssl rand -hex 32
nano .env
~~~

Результат `openssl` вставить в `POSTGRES_PASSWORD`. Hex выбран специально:
так пароль безопасно входит в PostgreSQL connection URL без дополнительного
URL-encoding.

Минимально обязательные значения:

~~~dotenv
DOMAIN=play.example.com
POSTGRES_PASSWORD=<random-hex>

GOOGLE_OAUTH_CLIENT_ID=<client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<client-secret>
GOOGLE_OAUTH_REDIRECT_URI=https://play.example.com/api/auth/google/callback
FRONTEND_URL=https://play.example.com

ENVIRONMENT=production
API_PREFIX=/api
COOKIE_SECURE=true
CORS_ORIGINS='["https://play.example.com"]'
~~~

Во всех четырёх местах должен быть один и тот же public origin. Не смешивать
`localhost` и `127.0.0.1`, не добавлять trailing slash в `FRONTEND_URL` и
`CORS_ORIGINS`.

Проверить наличие значений, не печатая секреты:

~~~bash
cd /opt/vladstone/deploy
for required_name in DOMAIN POSTGRES_PASSWORD GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET GOOGLE_OAUTH_REDIRECT_URI FRONTEND_URL ENVIRONMENT COOKIE_SECURE CORS_ORIGINS; do
  if ! grep -Eq "^$required_name=.+$" .env; then
    echo "Missing: $required_name"
    exit 1
  fi
done

sudo docker compose --env-file .env -f docker-compose.prod.yml config --quiet
~~~

Не запускать `docker compose config` без `--quiet` в публичный лог: resolved
config может содержать secrets.

Собрать и запустить:

~~~bash
cd /opt/vladstone/deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml pull postgres
sudo docker compose --env-file .env -f docker-compose.prod.yml build --pull
sudo docker compose --env-file .env -f docker-compose.prod.yml up -d postgres
sudo docker compose --env-file .env -f docker-compose.prod.yml run --rm api alembic upgrade head
sudo docker compose --env-file .env -f docker-compose.prod.yml up -d --remove-orphans
sudo docker compose --env-file .env -f docker-compose.prod.yml ps
~~~

API container ещё раз выполняет `alembic upgrade head` перед uvicorn; команда
идемпотентна. Отдельный migration step выше делает ошибку видимой до обычного
старта приложения.

Проверить эффективные не-секретные настройки:

~~~bash
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T api python -c "from app.core.config import get_settings; s=get_settings(); print(s.environment, s.frontend_url, s.cookie_secure, s.cors_origins)"
~~~

Ожидается `production`, точный HTTPS origin, `True` и список с тем же origin.

## 8. Приёмочный smoke перед ссылкой друзьям

### 8.1 Контейнеры, БД и HTTPS

~~~bash
cd /opt/vladstone/deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml ps
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres pg_isready -U vladstone -d vladstone
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T api alembic current
sudo docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 api web postgres
~~~

С внешнего компьютера:

~~~bash
curl -fsS https://play.example.com/api/health
curl -fsS https://play.example.com/api/auth/providers
curl -I https://play.example.com/
~~~

Ожидается:

- health: `status=ok` и `environment=production`;
- providers: `google=true`, `dev_login=false`, `email_code=false`;
- HTTP автоматически уходит на HTTPS;
- сертификат доверенный и выдан нужному host;
- в browser console нет mixed-content/CORS ошибок;
- снаружи не доступны 5432/6379/8000.

`/api/health` пока не проверяет БД, поэтому `pg_isready` и `alembic current`
обязательны отдельно.

### 8.2 Auth smoke

1. Открыть сайт в чистом профиле браузера.
2. Нажать Google login.
3. Проверить возврат ровно на `https://play.example.com`.
4. Обновить страницу: сессия сохраняется.
5. Выйти и убедиться, что защищённые routes больше не доступны.
6. Повторить вторым Google account.

При ошибке сначала проверить exact redirect URI и три URL в `.env`. Не
логировать authorization code, cookie или client secret.

### 8.3 PvE smoke

1. Запустить бой с ботом.
2. Поставить карту, изменить план, нажать `Готов`.
3. Дождаться server timer resolve и WS update.
4. Перезагрузить страницу во время planning.
5. Убедиться, что active match и сохранённый план восстановились.

### 8.4 Обязательный two-device PvP smoke

Использовать два разных Google account:

- устройство A — desktop через домашнюю сеть;
- устройство B — телефон через мобильную сеть, не тот же LAN.

Матрица:

- [ ] A создаёт invite, копирует ссылку и остаётся в lobby.
- [ ] B открывает deep link незалогиненным, проходит Google round-trip и
      попадает в правильный match.
- [ ] Self-join A отклоняется.
- [ ] После join оба автоматически видят один матч.
- [ ] У обоих своя сторона снизу; колонки не зеркалятся.
- [ ] Ready только A не резолвит ход; ready A+B даёт ровно один resolve.
- [ ] Оба разных плана одного хода применились.
- [ ] Рука соперника нигде не видна.
- [ ] Reload A и B во время planning сохраняет/восстанавливает план.
- [ ] Reload во время playback быстро показывает актуальное состояние без
      второго resolve.
- [ ] Отключение сети одного клиента не мешает второму; после возврата первый
      догоняет состояние.
- [ ] Cancelled invite даёт конечный экран, повторный join не стартует матч.
- [ ] Игра не получает `429` при нормальном полном матче.
- [ ] API/web/postgres logs не содержат traceback, invite token или secret.

Во время первого теста оператор держит открытыми:

~~~bash
sudo docker compose --env-file .env -f docker-compose.prod.yml logs -f --tail=200 api web postgres
~~~

Результаты и ощущения после матча записать в
[PLAYTEST_NOTES.md](PLAYTEST_NOTES.md). Только после этого Фаза 4 может быть
закрыта в ROADMAP.

## 9. Backup и проверка восстановления

Docker volume — не backup: удаление VPS, volume или ошибка миграции уничтожит
его вместе с данными.

Создать закрытый каталог:

~~~bash
sudo install -d -m 700 -o <linux-user> -g <linux-user> /opt/vladstone-backups
~~~

Перед первым обновлением и затем автоматически раз в сутки:

~~~bash
cd /opt/vladstone/deploy
backup_path="/opt/vladstone-backups/vladstone_$(date -u +%Y%m%dT%H%M%SZ).dump"
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres pg_dump -U vladstone -d vladstone -Fc > "$backup_path"
test -s "$backup_path"
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres pg_restore --list < "$backup_path" > /dev/null
echo "$backup_path"
~~~

Custom format `-Fc` предназначен для `pg_restore` и удобен для проверки/
выборочного восстановления. Backup считается существующим только когда:

1. команда завершилась без warning/error;
2. файл непустой и `pg_restore --list` его читает;
3. копия ушла на другое физическое место;
4. restore drill был выполнен на отдельной БД/VPS.

Минимальная политика для alpha: ежедневная off-host копия и отдельный backup
перед каждой миграцией. Не хранить единственную копию рядом с Docker volume.

## 10. Обновление

Обновлять между матчами.

~~~bash
cd /opt/vladstone
git status --short
git rev-parse HEAD
~~~

Записать предыдущий SHA и убедиться, что server checkout чистый. Затем сделать
backup по §9 и перейти на заранее проверенный commit:

~~~bash
git fetch --prune origin
git checkout <new-deploy-sha>

cd /opt/vladstone/deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml config --quiet
sudo docker compose --env-file .env -f docker-compose.prod.yml build
sudo docker compose --env-file .env -f docker-compose.prod.yml run --rm api alembic upgrade head
sudo docker compose --env-file .env -f docker-compose.prod.yml up -d --remove-orphans
sudo docker compose --env-file .env -f docker-compose.prod.yml ps
~~~

После обновления повторить §8.1, login smoke и короткий PvE/PvP smoke.

Не выполнять бездумный `git pull && up --build`:

- непонятно, какой SHA реально выложен;
- build и migration ошибки смешиваются с рестартом;
- rollback становится менее определённым.

## 11. Rollback

### Только код, без несовместимой миграции

~~~bash
cd /opt/vladstone
git checkout <previous-deploy-sha>
cd deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml build
sudo docker compose --env-file .env -f docker-compose.prod.yml up -d --remove-orphans
~~~

Затем повторить smoke.

### Есть несовместимая миграция или повреждение данных

Не запускать `alembic downgrade` вслепую. Например downgrade
`0003_pvp_invites` удаляет таблицы invite/participants. Правильная стратегия:

1. остановить API;
2. сохранить аварийную копию текущей БД;
3. либо выпустить forward-fix, либо восстановить проверенный pre-deploy backup;
4. запустить совместимый code SHA;
5. повторить полный smoke.

Восстановление основной БД уничтожает её текущее состояние и должно
выполняться только после явного выбора нужного backup:

~~~bash
cd /opt/vladstone/deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml stop api
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres dropdb -U vladstone --force vladstone
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres createdb -U vladstone vladstone
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres pg_restore -U vladstone -d vladstone --no-owner < /absolute/path/to/selected.dump
sudo docker compose --env-file .env -f docker-compose.prod.yml up -d api web
~~~

Сначала отработать это на отдельной тестовой БД/VPS.

## 12. Наблюдение и регулярное обслуживание

Полезные read-only команды:

~~~bash
cd /opt/vladstone/deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml ps
sudo docker compose --env-file .env -f docker-compose.prod.yml logs --since=30m api
sudo docker compose --env-file .env -f docker-compose.prod.yml logs --since=30m web
sudo docker compose --env-file .env -f docker-compose.prod.yml logs --since=30m postgres
sudo docker stats --no-stream
df -h
sudo docker system df
~~~

До постоянного сервера нужны:

- log rotation;
- uptime check внешнего `/api/health`;
- DB-aware readiness;
- alert по 5xx, restart loop и диску;
- heartbeat timer worker;
- Sentry или эквивалент для backend/frontend;
- ежедневный backup job и уведомление о его провале.

`restart: unless-stopped` уже задан всем production services, поэтому после
restart Docker/host контейнеры поднимутся автоматически, если не были явно
остановлены.

## 13. Диагностика типовых ошибок

### Сайт не получает HTTPS

- Проверить A/AAAA records.
- Проверить provider firewall для 80/443.
- Убедиться, что другой процесс не занял порты.
- Посмотреть `docker compose logs web`.
- Не проксировать домен через чужой TLS/CDN на первом smoke, пока прямой Caddy
  flow не подтверждён.

### `502 Bad Gateway`

- `docker compose ps`: API мог ещё выполнять migration.
- `docker compose logs api postgres`.
- `pg_isready` и `alembic current`.
- Проверить свободный диск.

### Google `redirect_uri_mismatch`

- Сравнить exact URI в Google Cloud и `GOOGLE_OAUTH_REDIRECT_URI`.
- Проверить HTTPS, host, path и отсутствие лишнего trailing slash.
- Проверить `FRONTEND_URL`.

### После логина `401`

- `COOKIE_SECURE=true` требует реальный HTTPS.
- Frontend и API должны быть на одном host.
- Проверить, что browser принял `refresh_token` cookie.
- Проверить server clock: OAuth token и session expiry зависят от времени.

### WS постоянно переподключается

- `CORS_ORIGINS` должен содержать точный browser Origin.
- Caddy обязан проксировать `/ws/*` в API.
- Проверить API restart loop и `web` logs.
- Убедиться, что открыт именно `wss://` при HTTPS.

### Матч перестал принимать план

- Проверить HTTP status: `409` означает устаревший turn/deadline, `429` —
  исчерпан rate bucket.
- Посмотреть API logs и текущее состояние через обычный reconnect.
- Не перезапускать БД и не редактировать `state_json` вручную.

## 14. Официальные эксплуатационные ссылки

- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/)
- [Docker json-file log rotation](https://docs.docker.com/engine/logging/drivers/json-file/)
- [Caddy Automatic HTTPS](https://caddyserver.com/docs/quick-starts/https)
- [Google OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google OAuth app audience/testing](https://support.google.com/cloud/answer/15549945)
- [PostgreSQL `pg_dump`](https://www.postgresql.org/docs/17/app-pgdump.html)
