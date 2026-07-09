/**
 * Detailed card view (collection): the full card face plus every stat spelled
 * out with labels, and placeholder sections for the ability description and the
 * coverage mini-schema. Those two are stubs until combat v4 lands the data
 * (COMBAT_REWORK §16.2 / §20 P0.3) — card mechanics are still designed one by
 * one with the owner, so we show "coming soon" rather than invent text.
 */
import React from "react";

import { type CollectionCard, type Rarity } from "../../api";
import { Card } from "../../shared/Card";
import {
  BootIcon,
  BurstIcon,
  HeartIcon,
  ManaIcon,
  RangeIcon,
  SwordIcon,
} from "../../shared/icons";

const RARITY_LABEL: Record<Rarity, string> = {
  common: "Обычная",
  uncommon: "Необычная",
  rare: "Редкая",
  epic: "Эпическая",
  legendary: "Легендарная",
};

// Placeholder coverage grid. Combat v4 moves the field to 5×5 with per-stance
// coverage patterns (COMBAT_REWORK §10) — until that data exists we only hint
// at the unit's own tile so the layout is ready to fill in later.
const COVERAGE_ROWS = 5;
const COVERAGE_COLS = 5;
const COVERAGE_UNIT_CELL = { row: COVERAGE_ROWS - 1, col: Math.floor(COVERAGE_COLS / 2) };

export function CardDetail({ card, onClose }: { card: CollectionCard; onClose: () => void }) {
  const stats: { icon: React.ReactNode; label: string; value: number }[] = [
    { icon: <ManaIcon />, label: "Мана", value: card.cost },
    { icon: <HeartIcon />, label: "Здоровье", value: card.hp },
    { icon: <BurstIcon />, label: "Урон", value: card.damage },
    { icon: <SwordIcon />, label: "Атаки за ход", value: card.attacks },
    { icon: <BootIcon />, label: "Шаги за ход", value: card.steps },
    { icon: <RangeIcon />, label: "Дальность", value: card.range },
  ];

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
            <Card card={card} />
            <p className="card-detail-tags">
              <span className="card-detail-rarity" data-rarity={card.rarity}>
                {RARITY_LABEL[card.rarity]}
              </span>
              <span className="muted">
                {card.ascension} · повторки {card.copies}/2
              </span>
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
              <p className="muted">
                Текст способности появится с боёвкой v4 — механики карт
                прорабатываются по одной.
              </p>
            </section>

            <section className="card-detail-section">
              <h3>Покрытие</h3>
              <div
                aria-hidden
                className="coverage-grid"
                style={{ ["--cov-cols"]: COVERAGE_COLS } as React.CSSProperties}
              >
                {Array.from({ length: COVERAGE_ROWS * COVERAGE_COLS }, (_, index) => {
                  const row = Math.floor(index / COVERAGE_COLS);
                  const col = index % COVERAGE_COLS;
                  const isUnit =
                    row === COVERAGE_UNIT_CELL.row && col === COVERAGE_UNIT_CELL.col;
                  return (
                    <span
                      className={isUnit ? "coverage-cell unit" : "coverage-cell"}
                      key={index}
                    />
                  );
                })}
              </div>
              <p className="muted">Схема зоны атаки появится с боёвкой v4.</p>
            </section>
          </div>
        </div>
      </section>
    </div>
  );
}
