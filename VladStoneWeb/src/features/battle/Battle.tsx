import React from "react";

import {
  type CombatEvent,
  type CombatMatch,
  type CombatUnit,
  type CollectionCard,
  type Placement,
  getActiveCombats,
  getCombat,
  logClientEvent,
  resolveCombat,
  startCombat,
} from "../../api";
import { starterCards } from "../../shared/cards";
import { applyEventSnapshot, wait } from "./animationState";
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

export function Battle({ onBattleFinished }: { onBattleFinished: () => void }) {
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
  const [realtimeStatus, setRealtimeStatus] =
    React.useState<MatchRealtimeStatus>("Realtime не подключен");
  const isRealtimeBusyRef = React.useRef(false);

  const player = match?.players.find((candidate) => candidate.id === "player");
  const bot = match?.players.find((candidate) => candidate.id === "bot");
  const isFinished = match?.result.status === "finished";
  const playerMana = player?.mana ?? 0;
  const plannedCost = placements.reduce((sum, placement) => {
    const card = starterCards.find((candidate) => candidate.id === placement.card_id);
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

  async function playCombatEvents(finalMatch: CombatMatch) {
    const events = finalMatch.events ?? [];
    if (!events.length) {
      setMatch(finalMatch);
      setActiveEvent(null);
      return;
    }
    setIsAnimating(true);
    for (const event of events) {
      setActiveEvent(event);
      setBattleMessage(event.message);
      setMatch((current) => applyEventSnapshot(current ?? finalMatch, event, finalMatch));
      if (event.type === "spawn") {
        const spawnedUnit = event.snapshot.units?.find((unit) => unit.id === event.actor_id);
        if (spawnedUnit?.side === "bottom") {
          setPlacements((current) =>
            current.filter(
              (placement) =>
                placement.row !== spawnedUnit.position.row ||
                placement.col !== spawnedUnit.position.col,
            ),
          );
        }
      }
      await wait(620);
    }
    setMatch(finalMatch);
    setActiveEvent(null);
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
        <div className={activeEvent?.target_id === "bot" ? "hero-line enemy hit" : "hero-line enemy"}>
          Герой врага · {bot?.hero.hp ?? 20} HP
        </div>
        <div className="board">
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
                {unit ? (
                  <UnitBadge
                    active={unit.id === activeEvent?.actor_id}
                    targeted={unit.id === activeEvent?.target_id}
                    unit={unit}
                  />
                ) : null}
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
          <button disabled={isResolving || isAnimating} onClick={handleStartBattle}>
            Старт
          </button>
          <div className={secondsLeft <= 5 && isTimerRunning ? "turn-timer warning" : "turn-timer"}>
            {isTimerRunning ? secondsLeft : 30}
          </div>
          <div className="turn-plate">
            <strong>Ход {match?.turn ?? 1}</strong>
            <span>+{nextMana} маны дальше</span>
          </div>
        </div>
        <section className="hand compact-hand">
          {starterCards.map((card) => (
            <button
              className={selectedCard?.id === card.id ? "hand-card active" : "hand-card"}
              disabled={isResolving || isAnimating || isFinished}
              key={card.id}
              onClick={() => handleSelectCard(card)}
            >
              <strong>{shortCardName(card.id)}</strong>
              <span>{card.cost} маны</span>
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

function UnitBadge({
  active = false,
  targeted = false,
  unit,
}: {
  active?: boolean;
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
      <strong>{shortCardName(unit.card_id)}</strong>
      <span>У:{unit.stats.damage}</span>
      <span>ХП:{unit.current_hp}</span>
      <span>Ш:{unit.remaining_steps}</span>
      <span>А:{unit.remaining_attacks}</span>
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
