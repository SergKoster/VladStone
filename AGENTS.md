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
| [docs/PVP_INVITE_PLAN.md](docs/PVP_INVITE_PLAN.md) | Подробный план PvP-invite: lobby, auth, multi-human resolve, viewer-safe WS, reconnect | Перед работой над Фазой 4 / матчем с другом |
| [docs/UX_DETAILS.md](docs/UX_DETAILS.md) | Копилка UX-идей и «приколюх» (микро-взаимодействия, анимации) | Перед работой над UI-полировкой |
| [TODO.md](TODO.md) | Живой краткосрочный бэклог и найденные баги | Всегда актуален для мелких задач |

**Текущий фокус (3 августа 2026): Фаза 4 — PvP invite и внешний матч с
другом.** Боёвка v4, 12 стартовых карт, API/таймер/WS, `BattleV4`, покадровый
replay, интент-стриминг и release blockers первого внешнего деплоя уже закрыты.
Баланс O10, расширение контента и оставшаяся UI-полировка отложены владельцем
до реального PvP-плейтеста. Следующий этап выполняется по
[PVP_INVITE_PLAN.md](docs/PVP_INVITE_PLAN.md): lobby и токен-ссылка → второй
авторизованный участник → multi-human resolve → viewer-safe HTTP/WS → reconnect
и тест на двух устройствах. После внешнего матча фидбек записать в
[PLAYTEST_NOTES.md](docs/PLAYTEST_NOTES.md) и вернуться к O10.

**Формат финала Codex:** заканчивай каждое сообщение двумя короткими пунктами:
«Следующее» (конкретный следующий этап) и «Тебе проверить» (ручная проверка,
если она нужна; иначе прямо «ничего»).

**Правило поддержки:** при изменении игровых правил — обнови DESIGN.md; при изменении структуры кода/API/моделей — обнови ARCHITECTURE.md. Не дублируй числа из кода в доки (стоимости карт, тайминги) — ссылайся на файл-источник.

**Правило коммитов:** любые внесённые изменения (код и доки) всегда коммить по завершении работы — не оставляй рабочее дерево грязным. Осмысленное сообщение в стиле истории репо (`feat(combat): ...`, `docs: ...`, `fix(battle): ...`).

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
- Скорость анимаций фиксирована (тайминги — `VladStoneWeb/src/features/battle/animationConfig.ts`; `Battle.tsx` и `ANIMATION_SPEED` удалены вместе с MVP); переключателя в UI нет — бой рассчитан на онлайн.
- Колода — серверный секрет: `PlayerState.deck` наружу не сериализуется никогда (только `deck_count`), рука уходит только своему владельцу (`viewer_id` в ответе).
