import { t } from "../../i18n";

export function Dashboard({
  coins,
  collectionCount,
  collectionTotal,
  message,
  onInvite,
  onPlay,
  onQuick,
}: {
  coins: number;
  collectionCount: number;
  collectionTotal: number;
  message?: string;
  onInvite: () => void;
  onPlay: () => void;
  onQuick: () => void;
}) {
  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>{t.dashboard}</h1>
          <p>{t.battleRules}</p>
        </div>
        <div className="dashboard-actions">
          <button onClick={onPlay}>Бой с ИИ</button>
          <button className="secondary" onClick={onInvite}>Бой с другом</button>
          <button className="secondary" onClick={onQuick}>Быстрый бой</button>
        </div>
      </header>
      <section className="metrics">
        <Metric label={t.coins} value={String(coins)} />
        <Metric label={t.collectionProgress} value={`${collectionCount} / ${collectionTotal}`} />
        <Metric label="Режим" value="Выбери бой" />
      </section>
      {message ? <p className="dashboard-message">{message}</p> : null}
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
