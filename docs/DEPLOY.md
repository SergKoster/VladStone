# Деплой VladStone для PvP с другом

Цель этой инструкции: поднять игру на одном VPS, войти двумя Google-аккаунтами
и сыграть PvP по invite-ссылке. Это **не** инструкция полноценного публичного
релиза.

Текущая оценка готовности:
[DEPLOY_READINESS_2026-08-03.md](DEPLOY_READINESS_2026-08-03.md).

## 1. Как это будет работать

~~~text
Ты и друг
   │
   │ HTTPS / WSS
   ▼
Caddy на VPS
   ├─ раздаёт React frontend
   ├─ /api/* → FastAPI
   └─ /ws/*  → FastAPI WebSocket
                    │
                    ▼
                PostgreSQL
~~~

Всё работает на одном домене, например `play.example.com`. Caddy сам получает
HTTPS-сертификат. API, WebSocket и cookies остаются same-origin.

На сервере будут три containers:

- `web` — Caddy и собранный frontend;
- `api` — FastAPI, PvP timer и WebSocket channels;
- `postgres` — база пользователей и матчей.

Нужен один API container: realtime и timer worker сейчас process-local.

## 2. Что потребуется

- VPS с Ubuntu 24.04, минимум 2 ГБ RAM и 20 ГБ диска.
- Домен или поддомен с возможностью создать A record.
- Google Cloud project и OAuth Web Client.
- Два разных Google-аккаунта: твой и друга.
- SSH-доступ к VPS.
- Доступ VPS к репозиторию GitHub.

Для одного теста не нужны Redis, Kubernetes, Sentry, CDN, отдельный staging,
load balancer или почтовый сервис.

## 3. Подготовить код

Общий PvP rate-limit уже исправлен: каждый authenticated player расходует свой
bucket, а regression test не даёт второму игроку унаследовать лимит создателя.

Выбрать exact commit и проверить его в чистом checkout:

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

Ожидается:

- `git status --short` пустой;
- pytest и ruff зелёные;
- frontend build зелёный;
- SHA commit записан — на VPS будет выложен именно он.

## 4. Подготовить домен и Google OAuth

### DNS

Создать A record:

~~~text
play.example.com → <публичный IPv4 VPS>
~~~

Не добавлять AAAA record, если IPv6 на VPS не настроен. Для автоматического
HTTPS Caddy сервер должен быть доступен из интернета по TCP 80 и 443.

Проверить DNS:

~~~bash
nslookup play.example.com
~~~

### Google Cloud

1. Создать OAuth consent screen.
2. Создать OAuth Client ID типа `Web application`.
3. Добавить точный Authorized redirect URI:

~~~text
https://play.example.com/api/auth/google/callback
~~~

4. Скопировать Client ID и Client Secret.
5. При необходимости добавить свой аккаунт и аккаунт друга в test users.

Scheme, host, path и trailing slash должны совпасть точно. Иначе Google вернёт
`redirect_uri_mismatch`.

Для короткого теста отдельный allowlist в приложении не нужен: не публикуй
домен, отправляй только invite-ссылку другу и после игры останови containers.

## 5. Подготовить VPS

Подключиться по SSH и установить базовые пакеты:

~~~bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl git
~~~

Установить Docker Engine и Compose plugin по
[официальной инструкции Docker](https://docs.docker.com/engine/install/ubuntu/).
После установки проверить:

~~~bash
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
~~~

В firewall VPS открыть:

- 80/tcp;
- 443/tcp;
- SSH-порт для себя.

Не открывать 5432, 6379 и 8000. Production Compose публикует только web 80/443.

Получить код:

~~~bash
sudo mkdir -p /opt/vladstone
sudo chown <linux-user>:<linux-user> /opt/vladstone
git clone git@github.com:SergKoster/VladStone.git /opt/vladstone
cd /opt/vladstone
git fetch --prune origin
git checkout <deploy-sha>
git status --short
~~~

Если repository private, на VPS нужен read-only GitHub deploy key. Не вставлять
personal token в clone URL.

## 6. Настроить и запустить игру

Создать production env:

~~~bash
cd /opt/vladstone/deploy
cp .env.prod.example .env
chmod 600 .env
openssl rand -hex 32
nano .env
~~~

Вывод `openssl` вставить в `POSTGRES_PASSWORD`. Заполненный файл:

~~~dotenv
DOMAIN=play.example.com
POSTGRES_PASSWORD=<random-hex>

GOOGLE_OAUTH_CLIENT_ID=<client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<client-secret>
GOOGLE_OAUTH_REDIRECT_URI=https://play.example.com/api/auth/google/callback
FRONTEND_URL=https://play.example.com

APP_NAME="VladStone API"
ENVIRONMENT=production
API_PREFIX=/api
COOKIE_SECURE=true
CORS_ORIGINS='["https://play.example.com"]'
~~~

`DOMAIN`, `GOOGLE_OAUTH_REDIRECT_URI`, `FRONTEND_URL` и `CORS_ORIGINS` должны
указывать на один host.

Проверить Compose без вывода resolved secrets:

~~~bash
sudo docker compose --env-file .env -f docker-compose.prod.yml config --quiet
~~~

Собрать и запустить:

~~~bash
sudo docker compose --env-file .env -f docker-compose.prod.yml pull postgres
sudo docker compose --env-file .env -f docker-compose.prod.yml build --pull
sudo docker compose --env-file .env -f docker-compose.prod.yml up -d postgres
sudo docker compose --env-file .env -f docker-compose.prod.yml run --rm api alembic upgrade head
sudo docker compose --env-file .env -f docker-compose.prod.yml up -d --remove-orphans
sudo docker compose --env-file .env -f docker-compose.prod.yml ps
~~~

Миграции также выполняются при обычном старте API. Отдельная команда нужна,
чтобы сразу увидеть ошибку до запуска сайта.

## 7. Проверка перед матчем

На VPS:

~~~bash
cd /opt/vladstone/deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml ps
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres pg_isready -U vladstone -d vladstone
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T api alembic current
sudo docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 api web postgres
~~~

С компьютера:

~~~bash
curl -fsS https://play.example.com/api/health
curl -fsS https://play.example.com/api/auth/providers
curl -I https://play.example.com/
~~~

Ожидается:

- health возвращает `status: ok` и `environment: production`;
- providers возвращает `google: true`;
- `dev_login` и `email_code` равны `false`;
- сайт открывается по HTTPS без предупреждения сертификата;
- HTTP переводится на HTTPS;
- в browser console нет CORS и mixed-content ошибок.

Затем проверить вход:

1. Открыть сайт в чистом browser profile.
2. Нажать Google login.
3. Войти своим аккаунтом.
4. Обновить страницу и убедиться, что сессия сохранилась.
5. Повторить с аккаунтом друга на втором устройстве.

## 8. Как сыграть PvP

1. Ты входишь на `https://play.example.com`.
2. Нажимаешь `Пригласить друга`.
3. Копируешь полученную invite-ссылку.
4. Отправляешь её другу обычным сообщением.
5. Друг открывает ссылку на другом устройстве и входит своим Google account.
6. Lobby автоматически переводит обоих в один PvP-матч.
7. Каждый расставляет карты и нажимает `Готов`.
8. Сервер применяет оба плана одним resolve и рассылает результат по WS.

Во время первого матча держать открытыми логи:

~~~bash
cd /opt/vladstone/deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml logs -f --tail=200 api web postgres
~~~

В первом матче проверить:

- оба видят свою сторону снизу;
- оба видят только свою руку;
- готовность одного игрока не запускает resolve;
- готовность обоих запускает ровно один resolve;
- несколько ходов проходят без `429` и traceback;
- reload во время planning возвращает в тот же матч;
- краткое отключение сети не ломает матч;
- повторное использование invite не создаёт третьего участника.

После матча записать обратную связь в
[PLAYTEST_NOTES.md](PLAYTEST_NOTES.md).

## 9. После игры

Если сервер пока больше не нужен:

~~~bash
cd /opt/vladstone/deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml down
~~~

Команда останавливает containers, но сохраняет PostgreSQL volume и Caddy
certificate data. Не добавлять `-v`: этот флаг удалит volumes и данные.

Повторный запуск:

~~~bash
sudo docker compose --env-file .env -f docker-compose.prod.yml up -d
~~~

Посмотреть состояние:

~~~bash
sudo docker compose --env-file .env -f docker-compose.prod.yml ps
sudo docker compose --env-file .env -f docker-compose.prod.yml logs --since=30m api web postgres
~~~

## 10. Как обновить код

Обновлять между матчами:

~~~bash
cd /opt/vladstone
git fetch --prune origin
git checkout <new-tested-sha>

cd deploy
sudo docker compose --env-file .env -f docker-compose.prod.yml build
sudo docker compose --env-file .env -f docker-compose.prod.yml run --rm api alembic upgrade head
sudo docker compose --env-file .env -f docker-compose.prod.yml up -d --remove-orphans
sudo docker compose --env-file .env -f docker-compose.prod.yml ps
~~~

После обновления повторить проверки из §7.

## 11. Частые проблемы

### Caddy не получает сертификат

- A record ещё не обновился.
- Порты 80/443 закрыты provider firewall.
- Создан неправильный AAAA record.
- Порт уже занят другим процессом.

Смотреть:

~~~bash
sudo docker compose --env-file .env -f docker-compose.prod.yml logs web
~~~

### Google пишет `redirect_uri_mismatch`

Сравнить exact URI в Google Cloud и `GOOGLE_OAUTH_REDIRECT_URI`. Особенно
проверить `https`, host, path и trailing slash.

### Сайт возвращает `502`

~~~bash
sudo docker compose --env-file .env -f docker-compose.prod.yml ps
sudo docker compose --env-file .env -f docker-compose.prod.yml logs api postgres
~~~

Обычно API ещё выполняет migration либо не может подключиться к PostgreSQL.

### WebSocket постоянно переподключается

- `CORS_ORIGINS` не совпадает с browser Origin.
- Открыт `ws://` вместо `wss://`.
- API перезапускается.
- Caddy не проксирует `/ws/*`.

### План получает `409` или `429`

- `409`: ход уже завершён по ready/deadline; клиент должен получить свежий
  state по WS или polling.
- `429`: конкретный игрок исчерпал свой rate-limit. Другой участник использует
  независимый bucket.
