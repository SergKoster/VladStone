import React from "react";

import { t } from "../../i18n";

export function AuthScreen({
  authMessage,
  code,
  devCode,
  email,
  onCodeChange,
  onEmailChange,
  onGoogleLogin,
  onRequestCode,
  onVerifyCode,
}: {
  authMessage: string;
  code: string;
  devCode: string | null;
  email: string;
  onCodeChange: (code: string) => void;
  onEmailChange: (email: string) => void;
  onGoogleLogin: () => void;
  onRequestCode: () => void;
  onVerifyCode: () => void;
}) {
  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <p className="brand">{t.appName}</p>
        <h1>{t.loginTitle}</h1>
        <div className="login-row">
          <input
            aria-label="Email"
            value={email}
            onChange={(event) => onEmailChange(event.target.value)}
            placeholder={t.emailPlaceholder}
            type="email"
          />
          <button onClick={onRequestCode}>{t.sendCode}</button>
        </div>
        {devCode && (
          <div className="code-row">
            <input
              aria-label="Код"
              value={code}
              onChange={(event) => onCodeChange(event.target.value)}
              placeholder={devCode}
            />
            <button onClick={onVerifyCode}>Войти</button>
          </div>
        )}
        {authMessage && <p className="muted">{authMessage}</p>}
        <button className="secondary" onClick={onGoogleLogin}>
          {t.googleLogin}
        </button>
      </section>
    </main>
  );
}
