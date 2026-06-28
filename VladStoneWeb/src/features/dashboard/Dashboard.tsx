import { t } from "../../i18n";

export function Dashboard({
  coins,
  collectionCount,
  onPlay,
}: {
  coins: number;
  collectionCount: number;
  onPlay: () => void;
}) {
  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>{t.dashboard}</h1>
          <p>{t.battleRules}</p>
        </div>
        <button onClick={onPlay}>{t.play}</button>
      </header>
      <section className="metrics">
        <Metric label={t.coins} value={String(coins)} />
        <Metric label={t.collectionProgress} value={`${Math.min(collectionCount, 2)} / 2`} />
        <Metric label="Режим" value="PvE bot" />
      </section>
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
