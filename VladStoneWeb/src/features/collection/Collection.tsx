import React from "react";

import { type CollectionCard, type CombatCatalogCard } from "../../api";
import { Card } from "../../shared/Card";
import { t } from "../../i18n";
import { CardDetail } from "./CardDetail";

export function Collection({
  cards,
  catalog,
}: {
  cards: CollectionCard[];
  catalog: CombatCatalogCard[];
}) {
  const [detailCard, setDetailCard] = React.useState<CollectionCard | null>(null);
  const catalogById = React.useMemo(() => new Map(catalog.map((card) => [card.id, card])), [catalog]);
  const detailCatalogCard = detailCard ? catalogById.get(detailCard.id) : null;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>{t.collection}</h1>
          <p>Карты и их боевые свойства берутся из единого каталога v4.</p>
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
            <p className="muted">Копий: {card.copies}</p>
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
