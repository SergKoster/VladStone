import React from "react";

import {
  acceptFriend,
  acceptFriendChallenge,
  blockSocialUser,
  getSocial,
  removeFriend,
  removeFriendChallenge,
  removeFriendRequest,
  requestFriend,
  searchSocialHandle,
  sendFriendChallenge,
  unblockSocialUser,
  type SocialPerson,
  type SocialSnapshot,
} from "../../api";

export function Friends({ onBattle }: { onBattle: (matchId: string) => void }) {
  const [social, setSocial] = React.useState<SocialSnapshot | null>(null);
  const [handle, setHandle] = React.useState("");
  const [found, setFound] = React.useState<SocialPerson | null>(null);
  const [message, setMessage] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const refresh = React.useCallback(async () => {
    const next = await getSocial();
    setSocial(next);
  }, []);

  React.useEffect(() => {
    void refresh().catch(() => setMessage("Не удалось загрузить друзей."));
  }, [refresh]);

  async function perform(action: () => Promise<unknown>) {
    setBusy(true);
    setMessage("");
    try {
      await action();
      await refresh();
    } catch {
      setMessage("Действие не удалось. Возможно, состояние уже изменилось.");
    } finally {
      setBusy(false);
    }
  }

  async function search(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    setFound(null);
    try {
      setFound(await searchSocialHandle(handle));
    } catch {
      setMessage("Игрок с таким ником не найден.");
    }
  }

  return (
    <section className="friends-page page">
      <p className="eyebrow">Социальное</p>
      <h1>Друзья</h1>
      <form className="friend-search" onSubmit={(event) => void search(event)}>
        <input
          aria-label="Ник игрока"
          maxLength={25}
          onChange={(event) => setHandle(event.target.value)}
          placeholder="Ник игрока"
          value={handle}
        />
        <button disabled={!handle || busy} type="submit">Найти</button>
      </form>
      {found ? (
        <div className="friend-search-result">
          <strong>{found.handle}</strong>
          <button disabled={busy} onClick={() => void perform(() => requestFriend(found.handle))}>
            Добавить
          </button>
          <button className="secondary" disabled={busy} onClick={() => void perform(() => blockSocialUser(found.user_id))}>
            Заблокировать
          </button>
        </div>
      ) : null}
      {message ? <p className="dashboard-message">{message}</p> : null}
      {!social ? <p className="muted">Загружаем…</p> : null}
      {social ? (
        <div className="friends-columns">
          <FriendSection title="Друзья" empty="Пока никого нет.">
            {social.friends.map((person) => (
              <div className="friend-row" key={person.user_id}>
                <strong>{person.handle}</strong>
                <div>
                  <button disabled={busy} onClick={() => void perform(() => sendFriendChallenge(person.user_id))}>
                    Вызвать
                  </button>
                  <button className="secondary" disabled={busy} onClick={() => void perform(() => removeFriend(person.user_id))}>
                    Удалить
                  </button>
                  <button className="secondary" disabled={busy} onClick={() => void perform(() => blockSocialUser(person.user_id))}>
                    Блок
                  </button>
                </div>
              </div>
            ))}
          </FriendSection>
          <FriendSection title="Входящие заявки" empty="Нет заявок.">
            {social.incoming_requests.map((person) => (
              <div className="friend-row" key={person.user_id}>
                <strong>{person.handle}</strong>
                <div>
                  <button disabled={busy} onClick={() => void perform(() => acceptFriend(person.user_id))}>
                    Принять
                  </button>
                  <button className="secondary" disabled={busy} onClick={() => void perform(() => removeFriendRequest(person.user_id))}>
                    Отклонить
                  </button>
                </div>
              </div>
            ))}
          </FriendSection>
          <FriendSection title="Исходящие заявки" empty="Нет заявок.">
            {social.outgoing_requests.map((person) => (
              <div className="friend-row" key={person.user_id}>
                <strong>{person.handle}</strong>
                <button className="secondary" disabled={busy} onClick={() => void perform(() => removeFriendRequest(person.user_id))}>
                  Отменить
                </button>
              </div>
            ))}
          </FriendSection>
          <FriendSection title="Вызовы" empty="Нет активных вызовов.">
            {social.incoming_challenges.map((challenge) => (
              <div className="friend-row" key={challenge.id}>
                <strong>{challenge.user.handle}</strong>
                <div>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void perform(async () => {
                        const result = await acceptFriendChallenge(challenge.id);
                        onBattle(result.match_id);
                      })
                    }
                  >
                    Принять бой
                  </button>
                  <button className="secondary" disabled={busy} onClick={() => void perform(() => removeFriendChallenge(challenge.id))}>
                    Отклонить
                  </button>
                </div>
              </div>
            ))}
            {social.outgoing_challenges.map((challenge) => (
              <div className="friend-row" key={challenge.id}>
                <strong>Ждём {challenge.user.handle}</strong>
                <button className="secondary" disabled={busy} onClick={() => void perform(() => removeFriendChallenge(challenge.id))}>
                  Отменить
                </button>
              </div>
            ))}
          </FriendSection>
          <FriendSection title="Заблокированы" empty="Список пуст.">
            {social.blocked.map((person) => (
              <div className="friend-row" key={person.user_id}>
                <strong>{person.handle}</strong>
                <button className="secondary" disabled={busy} onClick={() => void perform(() => unblockSocialUser(person.user_id))}>
                  Разблокировать
                </button>
              </div>
            ))}
          </FriendSection>
        </div>
      ) : null}
    </section>
  );
}

function FriendSection({
  children,
  empty,
  title,
}: React.PropsWithChildren<{ empty: string; title: string }>) {
  const rows = React.Children.toArray(children);
  return (
    <article className="friend-section">
      <h2>{title}</h2>
      {rows.length ? rows : <p className="muted">{empty}</p>}
    </article>
  );
}
