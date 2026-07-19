# Глава 6. Сети, HTTP и проектирование API

## Результат

HTTP-фреймворк легче понять, если сначала видеть протокол. API — публичное
обещание между независимо меняющимися сторонами, а не набор Python-функций.

После главы ты сможешь:

- провести запрос через DNS → TCP → TLS → HTTP → приложение;
- объяснить method, target, headers, body, status и caching;
- правильно использовать 2xx/4xx/5xx и идемпотентность;
- проектировать ресурс, команду, error contract и эволюцию схемы;
- объяснить cookie, same-origin, CORS и WebSocket Upgrade.

## Входной прогноз

Клиент дважды отправил:

```http
POST /api/combat/ready
Cookie: refresh_token=...
Content-Type: application/json

{"match_id":"m1","turn":7,"ready":true,"placements":[],"spells":[]}
```

Первый ответ потерялся. Что должен делать retry? Может ли сервер безопасно
считать второй запрос «ещё одним нажатием»? Какие поля позволяют распознать
устаревшее намерение?

## 1. Путь запроса

```text
URL
 → DNS: имя → IP
 → TCP: надёжный упорядоченный byte stream
 → TLS: аутентификация сервера + шифрование (HTTPS)
 → HTTP: request/response semantics
 → reverse proxy
 → ASGI server
 → FastAPI route/service/domain/DB
```

В локальной разработке TLS/reverse proxy обычно отсутствуют, но hostname всё
равно влияет на origin и cookie. В production Caddy завершает TLS и
проксирует `/api` и `/ws` в uvicorn.

TCP не знает JSON и status code. HTTP не знает PlayerIntents. Каждый слой
добавляет свой контракт.

## 2. HTTP message

Запрос имеет method, target, headers и иногда body. Ответ — status, headers и
body.

```http
GET /api/combat/catalog HTTP/1.1
Host: game.example
Accept: application/json
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: ...

{"cards":[...],"statuses":[...]}
```

Method сообщает семантику:

- `GET` — безопасное чтение: не должен менять бизнес-состояние;
- `POST` — обработка команды/создание, по умолчанию не считается
  идемпотентным протоколом;
- `PUT` — заменить представление по известному URI, идемпотентно;
- `PATCH` — частичное изменение;
- `DELETE` — удалить/деактивировать, повтор должен иметь совместимую семантику.

Идемпотентность: повтор одного и того же намерения имеет тот же итоговый
эффект, не обязательно тот же байтовый ответ.

## 3. Status code — часть API

Группы:

- `2xx` — запрос принят и обработан;
- `4xx` — запрос в текущем контексте нельзя выполнить;
- `5xx` — сервер не выполнил корректный запрос из-за своего сбоя.

VladStone использует:

- `404` — match id не существует;
- `403` — матч существует, но принадлежит другому пользователю;
- `409` — ресурс есть, но версия/фаза/дедлайн конфликтует с намерением;
- `422` — JSON не соответствует Pydantic schema.

Не превращай любой доменный отказ в `500`: это ломает retry, мониторинг и
ожидания клиента. Не отвечай `200 {"ok": false}` на протокольную ошибку:
инфраструктура увидит успех.

## 4. Ресурс, команда и состояние

REST-подобный resource API хорош для CRUD:

```text
GET /matches/{id}
GET /players/{id}/deck
PUT /players/{id}/deck
```

Доменная команда часто яснее искусственного CRUD:

```text
POST /combat/ready
POST /auth/logout
```

Главное — явная семантика, авторизация и retry contract. `ready` не должен
принимать готовое состояние матча: клиент отправляет intent, сервер проверяет
turn, owner, hand, mana и phase.

### Optimistic concurrency в контракте

Поле `turn` — версия намерения на уровне домена. Если сервер уже на восьмом
ходе, план для седьмого отклоняется `409`; иначе опоздавший пакет мог бы
примениться к новому состоянию.

Для общего API часто используют version/ETag:

```http
If-Match: "version-12"
```

При несовпадении — `412 Precondition Failed` или согласованный `409`.

## 5. Error model

Полезная ошибка машинно читаема и безопасна:

```json
{
  "code": "turn_conflict",
  "message": "Combat turn is no longer current",
  "request_id": "..."
}
```

`code` стабилен для клиента, `message` для человека, `request_id` связывает с
логами. Не отдавай traceback, SQL или секрет. Текущий проект в основном
использует стандартный `{"detail": "..."}` FastAPI — этого хватает MVP, но
публичный API выиграет от стабильных кодов.

## 6. Cookie, origin и CORS

Origin = scheme + host + port:

```text
http://127.0.0.1:5173 ≠ http://localhost:5173
http://127.0.0.1:5173 ≠ http://127.0.0.1:8001
https://game.example   ≠ http://game.example
```

Cookie привязана к правилам domain/path/SameSite/Secure; порт не является
cookie-domain, но origin-политики браузера учитывают порт. `HttpOnly`
запрещает JS читать cookie, `Secure` требует HTTPS, `SameSite` ограничивает
cross-site отправку.

CORS — браузерное разрешение читать cross-origin response, не firewall и не
auth. Небраузерный клиент не обязан соблюдать CORS. Production same-origin
через Caddy уменьшает эту сложность: страница, `/api` и `/ws` имеют один
внешний origin.

## 7. WebSocket начинается HTTP

Клиент отправляет HTTP handshake с Upgrade; после согласия соединение
переходит к двусторонним frames. TLS-вариант `wss` соответствует HTTPS.
Дальше нет обычного status code на каждое сообщение, поэтому application
protocol должен сам определить `type`, payload, error, heartbeat и version.

## Разобранный пример: `/plan` и `/ready`

Оба несут полный актуальный план. `/plan` сохраняет последнее намерение без
резолва. `/ready` атомарно сохраняет финальный план и флаг готовности.

Почему финальный план включён снова:

1. debounce `/plan` мог быть в полёте или потеряться;
2. отдельные «сохрани план» и «готов» допускают гонку;
3. одна команда делает invariant «ready относится именно к этому плану»
   атомарным на уровне request.

Повтор `ready=true` с тем же match/turn/plan должен стремиться к тому же
state. Если ход уже разрешён, `409` говорит клиенту перечитать
server-authoritative snapshot.

## PRIMM

### Predict

К какому status отнести:

1. malformed JSON;
2. `turn=0`;
3. valid turn, но чужой match;
4. дедлайн только что прошёл;
5. неожиданное падение сериализации.

### Run

Запусти API-тесты или используй `/docs` и отправь безопасные запросы к
локальному бою. До каждого запроса запиши status/body.

### Investigate

В `routes/combat.py` проследи `_load_planning_state_or_409`. Составь таблицу:
условие → status → client recovery. Отдельно найди viewer-specific payload.

### Modify

Спроектируй стабильный error code для трёх текущих `409`: ruleset expired,
deadline passed, stale turn. Не внедряй; покажи, как frontend сможет выбрать
recovery без парсинга английского `detail`.

### Make

Спроектируй API deck builder:

- resource/command URI;
- request/response;
- server invariants;
- auth;
- concurrency/version;
- retry/idempotency;
- error codes;
- совместимое добавление нового поля.

Сверь с `ARCHITECTURE.md §5.3`, не придумывая игровых правил.

## Самопроверка

1. Что гарантирует каждый слой DNS/TCP/TLS/HTTP?
2. Чем safe method отличается от idempotent?
3. Почему stale turn — 409, а не 500?
4. Зачем машинный error code отдельно от message?
5. Почему CORS не защищает API от curl?
6. Как `localhost` ломает dev auth при другом hostname?
7. Зачем `/ready` повторяет план?

<details>
<summary>Ответы</summary>

1. Резолв имени; byte stream; защищённый канал/identity; semantics messages.
2. Safe не меняет бизнес-state; idempotent допускает повтор с тем же эффектом.
3. Запрос конфликтует с текущим состоянием ресурса; сервер работает штатно.
4. Клиент ветвится по стабильному значению, текст можно менять/локализовать.
5. CORS исполняет браузер и регулирует чтение response, не сетевой доступ.
6. Cookie и origin определяются hostname; это разные web security contexts.
7. Чтобы plan и ready были одним атомарным намерением, несмотря на
   debounce/потерю предыдущего request.

</details>

## Мастерство

Защити API deck builder перед воображаемым frontend-разработчиком: пять
примеров успеха/ошибки, повтор запроса, конкурентное обновление и совместимая
эволюция. Зачёт — клиенту не надо угадывать состояние или парсить message.

- **+1:** путь запроса и status cases.
- **+3:** cookie/origin/CORS на своих URL.
- **+7:** API contract новой команды.
- **+14:** разобрать неизвестный HTTP trace без FastAPI.

Углубление:
[MDN HTTP](https://developer.mozilla.org/en-US/docs/Web/HTTP),
[HTTP Semantics RFC 9110](https://www.rfc-editor.org/rfc/rfc9110),
[MDN cookies](https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies),
[WebSocket RFC 6455](https://www.rfc-editor.org/rfc/rfc6455).
