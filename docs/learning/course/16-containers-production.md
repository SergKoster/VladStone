# Глава 16. Docker, production и эксплуатация

## Результат

Production — процесс воспроизводимой доставки, изменения schema, наблюдения,
восстановления и отката. Контейнер упаковывает filesystem/process config, но
не заменяет безопасность, backup или orchestration.

После главы ты сможешь:

- объяснить image, layer, container, network и volume;
- читать multi-stage Dockerfile и Compose;
- провести запрос через Caddy в API/Postgres;
- планировать migration/deploy/rollback без несовместимого окна;
- делать и проверять restore backup;
- управлять secrets и reproducible dependencies;
- составить безопасный production runbook.

## Входной сценарий

Новый image API собран, migration добавляет `NOT NULL` column, старый
container ещё работает. Что может сломаться, если migration запускается
автоматически перед новым uvicorn? Какой rollback возможен после записи новых
данных?

## 1. Image и container

**Image** — immutable шаблон filesystem/config из layers. **Container** —
запущенный process с writable layer, namespaces/cgroups и подключёнными
network/volumes.

Container не VM: разделяет kernel host. Удаление container удаляет его
writable layer; named volume живёт отдельно. Поэтому Postgres data находится
в `postgres-data`, а не внутри disposable layer.

Image должен быть:

- воспроизводимым из commit + lock;
- минимальным;
- без secrets;
- запускаемым non-root, где возможно;
- помеченным immutable tag/digest для rollback.

## 2. Layers и build cache

Dockerfile выполняется сверху вниз; изменение шага инвалидирует его и
последующие layers. Поэтому сначала копируют dependency manifests, ставят
зависимости, затем source:

```dockerfile
COPY pyproject.toml ./
RUN pip install --no-cache-dir "."
COPY app ./app
```

Но текущие Python dependencies заданы нижними границами без lock:
одинаковый commit в разные дни может установить разные версии. Это открытый
риск `ARCHITECTURE §8.22`. Профессиональный fix: проверяемый lock/constraints
с hashes, одинаковый путь CI и Docker, controlled update PR.

## 3. Multi-stage frontend

`VladStoneWeb/Dockerfile`:

```text
node build stage
  npm ci
  tsc + vite build → /app/dist

prod stage: caddy
  copy only dist → /srv
```

Build tools/node_modules не попадают в final prod image. `VITE_API_BASE_URL`
встраивается при build; изменение runtime env Caddy не перепишет уже
собранный JS.

Dev target здесь запускает `vite preview`, а не HMR dev server — читай
фактический CMD, не доверяй имени target.

## 4. Compose

Production services:

- `postgres`: internal only, named volume, healthcheck;
- `api`: build backend, env/secrets, depends on healthy Postgres;
- `web`: Caddy/static, ports 80/443, persistent certificate data.

Service names работают как DNS внутри Compose network:

```text
api → postgres:5432
web → api:8000
```

Postgres не публикует host port в production compose, уменьшая поверхность.
`depends_on: service_healthy` упорядочивает initial start, но не гарантирует,
что dependency никогда не упадёт позже. Application всё равно требует
timeout/recovery.

## 5. Caddy и same-origin

`deploy/Caddyfile`:

```text
https://DOMAIN
 ├─ /api/* → api:8000
 ├─ /ws/*  → api:8000
 └─ files /srv, SPA fallback /index.html
```

Caddy получает/продлевает TLS certificate и завершает HTTPS. API запускается
с proxy headers, поэтому доверительная модель forwarded headers важна:
при прямом публичном доступе attacker мог бы подделать их. В compose API не
публикует port наружу; Caddy — доверенный proxy.

`VITE_API_BASE_URL=/api` создаёт один browser origin и правильный `wss`.

## 6. Process model

API CMD:

```text
alembic upgrade head
&&
uvicorn ... --host 0.0.0.0 --port 8000
```

Миграция падает → uvicorn не стартует. Хорошо: несовместимый app не начинает
работу. Но автоматическая migration в каждом replica опасна при multi-instance:
несколько starters гоняются, long lock задерживает readiness, backward
compatibility не гарантирована.

Для текущего single-instance это простой осознанный workflow. Перед
горизонтальным scaling migration станет отдельным controlled job/step.

Один uvicorn worker обязателен сейчас: sockets и timer channel in-memory.
Несколько workers без Redis routing создадут функциональную ошибку, не
«ускорение».

## 7. Secrets

`deploy/.env` не коммитится. Но env доступен process/container inspection и
может случайно попасть в logs. Минимум:

- отдельные production credentials;
- случайные сильные значения;
- least privilege DB/OAuth;
- rotation runbook;
- не печатать config dump;
- ограничить доступ к VPS/CI secrets;
- никогда не bake в image/build args frontend.

Frontend bundle публичен: любой `VITE_*` видит пользователь. Там не может быть
client secret.

## 8. Migration и deploy

Для single VPS безопаснее explicit sequence:

1. CI: tests/lint/build + migration review;
2. backup/restore confidence для risky schema;
3. build immutable images;
4. определить backward compatibility;
5. применить expand migration;
6. запустить new app/readiness;
7. smoke test auth/health/API/WS;
8. наблюдать metrics/logs;
9. contract migration позже.

Текущий `docker compose up -d --build` объединяет шаги и даёт секунды downtime,
но rollback не описан. До друзей нужен runbook: previous commit/image,
DB compatibility, команда и критерий отката.

`downgrade` не всегда безопасен: удалённые/преобразованные данные не
возвращаются автоматически. Часто application rollback требует schema,
совместимой с обеими версиями.

## 9. Backup ≠ успешный `pg_dump`

Backup считается существующим, когда restore проверен.

Нужно определить:

- RPO: сколько данных можно потерять;
- RTO: сколько можно восстанавливать;
- расписание/retention;
- encryption и доступ;
- off-host copy;
- monitoring успешности;
- регулярный restore drill;
- консистентность с secrets/config.

Named volume не backup: потеря VPS/ошибка удаления/коррупция унесёт и
container, и volume.

Перед ценными аккаунтами backups — release blocker из `DEPLOY.md`.

## 10. Smoke, canary и rollback

После deploy автоматизируй минимальный smoke:

- HTTPS certificate/domain;
- `/api/health`;
- providers/config prod (dev login выключен);
- auth redirect/callback безопасным способом;
- catalog;
- создать test match, WS snapshot/ping/update;
- DB migration revision;
- no secret/error spike.

Canary на одном VPS ограничен, но можно иметь staging или manual test account.
Rollback trigger заранее: elevated 5xx, auth failures, migration error,
worker heartbeat stale, reconnect failure.

## 11. Container security и operations

- pinned base image/digest и обновления security patches;
- dependency/scanner alerts;
- read-only filesystem где возможно;
- non-root user;
- resource limits;
- log rotation;
- image provenance/SBOM;
- SSH/firewall updates;
- Postgres не наружу;
- Caddy/API body limits и rate limits.

Текущие Dockerfiles — минимальный MVP, не финальный hardened baseline.

## Разобранный request path

```text
Browser https://play.example
 → DNS A → VPS
 → TCP 443/TLS at Caddy
 → Caddy handle /api/*
 → Compose DNS api:8000
 → uvicorn/FastAPI
 → psycopg connection to postgres:5432
 → volume-backed data
 → response reverse path
```

Для WS Caddy сохраняет Upgrade. Certificates живут в `caddy-data`; frontend
files — внутри immutable image; DB — volume.

## PRIMM

### Predict

Что переживёт:

1. restart API container;
2. recreate Postgres container;
3. удалить `postgres-data` volume;
4. rebuild frontend с новым runtime-only DOMAIN;
5. rollback app после destructive migration?

### Run

Без production secrets прочитай:

```powershell
docker compose -f deploy/docker-compose.prod.yml config
```

Только если локально есть безопасная env-копия; иначе сделай статическую
трассировку. Не выводи реальные secrets в журнал/ответ.

### Investigate

Для каждого `COPY`, volume, port и env в Dockerfile/Compose ответь:
build-time или runtime, public или internal, persistent или disposable.

### Modify

В отдельном toy Dockerfile переставь dependency/source COPY и сравни cache
при изменении одного source файла. Не меняй production Dockerfile ради
упражнения.

### Make

Напиши runbook первого deploy и rollback:

- prerequisites/DNS;
- secret creation;
- backup;
- build/migration;
- smoke;
- observability;
- rollback;
- restore;
- owner/contact.

Сверь с `docs/DEPLOY.md` и явно заполни его пробелы.

## Самопроверка

1. Image против container?
2. Зачем named volume Postgres?
3. Что даёт multi-stage?
4. Почему Compose health не решает runtime outage?
5. Почему несколько uvicorn workers сейчас ломают realtime?
6. Build-time `VITE_*` против runtime env?
7. Почему downgrade не равен rollback?
8. Когда backup доказан?

<details>
<summary>Ответы</summary>

1. Immutable шаблон layers; running process + writable layer/runtime config.
2. Отделяет durable data от disposable container.
3. Final image содержит runtime artifacts без build toolchain.
4. Упорядочивает старт; dependency может упасть позже.
5. In-memory sockets/channels/worker state не разделяются между процессами.
6. Встраивается в публичный JS при build; runtime env процесса его не меняет.
7. Data loss/новые writes и несовместимость могут быть необратимы.
8. После успешного monitored restore drill в целевое RPO/RTO.

</details>

## Мастерство

На чистой локальной/staging среде (не production) проведи build → migrate →
smoke → backup → restore → rollback rehearsal и сохрани runbook с
наблюдениями. Зачёт: данные после restore проверены, secrets не утекли,
rollback учитывает schema.

- **+1:** request path и storage.
- **+3:** deploy ordering.
- **+7:** backup/restore plan.
- **+14:** incident-style rollback tabletop.

Углубление:
[Docker Get Started](https://docs.docker.com/get-started/),
[Compose](https://docs.docker.com/compose/),
[Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[PostgreSQL backup](https://www.postgresql.org/docs/current/backup.html),
[GitHub Actions](https://docs.github.com/actions).
