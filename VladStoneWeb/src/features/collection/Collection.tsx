import React from "react";

import { type CollectionCard, type CombatCatalogCard, ascendCard } from "../../api";
import { Card } from "../../shared/Card";
import { t } from "../../i18n";
import { CardDetail } from "./CardDetail";

export function Collection({
  cards,
  catalog,
  onCollectionChange,
}: {
  cards: CollectionCard[];
  catalog: CombatCatalogCard[];
  onCollectionChange: (cards: CollectionCard[]) => void;
}) {
  const [detailCard, setDetailCard] = React.useState<CollectionCard | null>(null);
  const catalogById = React.useMemo(() => new Map(catalog.map((card) => [card.id, card])), [catalog]);
  const detailCatalogCard = detailCard ? catalogById.get(detailCard.id) : null;

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
            <button
              aria-label={`Подробнее: ${card.name}`}
              className="card-open"
              onClick={() => setDetailCard(card)}
            >
              <Card card={card} />
            </button>
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
      {detailCard && detailCatalogCard ? (
        <CardDetail
          card={detailCatalogCard}
          collectionMeta={detailCard}
          onClose={() => setDetailCard(null)}
        />
      ) : null}
    </div>
  );
}
