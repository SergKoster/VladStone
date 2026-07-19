# Модуль 8. Инфраструктура и деплой

> Цель — понимать каждый слой прод-схемы из [DEPLOY.md](../DEPLOY.md) и уметь
> самому задеплоить проект на чистый VPS (это и есть Фаза P4 — деплой друзьям).

## Что нужно знать на выходе

- Docker: образ vs контейнер, Dockerfile, слои, multi-stage build (наш
  фронт собирается именно так).
- Docker Compose: сервисы, сети, volumes, env; чем наш
  `docker-compose.prod.yml` отличается от dev-запуска.
- Reverse proxy: зачем Caddy, что такое same-origin (`/api`, `/ws`), авто-HTTPS
  (Let's Encrypt под капотом).
- PostgreSQL в проде: контейнер, volume с данными, бэкапы; миграции на старте
  (`alembic upgrade head`).
- Переменные окружения как контракт прода: `ENVIRONMENT=production` гасит
  dev-функции, `COOKIE_SECURE=true`.
- GitHub Actions: как читается workflow, когда он запускается.

## Ресурсы

1. [Официальный Docker Get Started](https://docs.docker.com/get-started/) —
   основа: образы, контейнеры, volumes, compose.
2. [DevOps with Docker (Университет Хельсинки, бесплатно)](https://devopswithdocker.com/) —
   лучший бесплатный курс: Dockerfile, compose, CI/CD; практический.
3. [Документация Caddy](https://caddyserver.com/docs/) — раздел
   Getting Started + reverse_proxy.
4. [Docker: официальный образ Postgres](https://www.docker.com/blog/how-to-use-the-postgres-docker-official-image/) —
   как правильно поднимать БД в контейнере.
5. [GitHub Actions: Understanding workflows](https://docs.github.com/en/actions/learn-github-actions/understanding-github-actions).

## Где это у нас

- `deploy/docker-compose.prod.yml` — вся прод-схема одним файлом; читать
  вместе с [DEPLOY.md](../DEPLOY.md) и ARCHITECTURE §2.5.
- `VladStoneWeb/Dockerfile` — multi-stage: build фронта → Caddy со статикой.
- `VladStoneAPI` Dockerfile/entrypoint — где выполняется `alembic upgrade head`.
- `.github/workflows/ci.yml` — CI.
- `start-dev.bat` — для контраста: dev-запуск без контейнеров.

## Практика

1. Локально собрать прод-образ фронта (`docker build`) и разобрать его слои:
   что попало в финальный образ, а что осталось в build-стадии.
2. Поднять весь прод-компоуз локально (или максимально близко к нему),
   зайти через Caddy и убедиться, что `/api` проксируется. Понять, почему в
   этой схеме нет CORS-проблем.
3. Написать шпаргалку «деплой с нуля»: последовательность команд от чистого
   VPS до работающей игры — по DEPLOY.md, но своими словами. Пробелы в
   понимании вскроются мгновенно.
4. Потренировать бэкап/восстановление: `pg_dump` из контейнера БД и
   восстановление в свежий контейнер.
5. Разобрать риск §8.22 (незафиксированные версии Python-зависимостей):
   почему `>=` в pyproject — проблема для воспроизводимости, и что такое
   lock-файл.

## Вопросы для самопроверки

- Чем контейнер отличается от виртуальной машины? Что происходит с данными
  контейнера БД при его пересоздании — и причём тут volume?
- Зачем multi-stage build, если можно собрать всё в одном образе?
- Почему прод живёт на одном домене (same-origin), и какую боль это убирает?
- Что произойдёт при деплое новой версии с миграцией: в каком порядке
  обновляются БД и код?
