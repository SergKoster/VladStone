import React from "react";

import {
  cancelMatchInvite,
  getMatchLobby,
  joinMatchInvite,
  type MatchLobbyResponse,
} from "../../api";

export const PENDING_INVITE_ROUTE_KEY = "vladstone.pendingInviteRoute";

export function CreatedInviteLobby({
  matchId,
  onBack,
  onStarted,
}: {
  matchId: string;
  onBack: () => void;
  onStarted: () => void;
}) {
  const [lobby, setLobby] = React.useState<MatchLobbyResponse | null>(null);
  const [message, setMessage] = React.useState("Проверяем приглашение…");
  const [busy, setBusy] = React.useState(false);
  const sharePath = window.sessionStorage.getItem(`vladstone.invite.${matchId}`);
  const inviteUrl = sharePath ? `${window.location.origin}${sharePath}` : null;

  React.useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await getMatchLobby(matchId);
        if (cancelled) return;
        setLobby(next);
        if (next.match.status === "planning") {
          onStarted();
          return;
        }
        if (next.match.status === "expired" || next.invite.status !== "pending") {
          setMessage("Приглашение больше не активно.");
          return;
        }
        setMessage("Ждём, пока друг откроет ссылку.");
      } catch {
        if (!cancelled) setMessage("Не удалось обновить статус приглашения.");
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [matchId, onStarted]);

  async function copyInvite() {
    if (!inviteUrl) return;
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setMessage("Ссылка скопирована — отправь её другу.");
    } catch {
      setMessage("Не удалось скопировать ссылку. Скопируй её из адресной строки.");
    }
  }

  async function cancelInvite() {
    setBusy(true);
    try {
      await cancelMatchInvite(matchId);
      window.sessionStorage.removeItem(`vladstone.invite.${matchId}`);
      onBack();
    } catch {
      setMessage("Не удалось отменить приглашение.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="invite-page page">
      <p className="eyebrow">PvP с другом</p>
      <h1>Приглашение готово</h1>
      <p className="muted">{message}</p>
      {inviteUrl ? (
        <div className="invite-link-row">
          <input aria-label="Ссылка-приглашение" readOnly value={inviteUrl} />
          <button onClick={copyInvite}>Копировать</button>
        </div>
      ) : (
        <p className="invite-warning">После перезагрузки создай новое приглашение, чтобы получить ссылку.</p>
      )}
      <p className="invite-meta">
        Статус: {lobby?.invite.status === "pending" ? "ожидание игрока" : lobby?.invite.status ?? "…"}
      </p>
      <div className="invite-actions">
        <button className="secondary" disabled={busy} onClick={cancelInvite}>Отменить</button>
        <button className="ghost-btn" onClick={onBack}>Назад</button>
      </div>
    </section>
  );
}

export function JoinInvite({
  token,
  onBack,
  onJoined,
}: {
  token: string;
  onBack: () => void;
  onJoined: (matchId: string) => void;
}) {
  const started = React.useRef(false);
  const [message, setMessage] = React.useState("Подключаем к матчу…");

  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    void joinMatchInvite(token)
      .then((response) => {
        window.sessionStorage.removeItem(PENDING_INVITE_ROUTE_KEY);
        onJoined(response.match.id);
      })
      .catch(() => setMessage("Приглашение недействительно, истекло или уже занято."));
  }, [onJoined, token]);

  return (
    <section className="invite-page page">
      <p className="eyebrow">PvP с другом</p>
      <h1>Приглашение на бой</h1>
      <p className="muted">{message}</p>
      {message !== "Подключаем к матчу…" ? <button onClick={onBack}>На главную</button> : null}
    </section>
  );
}
