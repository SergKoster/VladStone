import { t } from "../../i18n";

export function Dashboard({
  coins,
  collectionCount,
  message,
  onInvite,
  onPlay,
}: {
  coins: number;
  collectionCount: number;
  message?: string;
  onInvite: () => void;
  onPlay: () => void;
}) {
  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>{t.dashboard}</h1>
          <p>{t.battleRules}</p>
        </div>
        <div className="dashboard-actions">
          <button onClick={onPlay}>{t.play}</button>
          <button className="secondary" onClick={onInvite}>Пригласить друга</button>
        </div>
      </header>
      <section className="metrics">
        <Metric label={t.coins} value={String(coins)} />
        <Metric label={t.collectionProgress} value={`${Math.min(collectionCount, 2)} / 2`} />
        <Metric label="Режим" value="PvE bot" />
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
