import React from "react";

import {
  type CombatCatalogCard,
  type CombatMatch,
  type CombatResponse,
  type CombatUnit,
  type Placement,
  type SpellCast,
  getCombat,
  resolveCombat,
  startCombat,
} from "../../api";
import { CardArt } from "../../shared/cardArt";
import { BootIcon, BurstIcon, HeartIcon, SwordIcon } from "../../shared/icons";
import { type MatchRealtimeStatus, connectMatchRealtime } from "./matchRealtime";

type Props = {
  cards: CombatCatalogCard[];
  onBattleFinished: () => void;
};

type PlannedUnit = { kind: "unit"; card_id: string; row: number; col: number };
type PlannedSpell = { kind: "spell"; card_id: string; row: number; col: number };
type Planned = PlannedUnit | PlannedSpell;

const TURN_SECONDS = 30;
// Пикселей до превращения нажатия на карту в перетаскивание (ниже — тап-выбор).
const DRAG_THRESHOLD = 6;

export function BattleV4({ cards, onBattleFinished }: Props) {
  const catalog = React.useMemo(() => new Map(cards.map((c) => [c.id, c])), [cards]);
  const [match, setMatch] = React.useState<CombatMatch | null>(null);
  const [planned, setPlanned] = React.useState<Planned[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [resultDismissed, setResultDismissed] = React.useState(false);
  const [realtime, setRealtime] = React.useState<MatchRealtimeStatus>("Realtime не подключен");
  const [secondsLeft, setSecondsLeft] = React.useState(TURN_SECONDS);
  // Перетаскивание карты руки на клетку (pointer events — мышь и тач одним путём).
  const dragRef = React.useRef<{
    cardId: string;
    startX: number;
    startY: number;
    dragging: boolean;
  } | null>(null);
  // Глотает click, который браузер синтезирует после pointerup (чтобы драг/тап
  // не сработали дважды через onClick).
  const suppressClickRef = React.useRef(false);
  const [dragGhost, setDragGhost] = React.useState<{
    x: number;
    y: number;
    valid: boolean;
    name: string;
  } | null>(null);
  const autoSubmittedDeadline = React.useRef<string | null>(null);

  const viewer = match?.players.find((p) => p.id === match.viewer_id) ?? null;
  const enemy = match?.players.find((p) => viewer && p.team !== viewer.team) ?? null;
  const rows = match?.rows ?? 5;
  const cols = match?.cols ?? 5;
  const isFinished = match?.result.status === "finished" || match?.result.status === "expired";

  const plannedCost = planned.reduce((sum, p) => sum + (catalog.get(p.card_id)?.cost ?? 0), 0);
  const availableMana = Math.max(0, (viewer?.mana ?? 0) - plannedCost);

  // --- realtime: server-pushed updates (timer resolves, own resolve echo) ---
  React.useEffect(() => {
    if (!match) return undefined;
    const apply = (payload: CombatResponse) => {
      setMatch(payload.match);
      setPlanned([]);
      setSelected(null);
    };
    const disconnect = connectMatchRealtime({
      isBusy: () => false,
      matchId: match.id,
      onSnapshot: apply,
      onUpdate: apply,
      onStatus: setRealtime,
    });
    return disconnect;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [match?.id]);

  // --- turn countdown from the server planning deadline ---
  React.useEffect(() => {
    if (!match?.planning_deadline || match.status !== "planning") {
      setSecondsLeft(TURN_SECONDS);
      return undefined;
    }
    const tick = () => {
      const left = Math.max(
        0,
        Math.ceil((Date.parse(match.planning_deadline!) - Date.now()) / 1000),
      );
      setSecondsLeft(Math.min(TURN_SECONDS, left));
    };
    tick();
    const id = window.setInterval(tick, 500);
    return () => window.clearInterval(id);
  }, [match?.planning_deadline, match?.status]);

  React.useEffect(() => {
    if (
      !match?.planning_deadline ||
      match.status !== "planning" ||
      secondsLeft > 0 ||
      busy
    ) {
      return;
    }
    const deadlineKey = `${match.id}:${match.turn}:${match.planning_deadline}`;
    if (autoSubmittedDeadline.current === deadlineKey) return;
    autoSubmittedDeadline.current = deadlineKey;
    void handleResolve();
  }, [busy, match?.id, match?.planning_deadline, match?.status, match?.turn, secondsLeft]);

  React.useEffect(() => {
    if (isFinished) setResultDismissed(false);
  }, [isFinished]);

  async function handleStart() {
    setBusy(true);
    try {
      const res = await startCombat();
      setMatch(res.match);
      setPlanned([]);
      setSelected(null);
    } finally {
      setBusy(false);
    }
  }

  const unitAt = (row: number, col: number): CombatUnit | undefined =>
    match?.units.find((u) => !u.is_tower && u.row === row && u.col === col);
  const plannedAt = (row: number, col: number) =>
    planned.find((p) => p.row === row && p.col === col);

  // Absolute spawn rows for the viewer (bottom side): rows counted from own edge.
  const spawnRowsFor = (card: CombatCatalogCard): number[] =>
    (card.spawn_rows ?? []).map((r) => rows - r).filter((r) => r >= 0 && r < rows);

  function isValidTarget(card: CombatCatalogCard, row: number, col: number): boolean {
    if (col < 0 || col >= cols) return false;
    if (card.card_type === "spell") return unitAt(row, col) != null;
    if (!spawnRowsFor(card).includes(row)) return false;
    return !unitAt(row, col) && !plannedAt(row, col);
  }

  // Общая точка размещения — и клик-путь, и drag-n-drop идут через неё
  // (одинаковые проверки маны/зоны/занятости). true — карта запланирована.
  function placeCard(cardId: string, row: number, col: number): boolean {
    if (busy || isFinished) return false;
    const card = catalog.get(cardId);
    if (!card) return false;
    if (plannedCost + card.cost > (viewer?.mana ?? 0)) return false;
    if (!isValidTarget(card, row, col)) return false;
    setPlanned((cur) => [
      ...cur,
      card.card_type === "spell"
        ? { kind: "spell", card_id: card.id, row, col }
        : { kind: "unit", card_id: card.id, row, col },
    ]);
    // Если копий этой карты в руке больше не осталось — снять выбор.
    const inHand = (viewer?.hand ?? []).filter((c) => c === cardId).length;
    const plannedSame = planned.filter((p) => p.card_id === cardId).length + 1;
    if (plannedSame >= inHand) setSelected(null);
    return true;
  }

  function handleCellClick(row: number, col: number) {
    if (selected) placeCard(selected, row, col);
  }

  // Клетка под указателем — по elementFromPoint + data-атрибутам. Координаты
  // мерим ЖИВЬЁМ на каждом move: страница может проскроллиться / сервер
  // дорезолвит ход по таймеру, заранее снятые координаты устаревают.
  function cellFromPoint(x: number, y: number): { row: number; col: number } | null {
    const el = document.elementFromPoint(x, y)?.closest(".cell-v4");
    if (!el) return null;
    const row = Number(el.getAttribute("data-row"));
    const col = Number(el.getAttribute("data-col"));
    return Number.isNaN(row) || Number.isNaN(col) ? null : { row, col };
  }

  function handleCardPointerDown(e: React.PointerEvent, cardId: string) {
    if (busy || isFinished) return;
    // Начало нового взаимодействия сбрасывает подавление: настоящий драг мыши
    // может не породить финальный click, и застрявший флаг съел бы следующий.
    suppressClickRef.current = false;
    dragRef.current = { cardId, startX: e.clientX, startY: e.clientY, dragging: false };
    // Держим move/up на карте даже после ухода указателя за её пределы.
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // Некоторые окружения отклоняют capture на синтетических указателях — не фатально.
    }
  }

  function handleCardPointerMove(e: React.PointerEvent) {
    const d = dragRef.current;
    if (!d) return;
    const dist = Math.hypot(e.clientX - d.startX, e.clientY - d.startY);
    if (!d.dragging && dist < DRAG_THRESHOLD) return; // ещё тап, не драг
    if (!d.dragging) {
      d.dragging = true;
      setSelected(d.cardId); // выбор включает подсветку валидных клеток (.ok)
    }
    const cell = cellFromPoint(e.clientX, e.clientY);
    const card = catalog.get(d.cardId);
    const valid = Boolean(
      cell &&
        card &&
        plannedCost + card.cost <= (viewer?.mana ?? 0) &&
        isValidTarget(card, cell.row, cell.col),
    );
    setDragGhost({ x: e.clientX, y: e.clientY, valid, name: card?.name ?? d.cardId });
  }

  function handleCardPointerUp(e: React.PointerEvent) {
    const d = dragRef.current;
    dragRef.current = null;
    setDragGhost(null);
    if (!d) return;
    suppressClickRef.current = true; // click после pointerup не должен сработать
    if (d.dragging) {
      const cell = cellFromPoint(e.clientX, e.clientY);
      if (cell) placeCard(d.cardId, cell.row, cell.col);
    } else {
      setSelected((s) => (s === d.cardId ? null : d.cardId)); // тап — выбор/снятие
    }
  }

  function handleCardPointerCancel() {
    dragRef.current = null;
    setDragGhost(null);
  }

  function handleCardClick(cardId: string) {
    // Только клавиатурный/несенсорный путь: тач/мышь обслуживает pointerup.
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    setSelected((s) => (s === cardId ? null : cardId));
  }

  async function handleResolve() {
    if (!match || busy || isFinished) return;
    const placements: Placement[] = planned
      .filter((p): p is PlannedUnit => p.kind === "unit")
      .map(({ card_id, row, col }) => ({ card_id, row, col }));
    const spells: SpellCast[] = planned
      .filter((p): p is PlannedSpell => p.kind === "spell")
      .map(({ card_id, row, col }) => ({ card_id, row, col }));
    setBusy(true);
    try {
      const res = await resolveCombat(match.id, match.turn, placements, spells);
      setMatch(res.match);
      setPlanned([]);
      setSelected(null);
      if (res.match.result.status !== "active") onBattleFinished();
    } catch {
      // Deadline passed or already resolved — refetch the authoritative state.
      const fresh = await getCombat(match.id).catch(() => null);
      if (fresh) setMatch(fresh.match);
    } finally {
      setBusy(false);
    }
  }

  const towersOf = (side: "top" | "bottom") =>
    (match?.units ?? [])
      .filter((u) => u.is_tower && u.side === side)
      .sort((a, b) => a.col - b.col);

  // Hand entries, marking planned copies so a card can't be planned twice.
  const handEntries = React.useMemo(() => {
    const usedByCard: Record<string, number> = {};
    return (viewer?.hand ?? []).map((cardId, index) => {
      const used = (usedByCard[cardId] = (usedByCard[cardId] ?? 0) + 1);
      const plannedCount = planned.filter((p) => p.card_id === cardId).length;
      return { key: `${cardId}-${index}`, cardId, isPlanned: used <= plannedCount };
    });
  }, [viewer?.hand, planned]);

  if (!match) {
    return (
      <section className="battle-empty">
        <button className="ghost-btn" disabled={busy} onClick={handleStart}>
          {busy ? "Запуск..." : "Старт боя"}
        </button>
      </section>
    );
  }

  return (
    <div className="battle-v4">
      {dragGhost ? (
        <div
          aria-hidden
          className={`card-drag-ghost${dragGhost.valid ? " valid" : ""}`}
          style={{ left: dragGhost.x, top: dragGhost.y }}
        >
          {dragGhost.name}
        </div>
      ) : null}
      <section className="battle-stage">
        <div className="battle-topbar">
          <button className="ghost-btn" disabled={busy} onClick={handleStart}>
            Новый бой
          </button>
          <span className="rt-status">{realtime}</span>
        </div>

        <TowerRow label="Башни врага" towers={towersOf(enemy?.side ?? "top")} />

        <div
          className="board-v4"
          style={{ ["--cols" as string]: cols, ["--rows" as string]: rows } as React.CSSProperties}
        >
          {Array.from({ length: rows * cols }, (_, i) => {
            const row = Math.floor(i / cols);
            const col = i % cols;
            const unit = unitAt(row, col);
            const plan = plannedAt(row, col);
            const card = selected ? catalog.get(selected) : null;
            const highlight = card && isValidTarget(card, row, col);
            return (
              <button
                key={i}
                className={`cell-v4${highlight ? " ok" : ""}`}
                data-row={row}
                data-col={col}
                onClick={() => handleCellClick(row, col)}
              >
                {unit ? <UnitToken unit={unit} catalog={catalog} /> : null}
                {plan && !unit ? (
                  <span className={`plan-mark ${plan.kind}`}>
                    {catalog.get(plan.card_id)?.name ?? plan.card_id}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>

        <TowerRow label="Твои башни" towers={towersOf(viewer?.side ?? "bottom")} />

        <div className="mana-bar" aria-label="Мана">
          <div style={{ width: `${(availableMana / (match.mana_cap || 10)) * 100}%` }} />
          <span>
            Мана {availableMana}/{match.mana_cap}
          </span>
        </div>
      </section>

      <section className="battle-side">
        <div className="battle-hud">
          <div className={secondsLeft <= 5 ? "turn-timer warning" : "turn-timer"}>
            {secondsLeft}
          </div>
          <div className="turn-plate">
            <strong>Ход {match.turn}</strong>
            <span>Колода: {viewer?.deck_count ?? 0}</span>
          </div>
        </div>

        <div className="hand-v4">
          {handEntries.map(({ key, cardId, isPlanned }) => {
            const card = catalog.get(cardId);
            const affordable = (card?.cost ?? 0) + plannedCost <= (viewer?.mana ?? 0);
            return (
              <button
                key={key}
                className={[
                  "hand-card-v4",
                  selected === cardId ? "active" : "",
                  isPlanned ? "planned" : "",
                  !affordable && !isPlanned ? "poor" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                disabled={busy || isFinished || isPlanned || (!affordable && !isPlanned)}
                onClick={() => handleCardClick(cardId)}
                onPointerDown={(e) => handleCardPointerDown(e, cardId)}
                onPointerMove={handleCardPointerMove}
                onPointerUp={handleCardPointerUp}
                onPointerCancel={handleCardPointerCancel}
              >
                <span className="hand-card-art">
                  <CardArt cardId={cardId} label={card?.name ?? cardId} rarity="common" />
                </span>
                <span className="hand-card-name">{card?.name ?? cardId}</span>
                {/* Характеристики видны ВСЕГДА (описание-механика — отдельно, тултип). */}
                {card?.stats ? (
                  <span className="hand-card-stats">
                    <span title="Здоровье">
                      <HeartIcon />
                      {card.stats.hp}
                    </span>
                    <span title="Урон">
                      <BurstIcon />
                      {card.stats.damage}
                    </span>
                    <span title="Атаки за ход">
                      <SwordIcon />
                      {card.stats.attacks_per_turn}
                    </span>
                    <span title="Шаги за ход">
                      <BootIcon />
                      {card.stats.move_steps}
                    </span>
                  </span>
                ) : (
                  <span className="hand-card-stats spell">заклинание</span>
                )}
                <span className="hand-card-cost">{card?.cost ?? "?"}</span>
              </button>
            );
          })}
        </div>

        <button
          className="resolve-btn"
          disabled={busy || isFinished}
          onClick={handleResolve}
        >
          {busy ? "Ход идёт..." : "Завершить ход"}
        </button>

        <ul className="battle-log">
          {match.log.slice(-8).map((entry, i) => (
            <li key={i}>{entry.message}</li>
          ))}
        </ul>
      </section>

      {isFinished && !resultDismissed ? (
        <ResultOverlay match={match} onClose={() => setResultDismissed(true)} />
      ) : null}
    </div>
  );
}

function TowerRow({ label, towers }: { label: string; towers: CombatUnit[] }) {
  return (
    <div className="tower-row" aria-label={label}>
      {towers.map((t) => (
        <div key={t.id} className={`tower${t.current_hp <= 0 ? " dead" : ""}`}>
          <span className="tower-hp">{Math.max(0, t.current_hp)}</span>
          <span className="tower-bar">
            <span style={{ width: `${Math.max(0, (t.current_hp / t.max_hp) * 100)}%` }} />
          </span>
        </div>
      ))}
    </div>
  );
}

function UnitToken({
  unit,
  catalog,
}: {
  unit: CombatUnit;
  catalog: Map<string, CombatCatalogCard>;
}) {
  const card = unit.card_id ? catalog.get(unit.card_id) : null;
  return (
    <span className={`unit-v4 ${unit.side} stance-${unit.stance}`}>
      <span className="unit-v4-art">
        <CardArt cardId={unit.card_id ?? ""} label={card?.name ?? "?"} rarity="common" />
      </span>
      <span className="unit-v4-stat unit-v4-steps" title="Шаги за ход">
        <BootIcon />
        {unit.move_steps}
      </span>
      <span className="unit-v4-stat unit-v4-attacks" title="Атаки за ход">
        <SwordIcon />
        {unit.attacks_per_turn}
      </span>
      <span className="unit-v4-stat unit-v4-dmg" title="Урон">
        <BurstIcon />
        {unit.damage}
      </span>
      <span className="unit-v4-stat unit-v4-hp" title="Здоровье">
        {/* Только текущее HP: потолка нет (Q4), лечение может поднять выше
            базы, и "6/2" читалось бы как поломка. Максимум/база — в карточке. */}
        <HeartIcon />
        {Math.max(0, unit.current_hp)}
      </span>
      <span
        aria-label={unit.stance === "defense" ? "Стойка: защита" : "Стойка: атака"}
        className="unit-v4-stance"
        title={unit.stance === "defense" ? "Защита" : "Атака"}
      >
        <span aria-hidden="true">{unit.stance === "defense" ? "🛡" : "⚔"}</span>
      </span>
      {unit.statuses.length > 0 ? (
        <span className="unit-v4-status">{unit.statuses.map((s) => s.stacks).join("·")}</span>
      ) : null}
    </span>
  );
}

function ResultOverlay({ match, onClose }: { match: CombatMatch; onClose: () => void }) {
  if (match.result.status === "expired") {
    return (
      <div className="result-backdrop" onClick={onClose}>
        <section className="result-panel" onClick={(e) => e.stopPropagation()}>
          <strong>Матч завершён</strong>
          <span>Правила боя обновились — начни новый бой.</span>
          <button onClick={onClose}>Понятно</button>
        </section>
      </div>
    );
  }
  const viewer = match.players.find((p) => p.id === match.viewer_id);
  const didWin = viewer != null && match.result.winner_team === viewer.team;
  return (
    <div className="result-backdrop" onClick={onClose}>
      <section className="result-panel" onClick={(e) => e.stopPropagation()}>
        <strong>{didWin ? "Победа" : "Поражение"}</strong>
        <span>{didWin ? "Башни врага пали." : "Твои башни пали."}</span>
        <b>+{match.result.reward_coins} монет</b>
        <button onClick={onClose}>Забрать</button>
      </section>
    </div>
  );
}
