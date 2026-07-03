# VladStone

[![CI](https://github.com/SergKoster/VladStone/actions/workflows/ci.yml/badge.svg)](https://github.com/SergKoster/VladStone/actions/workflows/ci.yml)

Карточная MMO-игра в разработке. Текущий фокус: web MVP, отдельный FastAPI backend, React frontend, Docker-first запуск и изолированный модуль боевых правил.

## Структура

- `VladStoneAPI/` - FastAPI backend.
- `VladStoneWeb/` - React/Vite frontend.
- `TODO.md` - roadmap и backlog.
- `docker-compose.yml` - локальный запуск API, Web, PostgreSQL и Redis.

## Локальный запуск

Самый простой вариант на Windows:

Двойной клик по файлу:

- `start-dev.bat`

Или из терминала:

```powershell
.\start-dev.bat
```

PowerShell-вариант:

```powershell
.\start-dev.ps1
```

Остановка фоновых dev-процессов:

```powershell
.\stop-dev.ps1
```

Если PowerShell пишет, что scripts are disabled, запускай `.bat`-файл. Он включает `ExecutionPolicy Bypass` только для текущего запуска.

Backend:

```powershell
cd VladStoneAPI
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Миграции БД для серверного/контейнерного запуска:

```powershell
cd VladStoneAPI
.\.venv\Scripts\python -m alembic upgrade head
```

В `local` и `test` режиме API все еще может создать таблицы автоматически для удобства разработки. Для production нужно считать Alembic обязательным шагом перед стартом API.

Frontend:

```powershell
cd VladStoneWeb
npm install
npm run dev
```

Docker:

```powershell
docker compose up --build
```

Docker-сборка запускает API после `alembic upgrade head`, а web-контейнер отдает production-сборку Vite через `npm run preview`.

Адреса:

- Web: `http://localhost:5173`
- API healthcheck: `http://localhost:8001/api/health`
- Combat demo: `http://localhost:8001/api/combat/demo`

## Архитектура боя

- `POST /api/combat/start` создает матч на backend и сохраняет его состояние.
- `POST /api/combat/resolve` принимает только `match_id` и список планируемых постановок карт.
- Клиент больше не отправляет полный объект матча обратно на сервер.
- Награда за завершенный бой начисляется по серверному состоянию матча и защищена от повторной выдачи.

## Проверки

Backend:

```powershell
cd VladStoneAPI
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
```

Frontend:

```powershell
cd VladStoneWeb
npm run build
```

## Google Login

Пока работает локальный dev-вход через Google-кнопку. Для настоящего OAuth нужно создать Google Cloud OAuth client. Детали: [docs/google-oauth.md](docs/google-oauth.md).
