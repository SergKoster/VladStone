# Модуль 4. Realtime: WebSockets и таймеры

> Наш бой — realtime: сервер сам двигает матчи по дедлайнам и рассылает
> обновления. Цель — понимать протокол WebSocket и всю нашу realtime-цепочку.

## Что нужно знать на выходе

- Протокол WebSocket: handshake через HTTP Upgrade, фреймы, ping/pong, чем
  отличается от HTTP-поллинга и Server-Sent Events.
- Модель «канал на матч»: подписка сокетов, broadcast, снапшот при
  подключении.
- Поллинг как fallback и reconnect: почему клиент обязан переживать разрыв.
- Серверные таймеры: фоновый воркер + «ленивый» дорезолв в роутах как
  подстраховка (два пути к одному результату).
- Ограничения одного инстанса и зачем в будущем Redis pub/sub
  (ARCHITECTURE §2.4).

## Ресурсы

1. [MDN: WebSockets API](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API) —
   клиентская сторона, база.
2. [High Performance Browser Networking, глава WebSocket](https://hpbn.co/websocket/) —
   бесплатная книга Ильи Григорика; как протокол работает на уровне сети.
3. [FastAPI: WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) —
   серверная сторона на нашем фреймворке.
4. [Паттерны realtime-архитектуры](https://codelit.io/blog/websocket-real-time-architecture-patterns) —
   обзор: чат, игры, live-данные.

## Где это у нас

- `VladStoneAPI/app/realtime/match_channels.py` — in-process менеджер каналов:
  прочитать целиком, он небольшой.
- `VladStoneAPI/app/api/routes/ws.py` — WS-эндпоинт `/ws/matches/{id}`:
  снапшот при подключении, авторизация, ping/pong.
- `VladStoneAPI/app/services/combat_timer_worker.py` и
  `services/combat_turn_timers.py` — дорезолв по дедлайну и broadcast.
- `VladStoneWeb/src/features/battle/matchRealtime.ts` — клиентская сторона:
  подключение, статусы, polling-fallback (8 с).
- Resolution-envelope и дедупликация по `(match_id, resolved_turn,
  last_sequence)` — ARCHITECTURE §5.2 («Reliability резолва»).

## Практика

1. Запустить бой и посмотреть WS-трафик в DevTools (вкладка Network → WS):
   найти снапшот при подключении, `match.updated`, ping/pong.
2. Убить WS руками (офлайн в DevTools) посреди матча — убедиться, что поллинг
   подхватывает, а после восстановления связи состояние догоняется. Объяснить
   по коду, как именно.
3. Трассировка «AFK-игрока»: не нажимать «Готов» и по коду проследить, кто и
   когда дорезолвит ход (воркер? ленивый путь?), и как результат доезжает до
   клиента.
4. Прочитать риски §8.19 (broadcast без backpressure) и §8.14 (совпадение
   дедлайнов) в ARCHITECTURE и пересказать своими словами: что сломается под
   нагрузкой и какой план фикса.

## Вопросы для самопроверки

- Почему WebSocket начинается с HTTP-запроса? Что такое Upgrade?
- Что случится с матчем, если упадёт таймер-воркер? А если клиент закроет
  вкладку на 5 минут и вернётся?
- Почему события резолва нельзя просто «отправить и забыть» — зачем envelope
  хранится в состоянии матча до следующего резолва?
- Чем наш пошаговый realtime проще (и дешевле), чем realtime в экшен-играх
  с клиентским предсказанием?
