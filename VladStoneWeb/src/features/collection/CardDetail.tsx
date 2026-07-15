/**
 * Полное v4-описание карты. Presenter получает только viewer-safe каталог и
 * пригоден и для коллекции, и для будущего detail из боя (W1b).
 */
import React from "react";

import { type CollectionCard, type CombatCatalogCard, type Rarity } from "../../api";
import { CardArt } from "../../shared/cardArt";
import {
  BootIcon,
  BurstIcon,
  HeartIcon,
  ManaIcon,
  SwordIcon,
} from "../../shared/icons";

const RARITY_LABEL: Record<Rarity, string> = {
  common: "Обычная",
  uncommon: "Необычная",
  rare: "Редкая",
  epic: "Эпическая",
  legendary: "Легендарная",
};

type CollectionMeta = Pick<CollectionCard, "ascension" | "copies">;
type CoverageCell = { forward: number; col: number };

export function CardDetail({
  card,
  collectionMeta,
  onClose,
}: {
  card: CombatCatalogCard;
  collectionMeta?: CollectionMeta;
  onClose: () => void;
}) {
  const stats = cardStats(card);
  const spawnRows = card.spawn_rows?.join("–");

  return (
    <div className="card-detail-backdrop" onClick={onClose}>
      <section
        aria-label={`Карта ${card.name}`}
        className="card-detail-panel"
        onClick={(event) => event.stopPropagation()}
      >
        <button aria-label="Закрыть" className="card-detail-close" onClick={onClose}>
          ×
        </button>
        <div className="card-detail-body">
          <div className="card-detail-face">
            <div className="card-detail-art">
              <CardArt cardId={card.id} label={card.name} rarity={card.rarity} />
            </div>
            <p className="card-detail-tags">
              <span className="card-detail-rarity" data-rarity={card.rarity}>
                {RARITY_LABEL[card.rarity]}
              </span>
              <span className="muted">{card.card_type === "unit" ? "Юнит" : "Заклинание"}</span>
              {collectionMeta ? (
                <span className="muted">
                  {collectionMeta.ascension} · повторки {collectionMeta.copies}/2
                </span>
              ) : null}
            </p>
          </div>
          <div className="card-detail-info">
            <h2 className="card-detail-name">{card.name}</h2>
            <dl className="card-detail-stats">
              {stats.map((stat) => (
                <div className="card-detail-stat" key={stat.label}>
                  <dt>
                    {stat.icon}
                    {stat.label}
                  </dt>
                  <dd>{stat.value}</dd>
                </div>
              ))}
            </dl>

            <section className="card-detail-section">
              <h3>Описание</h3>
              <p>{card.rules_text}</p>
            </section>

            {card.card_type === "unit" ? (
              <>
                <section className="card-detail-section">
                  <h3>Покрытие</h3>
                  <div className="coverage-schemes">
                    <CoveragePreview
                      board={card.board}
                      cells={card.coverage_attack ?? []}
                      label="Атака"
                    />
                    <CoveragePreview
                      board={card.board}
                      cells={card.coverage_defense ?? []}
                      label="Защита"
                    />
                  </div>
                </section>
                <section className="card-detail-section">
                  <h3>Постановка</h3>
                  <p>Ряды от своего края: {spawnRows ?? "—"}.</p>
                </section>
              </>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}

function cardStats(card: CombatCatalogCard): Array<{ icon: React.ReactNode; label: string; value: number }> {
  const stats = [{ icon: <ManaIcon />, label: "Мана", value: card.cost }];
  if (!card.stats) return stats;
  stats.push(
    { icon: <HeartIcon />, label: "Здоровье", value: card.stats.hp },
    { icon: <BurstIcon />, label: "Урон", value: card.stats.damage },
    { icon: <SwordIcon />, label: "Атаки за ход", value: card.stats.attacks_per_turn },
    { icon: <BootIcon />, label: "Шаги за ход", value: card.stats.move_steps },
  );
  if (card.damage_defense != null) {
    stats.push({ icon: <BurstIcon />, label: "Урон в защите", value: card.damage_defense });
  }
  return stats;
}

function CoveragePreview({
  board,
  cells,
  label,
}: {
  board: CombatCatalogCard["board"];
  cells: CoverageCell[];
  label: string;
}) {
  const unitRow = board.rows - 1;
  const unitCol = Math.floor(board.cols / 2);
  const covered = new Set(
    cells
      .map(({ forward, col }) => `${unitRow - forward}:${unitCol + col}`)
      .filter((key) => {
        const [row, col] = key.split(":").map(Number);
        return row >= 0 && row < board.rows && col >= 0 && col < board.cols;
      }),
  );

  return (
    <div className="coverage-scheme">
      <strong>{label}</strong>
      <div
        aria-label={`${label}: ${cells.length ? "есть покрытие" : "нет покрытия"}`}
        className="coverage-grid"
        style={{ ["--cov-cols" as string]: board.cols } as React.CSSProperties}
      >
        {Array.from({ length: board.rows * board.cols }, (_, index) => {
          const row = Math.floor(index / board.cols);
          const col = index % board.cols;
          const isUnit = row === unitRow && col === unitCol;
          const isCovered = covered.has(`${row}:${col}`);
          return (
            <span
              className={[
                "coverage-cell",
                isUnit ? "unit" : "",
                isCovered ? "covered" : "",
              ].filter(Boolean).join(" ")}
              key={index}
            />
          );
        })}
      </div>
      {!cells.length ? <span className="muted">Нет покрытия</span> : null}
    </div>
  );
}
