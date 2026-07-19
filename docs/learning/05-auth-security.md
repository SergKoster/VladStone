# Модуль 5. Аутентификация и безопасность

> У нас реальный Google OAuth, куки-сессии и целый список security-долгов в
> ARCHITECTURE §8 — идеальный учебный полигон. Цель — понимать, как устроен
> вход в приложение и от чего надо защищаться перед публичным деплоем.

## Что нужно знать на выходе

- Сессии vs токены: refresh-cookie (наш путь) против bearer access token;
  атрибуты кук (`HttpOnly`, `Secure`, `SameSite`) и почему куки привязаны к
  хосту (наша dev-боль `127.0.0.1` vs `localhost`).
- OAuth 2.0 / OpenID Connect: authorization code flow, `state` против CSRF,
  ID token (JWT) и его **обязательная** валидация (подпись, `aud`, `iss`,
  `exp`) — см. наш риск §8.21.
- Классические атаки: CSRF, XSS, брутфорс кодов, перебор id (IDOR), DoS
  большими телами запросов; rate limiting.
- Принцип «валидируй на сервере всё»: клиент — недоверенная среда (у нас это
  же и анти-чит: рука/колода — серверные секреты).

## Ресурсы

1. [roadmap.sh: раздел Authentication](https://roadmap.sh/backend) — обзорная
   карта тем.
2. [OAuth 2.0 Simplified](https://www.oauth.com/) — бесплатная книга; читать
   про authorization code flow.
3. [Google: Verify ID token](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token) —
   официальная инструкция, прямо относится к нашему риску §8.21.
4. [OWASP Top 10](https://owasp.org/www-project-top-ten/) — минимальный
   словарь угроз веб-приложения.
5. [MDN: HTTP cookies](https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies) —
   атрибуты кук и их смысл.

## Где это у нас

- `VladStoneAPI/app/api/routes/auth.py` — email-код (dev), Google OAuth
  (login/callback), refresh-cookie, logout, `/providers`.
- `VladStoneAPI/app/services/google_oauth.py` — обмен кода на токен; здесь же
  живёт известная дыра (JWT не проверяется криптографически — §8.21).
- `VladStoneAPI/app/services/auth.py` — коды, sessions, audit log.
- `VladStoneAPI/app/core/config.py` — `cookie_secure`, `environment` и то, как
  прод-режим гасит dev-логин.
- Анти-чит сериализация: `app/domain/combat/engine/payload.py` (`viewer_id`,
  `deck_count`, рука только владельцу).

## Практика

1. Пройти вход через dev-login с открытым DevTools: увидеть Set-Cookie,
   атрибуты куки, последующие запросы с ней. Потом объяснить, почему фронт на
   `localhost` при API на `127.0.0.1` получает 401.
2. Нарисовать (на бумаге/в тексте) полную схему Google OAuth flow по нашему
   коду: браузер → `/google/login` → Google → `/google/callback` → фронт.
   Отметить, где `state` и зачем.
3. Разобрать security-долги §8.8–8.10, §8.20–8.21 из ARCHITECTURE: для
   каждого сформулировать атаку «как злоумышленник это использует».
4. (Боевая задача, по готовности) Закрыть §8.8 — rate limit + счётчик попыток
   на verify email-кода. Это реальный release blocker, отличный выпускной
   проект модуля.

## Вопросы для самопроверки

- Почему refresh-токен в `HttpOnly`-куке безопаснее, чем в localStorage?
- Что именно защищает `state` в OAuth flow? Опиши атаку без него.
- Почему «мы получили токен по TLS от Google» — недостаточная причина не
  проверять подпись ID token?
- Какие три вещи обязан проверить сервер прежде, чем принять placement карты
  от клиента?
