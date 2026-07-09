# VladStone

Браузерная карточная MMO-игра. Web-first (играбельно с любого устройства), позже desktop/mobile без переписывания backend.

## Документы проекта — читать перед работой

| Файл | Что там | Когда читать |
|------|---------|--------------|
| [docs/DESIGN.md](docs/DESIGN.md) | Дизайн-документ: геймплей, карты, экономика, релизный скоуп | Перед любой работой над геймплеем, балансом, UI игры |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Архитектура: модули, потоки данных, инварианты, realtime | Перед изменением структуры кода, API, моделей данных |
| [docs/ROADMAP.md](docs/ROADMAP.md) | План по фазам с зависимостями | При выборе следующей задачи, оценке скоупа |
| [docs/DESIGN_QUESTIONS.md](docs/DESIGN_QUESTIONS.md) | Архив дизайн-решений владельца (ответы на опросники) | При сомнении в трактовке пункта DESIGN.md |
| [docs/PLAYTEST_NOTES.md](docs/PLAYTEST_NOTES.md) | Журнал фидбека плейтестов (сырьё для O7 — правок правил боя) | Перед любыми правками правил/ощущения боя |
| [docs/COMBAT_REWORK.md](docs/COMBAT_REWORK.md) | **Дизайн боёвки v4** (стойки, 5 башен, фазы, движок, blindspot) + §20 последовательность реализации | Перед любой работой над боем — это актуальный канон боёвки |
| [docs/UX_DETAILS.md](docs/UX_DETAILS.md) | Копилка UX-идей и «приколюх» (микро-взаимодействия, анимации) | Перед работой над UI-полировкой |
| [TODO.md](TODO.md) | Живой краткосрочный бэклог и найденные баги | Всегда актуален для мелких задач |

**Текущий фокус (июль 2026):** боёвка v4 — **КАНОН** (DESIGN §3); идёт реализация —
последовательность в [COMBAT_REWORK.md](docs/COMBAT_REWORK.md) §20. **P0 закрыт;
C1–C5 и S1–S3 решены владельцем** (§19); **`RULESET_VERSION`-гейт сделан**
(ARCH §8.7). Следующее — §20 P1.7: модель участников (R12), затем P2 движок v4.

**Правило поддержки:** при изменении игровых правил — обнови DESIGN.md; при изменении структуры кода/API/моделей — обнови ARCHITECTURE.md. Не дублируй числа из кода в доки (стоимости карт, тайминги) — ссылайся на файл-источник.

**По дизайну игры ничего не решать без владельца.** Открытые вопросы — в DESIGN_QUESTIONS.md.

## Незыблемые принципы

- Сервер — авторитетный источник правды: бой, коллекция, экономика, награды, прогресс.
- Клиент отправляет намерения игрока, а не готовое состояние.
- Анимации строятся по серверным combat events, а не угадываются фронтом.
- Realtime, таймеры и reconnect закладываются до PvP, а не после.
- Без лутбоксов: получение карт детерминированное или через явные награды/ивенты.
- Боевые правила развиваются отдельно от UI, auth, коллекции и экономики.

## Структура репо

- `VladStoneAPI/` — FastAPI backend. Домен боя: `app/domain/combat/` (resolver, planning, attacks, movement, collisions, deck, bot, cards...). Роуты: `app/api/routes/`. Realtime: `app/realtime/match_channels.py`.
- `VladStoneWeb/` — React/Vite/TS frontend. Фичи: `src/features/{battle,collection,dashboard,profile,auth}/`. Общее: `src/shared/` (Card, cardArt, icons, apiClient).
- `res/Cards/` — исходники артов. Рабочая копия: положить `<card_id>.png/jpg` в `VladStoneWeb/src/assets/cards/` и прогнать `VladStoneAPI\.venv\Scripts\python tools\compress_card_art.py` — получится сжатый `<card_id>.webp` (фронт подхватывает автоматически).
- `docs/` — документация проекта.

## Команды

Backend (из `VladStoneAPI/`):
```
.\.venv\Scripts\python -m pytest          # тесты
.\.venv\Scripts\python -m ruff check .    # линтер
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8001
```

Frontend (из `VladStoneWeb/`):
```
npm run build    # tsc + vite build — обязательная проверка
npm run dev      # dev-сервер на 5173
```

Полный dev-запуск: `start-dev.bat` из корня. CI: `.github/workflows/ci.yml` (pytest+ruff, npm build).

## Dev-нюансы

- API на `127.0.0.1:8001`, web на `5173`. **Куки авторизации привязаны к хосту**: открывай фронт и API на одном хосте (`127.0.0.1`, не `localhost`), иначе `/me/*` вернёт 401.
- Вход в dev: кнопка «Войти через Google» (dev-login, без реального OAuth).
- Скорость анимаций фиксирована (`ANIMATION_SPEED` в Battle.tsx); переключателя в UI нет — бой рассчитан на онлайн.
- Порядок колоды — серверный секрет: API отдаёт только `deck_count`, поле `player_deck` наружу не сериализуется.
