# Глава 11. Аутентификация и web security

## Результат

Безопасность начинается с доверительных границ и активов, а не с библиотеки.
Аутентификация отвечает «кто ты», авторизация — «можно ли тебе это действие»,
session — «как мы связываем запросы с подтверждённой identity».

После главы ты сможешь:

- построить threat model конкретного flow;
- объяснить cookie-session и хранение hash токена;
- провести OAuth 2.0 Authorization Code + OIDC;
- различать CSRF, XSS, IDOR, brute force и injection;
- проверять auth/authz на каждом HTTP и WS входе;
- безопасно работать с секретами, логами и rate limit.

## Входной threat model

Активы VladStone:

- аккаунт и collection;
- refresh session;
- скрытая рука/порядок deck;
- match ownership и награды;
- Google client secret;
- production DB.

Для каждого назови: кто атакующий, откуда входит, что пытается получить,
какая server-side проверка должна стоять последней.

## 1. Authentication, authorization, session

```text
credentials / OAuth proof
       ↓ authentication
     user identity
       ↓ session issuance
opaque refresh token in browser cookie
       ↓ hash lookup in DB on request
       ↓ authorization
resource + action + owner/role/context
```

Успешный login не разрешает читать любой match. `_get_authorized_record`
сравнивает `owner_user_id` с текущим user. WS повторяет ту же проверку до
accept. Иначе возник бы IDOR: подобрать match id и получить чужое состояние.

## 2. Opaque session token

Надёжный session token:

- генерируется криптографическим CSPRNG;
- имеет достаточно entropy;
- хранится у клиента как opaque secret;
- в БД хранится hash, а не исходный bearer secret;
- имеет expiry, revoke и rotation policy;
- не попадает в URL/log/telemetry.

Bearer означает: кто предъявил секрет, тот получает права. Hash в БД уменьшает
ущерб утечки таблицы, но не спасает token, уже украденный у браузера.

Cookie flags:

- `HttpOnly` — JS не читает token, уменьшает прямую кражу при XSS;
- `Secure` — браузер отправляет только по HTTPS;
- `SameSite` — ограничивает cross-site context;
- узкие `Path`/`Domain` — уменьшают область.

HttpOnly не лечит XSS полностью: вредный script может делать запросы от имени
пользователя, даже не видя token.

## 3. OAuth 2.0 и OpenID Connect

OAuth — delegated authorization framework. OIDC добавляет identity поверх
OAuth. Упрощённый server-side code flow:

```text
browser → VladStone /google/login
VladStone → redirect Google authorize + client_id + redirect_uri + state
user authenticates/consents at Google
Google → callback?code=...&state=...
VladStone checks state
VladStone backend exchanges one-time code for tokens
VladStone validates ID token
VladStone maps (issuer, sub) to local identity
VladStone creates local refresh session
VladStone → redirect frontend
```

`state` связывает callback с начатым браузером flow и защищает от login CSRF.
Для public clients особенно нужен PKCE; confidential backend также выигрывает
от современных рекомендаций, но client secret хранится только server-side.

### Проверка ID token

Нельзя просто декодировать JWT payload. Сервер проверяет:

- криптографическую подпись по доверенным Google keys;
- `iss`;
- `aud` = наш client id;
- `exp`/время;
- при необходимости nonce/`azp`;
- использует стабильный `sub` как provider identity, не email как вечный ключ.

`ARCHITECTURE.md §8.21` отмечает, что полноценная криптографическая проверка
текущего Google ID token — release blocker. Это учебный пример незакрытой
границы, не образец для копирования.

## 4. CSRF и CORS — разные вещи

При cookie auth браузер автоматически прикладывает cookie. Атакующий сайт
может заставить браузер жертвы отправить state-changing request. Это CSRF.

Защиты:

- SameSite с подходящей политикой;
- CSRF token/double-submit для нужных cross-site сценариев;
- проверка Origin/Referer как дополнительный слой;
- state-changing методы не GET;
- reauthentication для критичных действий.

CORS определяет, может ли script прочитать response; сам запрос в некоторых
формах всё равно уйдёт. Поэтому CORS ≠ CSRF defense.

## 5. XSS

XSS — выполнение недоверенного script в origin приложения. Источники:
неэкранированный HTML, опасный `innerHTML`, URL/script contexts, supply chain.

Защиты:

- React escaping по умолчанию; не обходить без sanitization;
- Content Security Policy;
- не хранить bearer token в JS-доступном storage без необходимости;
- output encoding по контексту;
- dependency hygiene.

Backend обязан возвращать данные, но не считать frontend «санитайзером всех
смыслов». Логи/админка тоже output contexts.

## 6. Brute force и rate limiting

Email code с малым пространством можно перебирать. Нужны:

- короткий expiry и one-time consumption;
- hash кода;
- лимит попыток на code/session/email;
- rate limit запроса кода по IP и identity;
- generic responses против enumeration;
- audit/metrics.

Rate limit key только по IP наказывает NAT и обходится ботнетом; только по
email позволяет атаковать жертву распределённо. Обычно нужен layered key и
policy. In-memory limiter одного процесса теряет state при restart и не
координирует instances.

## 7. Validation и anti-cheat

Клиент полностью недоверен. Для placement сервер проверяет минимум:

- authenticated/authorized actor;
- match/turn/phase;
- card instance действительно в руке;
- mana;
- legal spawn/target;
- карта не использована дважды;
- ruleset/current state.

Payload наружу viewer-specific: чужая hand пустая, есть только `hand_count`;
deck никогда не сериализуется, только `deck_count`. «UI не показывает» не
защита: атакующий вызывает API напрямую.

## 8. Injection, secrets и logs

SQLAlchemy bound parameters защищают значения от SQL injection, если не
строить raw SQL конкатенацией. Но injection бывает command/template/path.
Валидируй структуру и используй API безопасного уровня.

Секреты:

- environment/secret store, не Git;
- rotation/revocation;
- минимальные права;
- не печатать целиком token/JWT/code;
- `.env` локален и игнорируется.

Structured log должен помогать расследовать без персональных/секретных данных:
event, request/match/user internal id, result, latency, error class. Email и
IP — персональные данные с retention/access policy.

## Разобранный пример: match authorization

Порядок в HTTP:

1. lookup record;
2. `404`, если нет;
3. resolve refresh token → user;
4. если owner задан и user отсутствует/другой → `403`;
5. только затем state parsing/return.

Почему не вернуть `403` на всё: иногда это уменьшает enumeration, но текущий
контракт различает. В security review нужно сознательно решить, что раскрывает
существование id. Главное — никогда не отдать body до authz.

WS выполняет проверку до `accept`; policy violation закрывает handshake. Auth
на HTTP route не переносится автоматически на другой WS endpoint.

## PRIMM

### Predict

Для каждой атаки выбери контроль: stolen DB of token hashes, malicious site
POST, script in page, guessed match id, email code brute force, forged ID
token.

### Run

В DevTools локального входа исследуй `Set-Cookie` и subsequent request. Не
копируй token в заметки. Сравни host `127.0.0.1` и `localhost` только на
локальной среде.

### Investigate

Нарисуй Google flow по `routes/auth.py` и `services/google_oauth.py`. На каждой
стрелке: attacker control, проверка, секрет, log policy. Сверь с
`ARCHITECTURE §8.8–8.10, §8.20–8.21`.

### Modify

В мини-примере напиши pure function `authorize_match(record_owner, user_id)`
и таблицу тестов: public match, owner, anonymous, other user. Затем добавь
состояние deleted/expired и реши порядок authz vs lifecycle error.

### Make

Составь threat model email verify:

- assets/actors/entry points;
- пять abuse cases;
- layered rate limits;
- atomic attempt counter/consume;
- generic error contract;
- metrics/alerts;
- тесты гонки.

Реализация release blocker — отдельная production-задача, не делай её внутри
учебного упражнения без полного scope/review.

## Самопроверка

1. Authn против authz?
2. Зачем hash opaque token в DB?
3. Что защищает OAuth `state`?
4. Какие claims/свойства ID token надо проверить?
5. Почему HttpOnly не лечит XSS полностью?
6. Почему CORS не CSRF defense?
7. Почему rate limit только по IP слаб?
8. Какие секреты battle payload нельзя отдавать?

<details>
<summary>Ответы</summary>

1. Установить identity; разрешить конкретное действие над ресурсом.
2. Утечка DB не даёт готовые bearer tokens, хотя активную кражу клиента не
   решает.
3. Связывает callback с инициированным flow/браузером и мешает login CSRF.
4. Signature trusted key, issuer, audience, expiry и flow-specific
   nonce/authorized party; identity по sub.
5. Script может отправлять same-origin actions с автоматически приложенной
   cookie.
6. CORS про чтение response браузерным script, а CSRF — про нежелательный
   state-changing request с cookie.
7. NAT/shared users, botnet/proxy bypass и нет identity dimension.
8. Порядок deck всегда; hand только владельцу; user/internal ownership data по
   необходимости и viewer-safe contract.

</details>

## Мастерство

Проведи 45-минутный threat-model review одного flow: diagram, активы, trust
boundaries, abuse cases, controls, residual risk и tests. Зачёт: контроль
находится server-side и привязан к конкретной атаке, а не «добавить JWT».

- **+1:** authn/authz/session.
- **+3:** OAuth flow без подсказки.
- **+7:** CSRF/XSS/IDOR cases.
- **+14:** новый threat model.

Углубление:
[OWASP Top 10](https://owasp.org/www-project-top-ten/),
[OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[OAuth 2.0 Security BCP RFC 9700](https://www.rfc-editor.org/rfc/rfc9700),
[OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html),
[Google ID token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).
