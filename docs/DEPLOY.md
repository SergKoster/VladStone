# Деплой VladStone на VPS

Вся игра живёт на одном сервере и одном домене: Caddy раздаёт фронт и
проксирует `/api` + `/ws` в FastAPI; рядом PostgreSQL. HTTPS-сертификат Caddy
получает и продлевает сам. Файлы деплоя — в [`deploy/`](../deploy/).

```
Браузер ──https──> Caddy (контейнер web)
                     ├─ статика фронта (/srv)
                     ├─ /api/* ──> api:8000 (uvicorn, 1 воркер)
                     └─ /ws/*  ──> api:8000 (WebSocket)
                                      └──> postgres:5432
```

## Что купить (один раз)

1. **VPS**: Ubuntu 24.04, минимум 2 ГБ RAM (хватит на 100–200 CCU с запасом).
2. **Домен** (например `vladstone.ru` или поддомен). В DNS — A-запись на IP VPS.

## Первый запуск

```bash
# 1. На VPS: установить Docker
curl -fsSL https://get.docker.com | sh

# 2. Забрать код
git clone <адрес-репозитория> vladstone && cd vladstone/deploy

# 3. Настроить секреты
cp .env.prod.example .env
nano .env        # домен, пароль БД (openssl rand -hex 24), Google-креды

# 4. Собрать и запустить всё
docker compose -f docker-compose.prod.yml up -d --build
```

Открыть `https://<домен>` — должен появиться экран входа с одной кнопкой
Google (email-вход и dev-login в проде выключены автоматически через
`ENVIRONMENT=production`).

**Google Cloud Console**: в OAuth-клиент добавить redirect URI
`https://<домен>/api/auth/google/callback` (см. [google-oauth.md](google-oauth.md));
тестовые аккаунты друзей — в test users, пока consent screen в testing-режиме.

## Обновление игры

```bash
cd vladstone && git pull && cd deploy
docker compose -f docker-compose.prod.yml up -d --build
```

Миграции БД применяются сами при старте API (`alembic upgrade head` в
Dockerfile). Даунтайм — секунды.

## Посмотреть, что происходит

```bash
docker compose -f docker-compose.prod.yml ps          # статусы
docker compose -f docker-compose.prod.yml logs -f api # логи API
```

## Важные ограничения (не менять, пока не решим иначе)

- **Один uvicorn-воркер.** WebSocket-каналы и таймер ходов живут в памяти
  процесса (ARCHITECTURE §2.4): несколько воркеров = игроки в разных
  процессах не увидят ходы друг друга. Масштабирование — Р2 (Redis pub/sub).
- **Postgres не выставлен наружу** — доступен только контейнерам.
- `deploy/.env` никогда не коммитить (в `.gitignore`).

## Ещё не сделано (Фаза 6)

- Бэкапы Postgres (до первых ценных аккаунтов — обязательно).
- Structured logging + Sentry.
- Смоук-нагрузка на 100–200 CCU.
