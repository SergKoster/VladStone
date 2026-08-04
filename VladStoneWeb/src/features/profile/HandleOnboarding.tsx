import React from "react";

export function HandleOnboarding({
  onSubmit,
}: {
  onSubmit: (handle: string) => Promise<void>;
}) {
  const [handle, setHandle] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const valid = /^[A-Za-z0-9_]{3,25}$/.test(handle);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setMessage("");
    try {
      await onSubmit(handle);
    } catch {
      setMessage("Ник уже занят или недоступен.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="auth-panel handle-onboarding" onSubmit={submit}>
        <p className="brand">VladStone</p>
        <h1>Выбери ник</h1>
        <p className="muted">3–25 символов: латинские буквы, цифры и _</p>
        <input
          aria-label="Ник"
          autoComplete="username"
          autoFocus
          maxLength={25}
          onChange={(event) => setHandle(event.target.value)}
          placeholder="Player_name"
          value={handle}
        />
        <button disabled={!valid || busy} type="submit">
          {busy ? "Сохраняем…" : "Продолжить"}
        </button>
        {message ? <p className="form-error">{message}</p> : null}
      </form>
    </main>
  );
}
