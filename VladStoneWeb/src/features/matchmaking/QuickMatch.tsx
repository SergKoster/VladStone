import React from "react";

import {
  cancelQuickMatchmaking,
  getQuickMatchmakingStatus,
  joinQuickMatchmaking,
  type QuickMatchmakingStatus,
} from "../../api";

const VISIBLE_POLL_MS = 2200;
const HIDDEN_POLL_MS = 12000;

export function QuickMatch({
  onBack,
  onMatched,
}: {
  onBack: () => void;
  onMatched: (matchId: string) => void;
}) {
  const enteredRef = React.useRef(false);
  const [status, setStatus] = React.useState<QuickMatchmakingStatus["status"]>("waiting");
  const [message, setMessage] = React.useState("Ищем соперника…");
  const [busy, setBusy] = React.useState(false);

  const consume = React.useCallback(
    (next: QuickMatchmakingStatus) => {
      setStatus(next.status);
      if (next.status === "matched" && next.match_id) {
        onMatched(next.match_id);
        return;
      }
      if (next.status === "waiting") setMessage("Ищем соперника…");
      if (next.status === "idle") setMessage("Поиск остановлен.");
    },
    [onMatched],
  );

  React.useEffect(() => {
    let disposed = false;
    let timer: number | null = null;

    const poll = async () => {
      try {
        let next = enteredRef.current
          ? await getQuickMatchmakingStatus()
          : await joinQuickMatchmaking();
        enteredRef.current = true;
        if (next.status === "idle") {
          next = await joinQuickMatchmaking();
        }
        if (!disposed) consume(next);
      } catch {
        if (!disposed) setMessage("Не удалось проверить поиск. Повторяем…");
      }
      if (!disposed) {
        timer = window.setTimeout(
          poll,
          document.visibilityState === "hidden" ? HIDDEN_POLL_MS : VISIBLE_POLL_MS,
        );
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible" && timer !== null) {
        window.clearTimeout(timer);
        void poll();
      }
    };
    void poll();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      disposed = true;
      if (timer !== null) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [consume]);

  async function cancel() {
    setBusy(true);
    try {
      const next = await cancelQuickMatchmaking();
      consume(next);
      if (next.status !== "matched") onBack();
    } catch {
      setMessage("Не удалось отменить поиск.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="quick-match-page page">
      <p className="eyebrow">Быстрый бой</p>
      <h1>Ищем соперника</h1>
      <p className="muted">Первый свободный игрок станет соперником. Рейтинг пока не учитывается.</p>
      <div aria-live="polite" className="quick-match-status">
        <span className={status === "waiting" ? "quick-match-dot searching" : "quick-match-dot"} />
        {message}
      </div>
      <button className="secondary" disabled={busy || status !== "waiting"} onClick={() => void cancel()}>
        Отменить поиск
      </button>
    </section>
  );
}
