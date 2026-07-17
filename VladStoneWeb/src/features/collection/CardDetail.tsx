/**
 * Полное v4-описание карты. Presenter получает только viewer-safe каталог и
 * пригоден и для коллекции, и для будущего detail из боя (W1b).
 */
import React from "react";

import {
  type CollectionCard,
  type CombatCatalogCard,
  type CombatStatusDefinition,
  type CombatUnit,
  type Rarity,
} from "../../api";
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
type UnitDetailState = Pick<
  CombatUnit,
  "attacks_per_turn" | "current_hp" | "damage" | "move_steps" | "stance" | "statuses"
>;

type DetailAction = {
  label: string;
  disabled: boolean;
  onClick: () => void;
};

export function CardDetail({
  card,
  collectionMeta,
  detailAction,
  fallbackDescription,
  fallbackName,
  onClose,
  statusCatalog = [],
  unit,
}: {
  card?: CombatCatalogCard;
  collectionMeta?: CollectionMeta;
  detailAction?: DetailAction;
  fallbackDescription?: string;
  fallbackName?: string;
  onClose: () => void;
  statusCatalog?: CombatStatusDefinition[];
  unit?: UnitDetailState;
}) {
  const closeButtonRef = React.useRef<HTMLButtonElement>(null);
  const title = card?.name ?? fallbackName ?? "Боевой токен";
  const stats = cardStats(card, unit);
  const spawnRows = card?.spawn_rows?.join("–");
  const statusById = new Map(statusCatalog.map((status) => [status.id, status]));

  React.useEffect(() => {
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="card-detail-backdrop" onClick={onClose}>
      <section
        aria-labelledby="card-detail-title"
        aria-modal="true"
        className="card-detail-panel"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <button
          aria-label="Закрыть"
          className="card-detail-close"
          onClick={onClose}
          ref={closeButtonRef}
        >
          ×
        </button>
        <div className="card-detail-body">
          <div className="card-detail-face">
            {card ? (
              <div className="card-detail-art">
                <CardArt cardId={card.id} label={card.name} rarity={card.rarity} />
              </div>
            ) : (
              <div className="card-detail-token">Боевой токен</div>
            )}
            <p className="card-detail-tags">
              {card ? (
                <span className="card-detail-rarity" data-rarity={card.rarity}>
                  {RARITY_LABEL[card.rarity]}
                </span>
              ) : null}
              <span className="muted">{card?.card_type === "spell" ? "Заклинание" : "Юнит"}</span>
              {unit ? (
                <span className={`card-detail-stance ${unit.stance}`}>
                  {unit.stance === "defense" ? "🛡 Защита" : "⚔ Атака"}
                </span>
              ) : null}
              {collectionMeta ? (
                <span className="muted">
                  {collectionMeta.ascension} · повторки {collectionMeta.copies}/2
                </span>
              ) : null}
            </p>
          </div>
          <div className="card-detail-info">
            <h2 className="card-detail-name" id="card-detail-title">{title}</h2>
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
              <p>{card?.rules_text ?? fallbackDescription ?? "Боевой токен без коллекционной карты."}</p>
            </section>

            {unit ? (
              <section className="card-detail-section card-detail-statuses">
                <h3>Текущие статусы</h3>
                {unit.statuses.length ? (
                  <ul>
                    {unit.statuses.map((status) => {
                      const definition = statusById.get(status.id);
                      const duration = status.ttl !== null
                        ? ` · ещё ходов: ${status.ttl}`
                        : definition?.decay === "permanent"
                          ? " · постоянно"
                          : "";
                      return (
                        <li key={status.id}>
                          <b>{definition?.name ?? status.id}</b>
                          {` · стаков: ${status.stacks}${duration}`}
                          {definition ? <small>{definition.description}</small> : null}
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="muted">Нет.</p>
                )}
              </section>
            ) : null}

            {card?.card_type === "unit" ? (
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
            {detailAction ? (
              <button
                className="card-detail-action"
                disabled={detailAction.disabled}
                onClick={detailAction.onClick}
              >
                {detailAction.label}
              </button>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}

function cardStats(
  card?: CombatCatalogCard,
  unit?: UnitDetailState,
): Array<{ icon: React.ReactNode; label: string; value: number }> {
  const stats: Array<{ icon: React.ReactNode; label: string; value: number }> = [];
  if (card) stats.push({ icon: <ManaIcon />, label: "Мана", value: card.cost });
  if (unit) {
    stats.push(
      { icon: <HeartIcon />, label: "Здоровье", value: Math.max(0, unit.current_hp) },
      { icon: <BurstIcon />, label: "Урон", value: unit.damage },
      { icon: <SwordIcon />, label: "Атаки за ход", value: unit.attacks_per_turn },
      { icon: <BootIcon />, label: "Шаги за ход", value: unit.move_steps },
    );
    return stats;
  }
  if (!card?.stats) return stats;
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
  // V4 (владелец, июль 2026): юнит рисуется в ЦЕНТРЕ схемы, а не в нижнем
  // ряду — так видно и покрытие «назад» (кресты/кольца бьют за спину).
  const unitRow = Math.floor(board.rows / 2);
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
