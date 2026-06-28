# Google OAuth Setup

Для настоящего входа через Google нужен Google Cloud проект.

## Что создать

1. Google Cloud Project.
2. OAuth consent screen.
3. OAuth Client ID типа Web application.

## Redirect URI для локальной разработки

Пока backend Google-flow не подключен к реальному OAuth callback, держим dev endpoint:

- `POST /api/auth/google/dev-login`

Когда будем подключать настоящий callback, локальный redirect URI будет примерно таким:

- `http://localhost:8001/api/auth/google/callback`

## Env-переменные

Добавить в `VladStoneAPI/.env`:

```env
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
```

## Важное

- До публичного запуска можно держать consent screen в testing-режиме.
- Тестовые Google-аккаунты нужно добавить в список test users.
- Google login должен быть полноценным способом входа, а не только привязкой к email-входу.
