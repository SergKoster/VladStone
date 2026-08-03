/**
 * Visual card face (4:5). A square art panel carries the primary stats as
 * corner pips; secondary stats sit in the footer strip. Presentational only —
 * callers provide the interactive wrapper (hand button, collection article).
 */
import { type CollectionCard } from "../api";
import { CardArt } from "./cardArt";
import { BootIcon, BurstIcon, HeartIcon, ManaIcon, SwordIcon } from "./icons";

export function Card({ card }: { card: CollectionCard }) {
  const stats = card.stats;
  return (
    <div className="card-face" data-rarity={card.rarity}>
      <div className="card-art-wrap">
        <CardArt cardId={card.id} label={card.name} rarity={card.rarity} />
        <span className="card-pip cost">
          <ManaIcon />
          {card.cost}
        </span>
        {stats ? (
          <>
            <span className="card-pip damage">
              <BurstIcon />
              {stats.damage}
            </span>
            <span className="card-pip hp">
              <HeartIcon />
              {stats.hp}
            </span>
          </>
        ) : null}
      </div>
      <div className="card-info">
        <span className="card-name">{card.name}</span>
        <div className="card-footer">
          {stats ? (
            <>
              <span className="card-stat" title="Атаки за ход">
                <SwordIcon />
                {stats.attacks_per_turn}
              </span>
              <span className="card-stat" title="Шаги за ход">
                <BootIcon />
                {stats.move_steps}
              </span>
            </>
          ) : (
            <span className="card-stat">Заклинание</span>
          )}
        </div>
      </div>
    </div>
  );
}
