import React from "react";

import {
  type CombatEvent,
  type CombatMatch,
  type CombatUnit,
  type CollectionCard,
  type Placement,
  type Rarity,
  getActiveCombats,
  getCombat,
  logClientEvent,
  resolveCombat,
  startCombat,
} from "../../api";
import { Card } from "../../shared/Card";
import { CardArt } from "../../shared/cardArt";
import { BootIcon, BurstIcon, HeartIcon, SwordIcon } from "../../shared/icons";
import { applyEventHp, applyEventSnapshot, wait } from "./animationState";
import {
  type AnimationSpeed,
  STRIKE_IMPACT,
  durationFor,
  layerTimings,
  pauseFor,
  prefersReducedMotion,
  strikeFor,
} from "./animationConfig";

// Online play resolves micro-steps on the server; the client just replays them
// at one fixed, deterministic pace (no per-client speed switching mid-match).
const ANIMATION_SPEED: AnimationSpeed = "normal";
// Planning seconds shown on the turn timer (mirrors TURN_DURATION_SECONDS). The
// server pushes the deadline past the resolution animation, so we clamp the
// display to this — the timer reads "frozen" until planning actually starts.
const TURN_SECONDS = 30;
import {
  type DamagePopup,
  type LungeEffect,
  computeLunge,
  damageLocation,
  isCollision,
  isMeleeLunge,
  useBattleEffects,
} from "./battleAnimations";
import {
  battleSnapshot,
  nextManaGain,
  secondsFromDeadline,
  shortCardName,
  withCombatEvents,
} from "./battleState";
import { type MatchRealtimeStatus, connectMatchRealtime } from "./matchRealtime";
import { useBattleAnimationState } from "./useBattleAnimationState";
import { useBattleUiState } from "./useBattleUiState";

export function Battle({
  cards,
  onBattleFinished,
}: {
  cards: CollectionCard[];
  onBattleFinished: () => void;
}) {
  const cells = Array.from({ length: 15 }, (_, index) => index);
  const [match, setMatch] = React.useState<CombatMatch | null>(null);
  const {
    battleMessage,
    isResolving,
    isTimerRunning,
    placements,
    resultDismissed,
    secondsLeft,
    selectedCard,
    setBattleMessage,
    setIsResolving,
    setIsTimerRunning,
    setPlacements,
    setResultDismissed,
    setSecondsLeft,
    setSelectedCard,
  } = useBattleUiState();
  const { activeEvent, isAnimating, setActiveEvent, setIsAnimating } = useBattleAnimationState();
  const { lunges, setLunges, clearLunges, popups, addPopup, dyingIds, markDying, reset: resetEffects } =
    useBattleEffects();
  const [realtimeStatus, setRealtimeStatus] =
    React.useState<MatchRealtimeStatus>("Realtime не подключен");
  const isRealtimeBusyRef = React.useRef(false);

  const player = match?.players.find((candidate) => candidate.id === "player");
  const bot = match?.players.find((candidate) => candidate.id === "bot");
  const isFinished = match?.result.status === "finished";
  const playerMana = player?.mana ?? 0;
  const plannedCost = placements.reduce((sum, placement) => {
    const card = cards.find((candidate) => candidate.id === placement.card_id);
    return sum + (card?.cost ?? 0);
  }, 0);
  const availableMana = Math.max(0, playerMana - plannedCost);
  const nextMana = nextManaGain(match?.turn ?? 1);

  React.useEffect(() => {
    isRealtimeBusyRef.current = isResolving || isAnimating;
  }, [isAnimating, isResolving]);

  React.useEffect(() => {
    if (match) {
      return;
    }
    getActiveCombats()
      .then((payload) => {
        const activeMatch = payload.matches[0];
        if (!activeMatch) {
          return;
        }
        setMatch(withCombatEvents(activeMatch, []));
        setSecondsLeft(secondsFromDeadline(activeMatch));
        setIsTimerRunning(activeMatch.status === "planning");
        setBattleMessage("Активный бой восстановлен.");
      })
      .catch(() => undefined);
  }, [match]);

  React.useEffect(() => {
    if (!match || isFinished) {
      setRealtimeStatus("Realtime не подключен");
      return undefined;
    }

    return connectMatchRealtime({
      isBusy: () => isRealtimeBusyRef.current,
      matchId: match.id,
      onSnapshot: (payload) => {
        setMatch(withCombatEvents(payload.match, payload.events));
        setSecondsLeft(secondsFromDeadline(payload.match));
      },
      onStatus: setRealtimeStatus,
      onUpdate: (payload) => void applyRealtimeMatchUpdate(payload),
    });
  }, [isFinished, match?.id]);

  React.useEffect(() => {
    if (!match || isFinished || realtimeStatus === "Realtime подключен") {
      return undefined;
    }
    const pollingTimerId = window.setInterval(() => {
      if (isRealtimeBusyRef.current) {
        return;
      }
      getCombat(match.id)
        .then((payload) => {
          setMatch(withCombatEvents(payload.match, payload.events));
          setSecondsLeft(secondsFromDeadline(payload.match));
        })
        .catch(() => undefined);
    }, 8000);
    return () => window.clearInterval(pollingTimerId);
  }, [isFinished, match, realtimeStatus]);

  function logBattleEvent(event: string, payload: Record<string, unknown> = {}) {
    logClientEvent(event, battleSnapshot(match, placements, payload));
  }

  const handleResolve = React.useCallback(async () => {
    if (!match || isResolving || isAnimating || isFinished) {
      return;
    }
    logClientEvent("battle_resolve_clicked", battleSnapshot(match, placements));
    setIsResolving(true);
    setIsTimerRunning(false);
    try {
      const payload = await resolveCombat(match.id, match.turn, placements);
      const resolvedMatch = withCombatEvents(payload.match, payload.events);
      logClientEvent(
        "battle_resolve_success",
        battleSnapshot(resolvedMatch, [], { previousTurn: match.turn }),
      );
      await playCombatEvents(resolvedMatch);
      setPlacements([]);
      setSelectedCard(null);
      setSecondsLeft(secondsFromDeadline(resolvedMatch));
      setIsTimerRunning(resolvedMatch.result.status !== "finished");
      setBattleMessage("Ход разыгран.");
    } catch (error) {
      logClientEvent(
        "battle_resolve_error",
        battleSnapshot(match, placements, { error: String(error) }),
      );
      getCombat(match.id)
        .then((payload) => {
          setMatch(withCombatEvents(payload.match, payload.events));
          setSecondsLeft(secondsFromDeadline(payload.match));
        })
        .catch(() => undefined);
      setBattleMessage("Ход уже устарел или сервер разыгрывает его сам.");
    } finally {
      setIsResolving(false);
    }
  }, [isAnimating, isFinished, isResolving, match, placements]);

  React.useEffect(() => {
    if (!isTimerRunning || !match || isFinished || isAnimating) {
      return undefined;
    }
    const timerId = window.setInterval(() => {
      setSecondsLeft(secondsFromDeadline(match));
    }, 1000);
    return () => window.clearInterval(timerId);
  }, [isAnimating, isFinished, isTimerRunning, match]);

  React.useEffect(() => {
    if (isTimerRunning && secondsLeft === 0) {
      logBattleEvent("battle_timer_zero");
      setBattleMessage("Время вышло. Сервер разыгрывает ход.");
    }
  }, [isTimerRunning, secondsLeft]);

  async function handleStartBattle() {
    logBattleEvent("battle_start_clicked");
    try {
      const payload = await startCombat();
      const startedMatch = withCombatEvents(payload.match, payload.events);
      logClientEvent("battle_start_success", battleSnapshot(startedMatch, []));
      setMatch(startedMatch);
      setPlacements([]);
      setSelectedCard(null);
      setActiveEvent(null);
      setResultDismissed(false);
      setSecondsLeft(secondsFromDeadline(startedMatch));
      setIsTimerRunning(true);
      setBattleMessage("Бой начался. Выбери карту и клетку спавна.");
    } catch (error) {
      logBattleEvent("battle_start_error", { error: String(error) });
      setBattleMessage("Не удалось начать бой. Проверь API.");
    }
  }

  async function applyRealtimeMatchUpdate(payload: { match: CombatMatch; events: CombatEvent[] }) {
    const resolvedMatch = withCombatEvents(payload.match, payload.events);
    logClientEvent("battle_realtime_update", battleSnapshot(resolvedMatch, placements));
    await playCombatEvents(resolvedMatch);
    setPlacements([]);
    setSelectedCard(null);
    setSecondsLeft(secondsFromDeadline(resolvedMatch));
    setIsTimerRunning(resolvedMatch.result.status !== "finished");
    setBattleMessage("Бой обновлён по realtime.");
  }

  function cellPosition(cell: number) {
    return {
      row: Math.floor(cell / 3),
      col: cell % 3,
    };
  }

  function plannedUnitAt(row: number, col: number) {
    return placements.find((placement) => placement.row === row && placement.col === col);
  }

  function unitAt(row: number, col: number) {
    return match?.units.find((unit) => unit.position.row === row && unit.position.col === col);
  }

  function samePosition(
    a: { row: number; col: number } | null,
    b: { row: number; col: number } | null,
  ) {
    return Boolean(a && b && a.row === b.row && a.col === b.col);
  }

  function dropSpawnedPlacement(event: CombatEvent) {
    if (event.type !== "spawn") {
      return;
    }
    const spawnedUnit = event.snapshot.units?.find((unit) => unit.id === event.actor_id);
    if (spawnedUnit?.side !== "bottom") {
      return;
    }
    setPlacements((current) =>
      current.filter(
        (placement) =>
          placement.row !== spawnedUnit.position.row ||
          placement.col !== spawnedUnit.position.col,
      ),
    );
  }

  function applyEventToBoard(event: CombatEvent, finalMatch: CombatMatch) {
    if (event.type === "death" && event.actor_id) {
      // Keep the dying unit on the board (skip its removal) so the fade plays.
      markDying(event.actor_id);
      setMatch((current) => ({
        ...(current ?? finalMatch),
        players: event.snapshot.players ?? current?.players ?? finalMatch.players,
        log: [...(current?.log ?? []), { message: event.message }].slice(-24),
      }));
    } else {
      setMatch((current) => applyEventSnapshot(current ?? finalMatch, event, finalMatch));
    }
    dropSpawnedPlacement(event);
  }

  function emitDamagePopup(event: CombatEvent, ttlMs: number) {
    const location = damageLocation(event);
    if (location) {
      addPopup(
        { row: location.row, col: location.col, amount: event.damage!, kind: location.kind },
        ttlMs,
      );
    }
  }

  // Attacker(s) jump sharply onto the target, the hit lands (HP drops here, in
  // sync with the animation), then they ease back. Passing several lunge events
  // animates them together — both sides of a collision leap into the cell at once.
  // `snapshotEvent` carries the post-hit state to apply at the impact moment.
  async function playLunge(
    lungeEvents: CombatEvent[],
    snapshotEvent: CombatEvent,
    finalMatch: CombatMatch,
  ) {
    const speed = ANIMATION_SPEED;
    const strikeMs = strikeFor(speed);
    const impactMs = Math.round(strikeMs * STRIKE_IMPACT);
    const ttl = Math.max(900, strikeMs);
    const offsets = lungeEvents
      .map(computeLunge)
      .filter((entry): entry is LungeEffect => entry !== null);

    setLunges(offsets);
    await wait(impactMs);
    // Impact: the attacker is on the target — apply the post-hit board state and
    // patch each target's exact HP (snapshots are pre-damage), then pop numbers.
    applyEventToBoard(snapshotEvent, finalMatch);
    setMatch((current) =>
      lungeEvents.reduce((acc, event) => applyEventHp(acc, event), current ?? finalMatch),
    );
    lungeEvents.forEach((event) => emitDamagePopup(event, ttl));
    await wait(strikeMs - impactMs);
    clearLunges();
  }

  async function playCombatEvents(finalMatch: CombatMatch) {
    const events = finalMatch.events ?? [];
    if (!events.length) {
      setMatch(finalMatch);
      setActiveEvent(null);
      return;
    }

    const speed = ANIMATION_SPEED;
    setIsAnimating(true);

    // Fallback for debug/reduced motion: jump straight to the resolved state.
    if (speed === "off" || prefersReducedMotion()) {
      events.forEach(dropSpawnedPlacement);
      setMatch(finalMatch);
      setActiveEvent(null);
      resetEffects();
      setIsAnimating(false);
      if (finalMatch.result.status === "finished") {
        onBattleFinished();
      }
      return;
    }

    const pause = pauseFor(speed);
    let index = 0;
    while (index < events.length) {
      const event = events[index];
      setActiveEvent(event);
      setBattleMessage(event.message);

      // Collision cluster: consecutive collision events on the same cell play
      // together so both contenders leap into the tile from their own sides.
      // The cluster's last event holds the post-collision HP, applied at impact.
      if (isCollision(event)) {
        const cell = event.to_position;
        const group: CombatEvent[] = [];
        while (
          index < events.length &&
          isCollision(events[index]) &&
          samePosition(events[index].to_position, cell)
        ) {
          group.push(events[index]);
          index += 1;
        }
        await playLunge(group.filter((entry) => entry.actor_id), group[group.length - 1], finalMatch);
        await wait(pause);
        continue;
      }

      // Melee/ranged strike: keep the board as-is until the attacker lands, then
      // playLunge applies the hit (HP) in sync with the animation.
      if (isMeleeLunge(event)) {
        await playLunge([event], event, finalMatch);
        await wait(pause);
        index += 1;
        continue;
      }

      applyEventToBoard(event, finalMatch);

      if (event.type === "death") {
        await wait(durationFor("death", speed));
        await wait(pause);
        index += 1;
        continue;
      }

      await wait(durationFor(event.type, speed));
      await wait(pause);
      index += 1;
    }

    setMatch(finalMatch);
    setActiveEvent(null);
    resetEffects();
    setIsAnimating(false);
    if (finalMatch.result.status === "finished") {
      onBattleFinished();
    }
  }

  function handleCellClick(cell: number) {
    if (isResolving || isAnimating || isFinished) {
      return;
    }
    const position = cellPosition(cell);
    logBattleEvent("battle_cell_clicked", {
      cell,
      position,
      selectedCardId: selectedCard?.id ?? null,
    });
    const planned = plannedUnitAt(position.row, position.col);
    if (planned) {
      const nextPlacements = placements.filter(
        (placement) => placement.row !== position.row || placement.col !== position.col,
      );
      setPlacements(nextPlacements);
      logClientEvent(
        "battle_plan_cancelled",
        battleSnapshot(match, nextPlacements, { cancelled: planned, position }),
      );
      setBattleMessage(`${shortCardName(planned.card_id)} убран из плана. Мана возвращена.`);
      return;
    }
    if (!selectedCard) {
      logBattleEvent("battle_cell_rejected", { reason: "no_selected_card", position });
      setBattleMessage("Сначала выбери карту в руке.");
      return;
    }
    if (position.row !== 4) {
      logBattleEvent("battle_cell_rejected", { reason: "not_spawn_row", position });
      setBattleMessage("Ставить юнитов пока можно только на ближайшие 3 клетки.");
      return;
    }
    const existingUnit = unitAt(position.row, position.col);
    if (existingUnit?.side === "bottom") {
      logBattleEvent("battle_cell_rejected", { reason: "occupied", position });
      setBattleMessage("Эта клетка уже занята.");
      return;
    }
    if (existingUnit?.side === "top" && unitAt(position.row - 1, position.col)) {
      logBattleEvent("battle_cell_rejected", {
        reason: "blocked_push_target",
        position,
        displacedUnitId: existingUnit.id,
      });
      setBattleMessage("Этого врага некуда вытолкнуть: клетка за ним занята.");
      return;
    }
    if (availableMana < selectedCard.cost) {
      logBattleEvent("battle_cell_rejected", {
        reason: "not_enough_mana",
        position,
        selectedCardId: selectedCard.id,
        availableMana,
      });
      setBattleMessage("Не хватает маны.");
      return;
    }
    const nextPlacements = [...placements, { card_id: selectedCard.id, ...position }];
    setPlacements(nextPlacements);
    logClientEvent(
      "battle_plan_added",
      battleSnapshot(match, nextPlacements, {
        added: { card_id: selectedCard.id, ...position },
        displacedUnitId: existingUnit?.id ?? null,
        availableManaAfterPlan: availableMana - selectedCard.cost,
      }),
    );
    setBattleMessage(
      existingUnit
        ? `${selectedCard.name} выталкивает ${shortCardName(existingUnit.card_id)}.`
        : `${selectedCard.name} готовится выйти на поле.`,
    );
  }

  function handleSelectCard(card: CollectionCard) {
    if (isResolving || isAnimating || isFinished) {
      return;
    }
    setSelectedCard(card);
    logBattleEvent("battle_card_selected", { cardId: card.id, cost: card.cost });
  }

  function dismissResult() {
    setResultDismissed(true);
  }

  return (
    <div className="battle-page">
      <section className="battle-stage">
        <div className="battle-topbar">
          <button
            className="ghost-btn"
            disabled={isResolving || isAnimating}
            onClick={handleStartBattle}
          >
            {match ? "Новый бой" : "Старт"}
          </button>
        </div>
        <div className={activeEvent?.target_id === "bot" ? "hero-line enemy hit" : "hero-line enemy"}>
          Герой врага · {bot?.hero.hp ?? 20} HP
        </div>
        {isResolving || isAnimating ? (
          <div className="resolve-banner" role="status">
            {isResolving ? "Сервер разыгрывает ход" : "Идёт ход"}
          </div>
        ) : null}
        <div className="board-wrap">
          <div
            aria-busy={isResolving || isAnimating}
            className={isResolving || isAnimating ? "board locked" : "board"}
          >
            {cells.map((cell) => {
              const position = cellPosition(cell);
              const unit = unitAt(position.row, position.col);
              const planned = plannedUnitAt(position.row, position.col);
              const shouldShowPlan = Boolean(planned && (!isAnimating || !unit));
              return (
                <button
                  className={cell >= 12 ? "board-cell spawn" : "board-cell"}
                  key={cell}
                  onClick={() => handleCellClick(cell)}
                >
                  {shouldShowPlan && planned ? (
                    <span className="planned-unit">
                      План
                      <strong>{shortCardName(planned.card_id)}</strong>
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
          <div
            className="unit-layer"
            style={layerStyle(ANIMATION_SPEED)}
          >
            {(match?.units ?? []).map((unit) => (
              <UnitToken
                acting={unit.id === activeEvent?.actor_id}
                dying={dyingIds.includes(unit.id)}
                key={unit.id}
                lunge={lunges.find((entry) => entry.unitId === unit.id) ?? null}
                rarity={cards.find((card) => card.id === unit.card_id)?.rarity ?? "common"}
                targeted={unit.id === activeEvent?.target_id}
                unit={unit}
              />
            ))}
            {popups.map((popup) => (
              <DamagePopupView key={popup.key} popup={popup} />
            ))}
          </div>
        </div>
        <div className={activeEvent?.target_id === "player" ? "hero-line hit" : "hero-line"}>
          Твой герой · {player?.hero.hp ?? 20} HP
        </div>
        <div className="mana-bar" aria-label="Мана">
          <div style={{ width: `${(availableMana / 10) * 100}%` }} />
          <span>Мана {availableMana}/10</span>
        </div>
      </section>

      <section className="battle-side">
        <div className="battle-hud">
          <div className={secondsLeft <= 5 && isTimerRunning ? "turn-timer warning" : "turn-timer"}>
            {isTimerRunning ? Math.min(TURN_SECONDS, secondsLeft) : TURN_SECONDS}
          </div>
          <div className="turn-plate">
            <strong>Ход {match?.turn ?? 1}</strong>
            <span>+{nextMana} маны дальше</span>
          </div>
        </div>
        <section className="hand compact-hand">
          {cards.map((card) => (
            <button
              className={selectedCard?.id === card.id ? "hand-card active" : "hand-card"}
              disabled={isResolving || isAnimating || isFinished}
              key={card.id}
              onClick={() => handleSelectCard(card)}
            >
              <Card card={card} />
            </button>
          ))}
        </section>
        <button disabled={!match || isResolving || isAnimating || isFinished} onClick={() => void handleResolve()}>
          {isResolving ? "Резолв..." : isAnimating ? "Идёт ход..." : "Завершить ход"}
        </button>
        <div className="battle-status">
          <span>{isAnimating ? "Идёт ход" : `План: ${placements.length}`}</span>
          <span>{realtimeStatus}</span>
          <span>{activeEvent?.message || battleMessage || "Выбери карту, затем нижнюю клетку."}</span>
        </div>
        {match?.log.length ? (
          <section className="battle-log">
            {match.log.slice(-6).map((entry, index) => (
              <p key={`${entry.message}-${index}`}>{entry.message}</p>
            ))}
          </section>
        ) : null}
      </section>
      {isFinished && !resultDismissed ? <ResultOverlay match={match} onClose={dismissResult} /> : null}
    </div>
  );
}

function layerStyle(speed: AnimationSpeed): React.CSSProperties {
  const { moveMs, strikeMs } = layerTimings(speed);
  return {
    ["--move-ms"]: `${moveMs}ms`,
    ["--strike-ms"]: `${strikeMs}ms`,
  } as React.CSSProperties;
}

function UnitToken({
  acting,
  dying,
  lunge,
  rarity,
  targeted,
  unit,
}: {
  acting: boolean;
  dying: boolean;
  lunge: LungeEffect | null;
  rarity: Rarity;
  targeted: boolean;
  unit: CombatUnit;
}) {
  const tokenStyle = {
    ["--col"]: unit.position.col,
    ["--row"]: unit.position.row,
  } as React.CSSProperties;
  // While striking, lift the attacker above the target so it reads as "on top".
  const tokenClasses = ["unit-token", dying ? "dying" : "", lunge ? "lunging" : ""]
    .filter(Boolean)
    .join(" ");
  // The strike target is fed to the keyframe via CSS vars (in % of one cell).
  const innerStyle = lunge
    ? ({ ["--lunge-x"]: `${lunge.dx}%`, ["--lunge-y"]: `${lunge.dy}%` } as React.CSSProperties)
    : undefined;
  return (
    <div className={tokenClasses} style={tokenStyle}>
      <div className={lunge ? "unit-token-inner striking" : "unit-token-inner"} style={innerStyle}>
        <UnitBadge active={acting} rarity={rarity} targeted={targeted} unit={unit} />
      </div>
    </div>
  );
}

function DamagePopupView({ popup }: { popup: DamagePopup }) {
  const style = { ["--col"]: popup.col, ["--row"]: popup.row } as React.CSSProperties;
  return (
    <span className={popup.kind === "hero" ? "damage-popup hero" : "damage-popup"} style={style}>
      <BurstIcon className="damage-burst" />
      <span className="damage-popup-text">-{popup.amount}</span>
    </span>
  );
}

function UnitBadge({
  active = false,
  rarity,
  targeted = false,
  unit,
}: {
  active?: boolean;
  rarity: Rarity;
  targeted?: boolean;
  unit: CombatUnit;
}) {
  const classes = [
    "unit-badge",
    unit.side === "bottom" ? "friendly" : "enemy",
    active ? "acting" : "",
    targeted ? "targeted" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={classes}>
      <CardArt cardId={unit.card_id} label={shortCardName(unit.card_id)} rarity={rarity} />
      <span className="unit-pip steps">
        <BootIcon />
        {unit.remaining_steps}
      </span>
      <span className="unit-pip attacks">
        <SwordIcon />
        {unit.remaining_attacks}
      </span>
      <span className="unit-pip damage">
        <BurstIcon />
        {unit.stats.damage}
      </span>
      <span className="unit-pip hp">
        <HeartIcon />
        {unit.current_hp}
      </span>
    </span>
  );
}

function ResultOverlay({ match, onClose }: { match: CombatMatch; onClose: () => void }) {
  const didWin = match.result.winner_id === "player";
  return (
    <div className="result-backdrop" onClick={onClose}>
      <section className="result-panel" onClick={(event) => event.stopPropagation()}>
        <strong>{didWin ? "Победа" : "Поражение"}</strong>
        <span>{didWin ? "Герой врага повержен." : "Твой герой пал."}</span>
        <b>+{match.result.reward_coins} монет</b>
        <button onClick={onClose}>Забрать</button>
      </section>
    </div>
  );
}
