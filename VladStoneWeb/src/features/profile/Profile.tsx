import React from "react";

import { type PublicProfileResponse } from "../../api";

export function Profile({
  email,
  onRename,
  profile,
}: {
  email?: string;
  onRename?: (handle: string) => Promise<void>;
  profile: PublicProfileResponse;
}) {
  const [nextHandle, setNextHandle] = React.useState(profile.handle);
  const [message, setMessage] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const createdDate = new Date(profile.created_at).toLocaleDateString("ru-RU");

  async function rename(event: React.FormEvent) {
    event.preventDefault();
    if (!onRename || busy || !/^[A-Za-z0-9_]{3,25}$/.test(nextHandle)) return;
    setBusy(true);
    setMessage("");
    try {
      await onRename(nextHandle);
    } catch {
      setMessage("Не удалось сменить ник: возможно, он уже зарезервирован.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page profile-page">
      <header className="page-header">
        <div className="profile-heading">
          <span aria-hidden="true" className="profile-avatar">
            {profile.avatar_key ?? profile.handle.slice(0, 1).toUpperCase()}
          </span>
          <div>
            <h1>{profile.handle}</h1>
            <p>Публичный профиль игрока</p>
          </div>
        </div>
      </header>
      <section className="metrics">
        <Metric label="Ник" value={profile.handle} />
        <Metric label="Коллекция" value={`${profile.collection.owned} / ${profile.collection.total}`} />
        <Metric label="Создан" value={createdDate} />
      </section>
      {email ? <p className="profile-private-note">Только тебе видно: {email}</p> : null}
      {onRename ? (
        <form className="profile-rename" onSubmit={rename}>
          <label htmlFor="profile-handle">Сменить ник</label>
          <div>
            <input
              id="profile-handle"
              maxLength={25}
              onChange={(event) => setNextHandle(event.target.value)}
              value={nextHandle}
            />
            <button disabled={busy || nextHandle === profile.handle} type="submit">
              Сохранить
            </button>
          </div>
          {message ? <p className="form-error">{message}</p> : null}
        </form>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
