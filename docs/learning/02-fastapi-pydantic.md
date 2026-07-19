# Модуль 2. FastAPI и Pydantic

> Каркас нашего API. Цель — понимать путь запроса от браузера до ответа:
> роутинг, валидация, зависимости, сериализация, lifespan.

## Что нужно знать на выходе

- Что такое ASGI и uvicorn; чем ASGI отличается от WSGI (и почему FastAPI
  умеет WebSockets, а классический Flask — нет).
- Роуты, path/query/body-параметры, коды ответов, `HTTPException`.
- Pydantic v2: модели запроса/ответа, валидация, `model_dump`, настройки через
  `pydantic-settings` (наш `core/config.py`).
- Dependency Injection (`Depends`): как роуты получают сессию БД и текущего
  пользователя, и почему это лучше глобальных переменных.
- Lifespan: код при старте/остановке приложения (у нас там запускается
  таймер-воркер).
- Автодокументация OpenAPI (`/docs`) — как читать и использовать.

## Ресурсы

1. [Официальный туториал FastAPI](https://fastapi.tiangolo.com/learn/) —
   **главный ресурс модуля**, написан как книга, проходить по порядку.
   Затем выборочно [Advanced User Guide](https://fastapi.tiangolo.com/advanced/).
2. [Документация Pydantic v2](https://docs.pydantic.dev/latest/) — разделы
   Models, Validators, Settings.
3. [Udemy: FastAPI — The Complete Course](https://www.udemy.com/course/fastapi-the-complete-course/) —
   опционально, если хочется вести за руку: от нуля до деплоя с auth и БД.
4. [Уроки FastAPI на YouTube](https://www.youtube.com/watch?v=tMJA41xhBZM) —
   альтернативный формат, если книга «не заходит».

## Где это у нас

- `VladStoneAPI/app/main.py` — сборка приложения: роутеры, CORS, lifespan.
- `VladStoneAPI/app/api/routes/combat.py` — самый насыщенный роутер:
  body-модели, зависимости, 409-ответы, viewer-специфичная сериализация.
- `VladStoneAPI/app/core/config.py` — pydantic-settings: конфиг из env.
- `VladStoneAPI/app/api/routes/health.py` — простейший роут для старта.
- Запусти сервер и открой `http://127.0.0.1:8001/docs` — вся схема API.

## Практика

1. Трассировка: пройти путь `POST /combat/start` от роута до записи в БД —
   выписать цепочку файлов/функций. Потом сверить с ARCHITECTURE §2.2.
2. В песочной ветке добавить тестовый роут `GET /debug/echo`, принимающий
   Pydantic-модель с валидацией (например, поле 1–100), и посмотреть в `/docs`,
   как валидация отражается в схеме и что возвращает 422.
3. Найти все `Depends` в `routes/` и объяснить, что даёт каждый.
4. Ответить по коду: где именно рождается `viewer_id` в ответе матча и почему
   рука соперника не утекает (инвариант анти-чита).

## Вопросы для самопроверки

- Что произойдёт, если в body придёт лишнее/неверное поле? Кто это отклоняет?
- Зачем `lifespan`, если можно запустить воркер «просто при импорте»?
- Почему конфиг читается через pydantic-settings, а не `os.environ` напрямую?
- Как FastAPI понимает, что параметр роута — это query, а что — body?
