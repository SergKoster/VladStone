# Google OAuth Setup

Для настоящего входа через Google нужен Google Cloud проект.

## Что создать

1. Google Cloud Project.
2. OAuth consent screen.
3. OAuth Client ID типа Web application.

## Redirect URI

Реальный flow реализован (июль 2026): `GET /api/auth/google/login` →
Google → `GET /api/auth/google/callback` → refresh-cookie → редирект на фронт.
Dev endpoint `POST /api/auth/google/dev-login` остаётся для локальной
разработки (работает только при `ENVIRONMENT=local`).

В Google Cloud Console в Authorized redirect URIs добавить:

- локально: `http://127.0.0.1:8001/api/auth/google/callback`
- прод: `https://<домен>/api/auth/google/callback`

## Env-переменные

Добавить в `VladStoneAPI/.env` (пока кредов нет, кнопка Google на фронте
работает как dev-login; фронт узнаёт о включённом Google из
`GET /api/auth/providers`):

```env
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8001/api/auth/google/callback
FRONTEND_URL=http://127.0.0.1:5173
```

## Важное

- До публичного запуска можно держать consent screen в testing-режиме.
- Тестовые Google-аккаунты нужно добавить в список test users.
- Google login должен быть полноценным способом входа, а не только привязкой к email-входу.
