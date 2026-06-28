import { type CollectionCard, ascendCard } from "../../api";
import { t } from "../../i18n";

export function Collection({
  cards,
  onCollectionChange,
}: {
  cards: CollectionCard[];
  onCollectionChange: (cards: CollectionCard[]) => void;
}) {
  async function handleAscend(card: CollectionCard) {
    const payload = await ascendCard(card.id);
    onCollectionChange(payload.cards);
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>{t.collection}</h1>
          <p>Повторки соединяются: 2 одинаковые карты одной ступени дают следующее возвышение.</p>
        </div>
      </header>
      <section className="card-grid">
        {cards.map((card) => (
          <article className="game-card" key={card.id}>
            <div className="card-topline">
              <strong>{card.name}</strong>
              <span>{card.cost}</span>
            </div>
            <dl>
              <div>
                <dt>HP</dt>
                <dd>{card.hp}</dd>
              </div>
              <div>
                <dt>Урон</dt>
                <dd>{card.damage}</dd>
              </div>
              <div>
                <dt>Дальность</dt>
                <dd>{card.range}</dd>
              </div>
              <div>
                <dt>Шаги</dt>
                <dd>{card.steps}</dd>
              </div>
              <div>
                <dt>Атаки</dt>
                <dd>{card.attacks}</dd>
              </div>
            </dl>
            <p className="muted">{card.ascension} · повторки {card.copies}/2</p>
            <button
              className="secondary"
              disabled={card.copies < 2 || card.ascension !== "Дефолт"}
              onClick={() => handleAscend(card)}
            >
              Возвысить
            </button>
          </article>
        ))}
      </section>
    </div>
  );
}
