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
  ANIMATION_WATCHDOG_MS,
  STRIKE_IMPACT,
  durationFor,
  interIterationPauseFor,
  intraIterationPauseFor,
  layerTimings,
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

// Label for the resolve-phase overlay ("итерация N"). micro_step 0 is the setup
// spawns of the turn; 1..N are the unit micro-turns. v4 will add spell/end phases
// via an event `phase` field (COMBAT_REWORK §18.3) — extend here when it lands.
function iterationLabel(step: number | null): string {
  if (step === null || step <= 0) {
    return "Появление воинов";
  }
  return `Итерация ${step}`;
}

// Board cell index under a viewport point, or null. Used for drag-and-drop drops;
// the drag ghost is pointer-events:none, so it never shadows the cell here.
function cellUnderPoint(x: number, y: number): number | null {
  const el = document.elementFromPoint(x, y);
  const cell = el?.closest?.(".board-cell") as HTMLElement | null;
  if (!cell || cell.dataset.cell == null) {
    return null;
  }
  return Number(cell.dataset.cell);
}

// Pixels the pointer must travel before a hand-card press becomes a drag (below
// this it stays a tap that selects the card).
const DRAG_THRESHOLD = 6;

export function Battle({
  cards,
  onBattleFinished,
}: {
  cards: CollectionCard[];
  onBattleFinished: () => void;
}) {
  const cells = Array.from({ length: 15 }, (_, index) => index);
  const [match, setMatch] = React.useState<CombatMatch | null>(null);
  // Always-current mirror of `match`: the realtime callback is a closure that
  // captures a stale `match`, so it reads the live turn through this ref instead.
  const matchRef = React.useRef<CombatMatch | null>(null);
  matchRef.current = match;
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
  // Resolve-phase overlay ("итерация N"): step = micro_step being played, visible
  // toggles the fade. Purely derived from the event stream — no server data
  // beyond micro_step (COMBAT_REWORK §18.3).
  const [iterationStep, setIterationStep] = React.useState<number | null>(null);
  const [iterationVisible, setIterationVisible] = React.useState(false);
  // Drag-and-drop placement: dragStartRef tracks the in-flight pointer drag (mouse
  // or touch); dragGhost drives the floating card preview and drop highlight.
  // suppressClickRef swallows the click that a browser fires after a drag release.
  const dragStartRef = React.useRef<{
    card: CollectionCard;
    startX: number;
    startY: number;
    active: boolean;
  } | null>(null);
  const suppressClickRef = React.useRef(false);
  const [dragGhost, setDragGhost] = React.useState<{
    x: number;
    y: number;
    cell: number | null;
    valid: boolean;
    name: string;
  } | null>(null);
  const [realtimeStatus, setRealtimeStatus] =
    React.useState<MatchRealtimeStatus>("Realtime не подключен");
  const isRealtimeBusyRef = React.useRef(false);

  const player = match?.players.find((candidate) => candidate.id === "player");
  const bot = match?.players.find((candidate) => candidate.id === "bot");
  // "expired" is terminal too (server closed the match, e.g. ruleset changed):
  // the battle locks and the result overlay explains — it is not a loss.
  const isFinished =
    match?.result.status === "finished" || match?.result.status === "expired";
  const playerMana = player?.mana ?? 0;
  const plannedCost = placements.reduce((sum, placement) => {
    const card = cards.find((candidate) => candidate.id === placement.card_id);
    return sum + (card?.cost ?? 0);
  }, 0);
  const availableMana = Math.max(0, playerMana - plannedCost);
  const nextMana = nextManaGain(match?.turn ?? 1);

  // The hand is server-authoritative (deck cycle). Planned placements consume
  // hand entries locally so a card cannot be planned twice.
  const handEntries = React.useMemo(() => {
    const plannedLeft: Record<string, number> = {};
    placements.forEach((placement) => {
      plannedLeft[placement.card_id] = (plannedLeft[placement.card_id] ?? 0) + 1;
    });
    return (match?.player_hand ?? []).map((cardId, index) => {
      const card = cards.find((candidate) => candidate.id === cardId) ?? null;
      let planned = false;
      if ((plannedLeft[cardId] ?? 0) > 0) {
        plannedLeft[cardId] -= 1;
        planned = true;
      }
      return { key: `${cardId}-${index}`, cardId, card, planned };
    });
  }, [cards, match?.player_hand, placements]);

  const deckCount = match?.deck_count ?? 0;

  // Draw animation: when the turn advances, the freshly drawn card (the hand's
  // last entry — the server appends draws) flies in from the deck stack.
  const [drawnKey, setDrawnKey] = React.useState<string | null>(null);
  const prevTurnRef = React.useRef(0);
  React.useEffect(() => {
    const turn = match?.turn ?? 0;
    const hand = match?.player_hand ?? [];
    // Any forward jump counts (the server may resolve turns by timer while the
    // client is away); a fresh mount (prev 0) does not animate.
    const isNextTurn = prevTurnRef.current > 0 && turn > prevTurnRef.current;
    prevTurnRef.current = turn;
    if (isNextTurn && hand.length > 0) {
      setDrawnKey(`${hand[hand.length - 1]}-${hand.length - 1}`);
      const timerId = window.setTimeout(() => setDrawnKey(null), 700);
      return () => window.clearTimeout(timerId);
    }
    return undefined;
  }, [match?.turn, match?.player_hand]);

  // Transient warnings shown right on the clicked cell (fade up and out).
  const [cellNotices, setCellNotices] = React.useState<
    Array<{ key: number; row: number; col: number; text: string }>
  >([]);
  const noticeKeyRef = React.useRef(0);
  const showCellNotice = React.useCallback(
    (position: { row: number; col: number }, text: string) => {
      const key = noticeKeyRef.current++;
      setCellNotices((current) => [...current, { key, ...position, text }]);
      window.setTimeout(() => {
        setCellNotices((current) => current.filter((notice) => notice.key !== key));
      }, 1100);
    },
    [],
  );

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
      setIsTimerRunning(resolvedMatch.result.status === "active");
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

  // One auto-submit attempt per turn: the ref survives re-renders, so the
  // 1s -> 0s tick does not fire a duplicate resolve while the first is in flight.
  const autoSubmitTurnRef = React.useRef<number | null>(null);
  // The state the current animation is playing towards; the watchdog lands on
  // it when the animation pipeline hangs instead of finishing.
  const latestFinalMatchRef = React.useRef<CombatMatch | null>(null);
  // True while a turn is being animated. A synchronous guard (a ref, not state)
  // so overlapping calls are rejected in the same tick — state/effect lag would
  // let a second run slip through and fight the first over the board.
  const isPlayingRef = React.useRef(false);
  // Generation token for the active playback run. The watchdog (or a superseding
  // run) bumps it; the running loop checks it after every await and bails without
  // touching the board — otherwise a loop the watchdog already force-finished
  // would wake up and replay its tail on top of the final state (looks like the
  // turn playing twice).
  const playGenRef = React.useRef(0);

  // Watchdog: a hung animation would freeze the battle in "Идёт ход" forever —
  // the turn timer stops and realtime updates get dropped as "busy", so there
  // is no other way out. If no animation event progresses for the whole cap,
  // force-finish and report which event stalled (battle_animation_watchdog in
  // telemetry) so freezes identify themselves in the dev logs.
  React.useEffect(() => {
    if (!isAnimating) {
      return undefined;
    }
    const watchdogId = window.setTimeout(() => {
      logClientEvent(
        "battle_animation_watchdog",
        battleSnapshot(latestFinalMatchRef.current ?? match, [], {
          stalledEventType: activeEvent?.type ?? null,
          stalledEventSequence: activeEvent?.sequence ?? null,
        }),
      );
      // Invalidate the in-flight loop so it cannot resume and replay its tail on
      // top of the final state we are about to set.
      playGenRef.current += 1;
      if (latestFinalMatchRef.current) {
        setMatch(latestFinalMatchRef.current);
      }
      setActiveEvent(null);
      resetEffects();
      setIsAnimating(false);
      // Release the re-entrancy guard too, or every later turn would be rejected
      // as "already playing" and animations would soft-lock for the rest of the match.
      isPlayingRef.current = false;
      setBattleMessage("Анимация зависла — показан итог хода.");
    }, ANIMATION_WATCHDOG_MS);
    return () => window.clearTimeout(watchdogId);
    // activeEvent in deps restarts the countdown on every played event, so the
    // watchdog only fires when the pipeline makes no progress at all.
  }, [activeEvent, isAnimating]);

  // Fade the iteration overlay out the moment playback settles — whether the loop
  // finished, the watchdog force-finished, or reduced motion skipped it, all land
  // on isAnimating=false. Keep iterationStep so the last label fades, not blanks.
  React.useEffect(() => {
    if (!isAnimating) {
      setIterationVisible(false);
    }
  }, [isAnimating]);

  React.useEffect(() => {
    if (!isTimerRunning || !match || isFinished) {
      return;
    }
    // <= 2, not <= 1: the countdown is ceil()-ed, so a displayed "1" can mean
    // mere milliseconds remain and the server may win the race (verified live:
    // submitting at "1" got a 409). "2" guarantees at least a full second.
    const shouldAutoSubmit =
      secondsLeft <= 2 &&
      placements.length > 0 &&
      !isResolving &&
      !isAnimating &&
      autoSubmitTurnRef.current !== match.turn;
    if (shouldAutoSubmit) {
      // The player staged placements but never pressed "resolve": submit them
      // before the server resolves the expired turn as an empty one and the
      // staged plan is silently lost (PLAYTEST_NOTES item 2).
      autoSubmitTurnRef.current = match.turn;
      logBattleEvent("battle_timer_autosubmit");
      setBattleMessage("Время вышло — отправляю твою расстановку.");
      void handleResolve();
      return;
    }
    if (secondsLeft === 0) {
      logBattleEvent("battle_timer_zero");
      setBattleMessage("Время вышло. Сервер разыгрывает ход.");
    }
  }, [
    handleResolve,
    isAnimating,
    isFinished,
    isResolving,
    isTimerRunning,
    match,
    placements,
    secondsLeft,
  ]);

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
    // The resolve route also broadcasts the turn it just resolved. The client that
    // initiated the resolve already animated it from the HTTP response, so a
    // broadcast for a state we already show would replay the whole turn (collisions
    // included) a second time. Skip the echo of our own resolve — keyed on
    // (turn, result.status), because a finishing turn does not bump the turn number,
    // so an away client must still be able to animate the finish.
    const shown = matchRef.current;
    const shownTurn = shown?.turn ?? 0;
    const shownStatus = shown?.result.status ?? "active";
    const isEcho =
      resolvedMatch.turn < shownTurn ||
      (resolvedMatch.turn === shownTurn && resolvedMatch.result.status === shownStatus);
    if (isEcho) {
      logClientEvent(
        "battle_realtime_duplicate",
        battleSnapshot(resolvedMatch, [], { shownTurn, shownStatus }),
      );
      return;
    }
    logClientEvent("battle_realtime_update", battleSnapshot(resolvedMatch, placements));
    await playCombatEvents(resolvedMatch);
    setPlacements([]);
    setSelectedCard(null);
    setSecondsLeft(secondsFromDeadline(resolvedMatch));
    setIsTimerRunning(resolvedMatch.result.status === "active");
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
    isCancelled: () => boolean,
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
    // If the run was force-finished mid-strike, stop before mutating the board —
    // the final state is already on screen; replaying the hit would double it.
    if (isCancelled()) {
      return;
    }
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

    // Re-entrancy guard: the resolve button and realtime pushes can each try to
    // play a turn, and the busy ref that gates realtime lags React state by one
    // effect tick — so two runs can overlap, fight over the board, and leave
    // isAnimating stuck true. A call arriving mid-animation only records the
    // newest final state (the running finally lands on it) and returns.
    latestFinalMatchRef.current = finalMatch;
    if (isPlayingRef.current) {
      return;
    }
    isPlayingRef.current = true;
    // Claim this run's generation; if the watchdog (or a superseding run) bumps it,
    // `cancelled()` turns true and the loop bails after its next await.
    const myGen = (playGenRef.current += 1);
    const cancelled = () => playGenRef.current !== myGen;
    // Mark busy synchronously (not via the effect) so a realtime push arriving
    // before the effect commits cannot enter and start a second, overlapping run.
    isRealtimeBusyRef.current = true;

    const speed = ANIMATION_SPEED;
    setIsAnimating(true);

    try {
      // Fallback for debug/reduced motion: jump straight to the resolved state.
      if (speed === "off" || prefersReducedMotion()) {
        events.forEach(dropSpawnedPlacement);
        return;
      }

      const intraPause = intraIterationPauseFor(speed);
      const interPause = interIterationPauseFor(speed);
      // Show the resolve overlay on the first iteration; settleAfter() flips it to
      // the next iteration inside the inter-iteration gap below.
      setIterationStep(events[0].micro_step ?? 0);
      setIterationVisible(true);
      // Pause after the event(s) just played: short within one resolver iteration,
      // long when the next event crosses into the next iteration (micro_step
      // changes) so each micro-turn reads as its own beat (COMBAT_REWORK §18.3).
      // Crossing a boundary also flips the overlay to the new iteration during that
      // longer gap — one gap, not a stack of pauses. `index` already points at the
      // next unplayed event when this is called.
      const settleAfter = async (playedStep: number | null): Promise<void> => {
        const next = events[index];
        if (!next) {
          return;
        }
        if (next.micro_step === playedStep) {
          await wait(intraPause);
          return;
        }
        setIterationStep(next.micro_step ?? playedStep);
        await wait(interPause);
      };
      let index = 0;
      while (index < events.length) {
        // Bail before any board mutation if this run was force-finished/superseded.
        if (cancelled()) {
          return;
        }
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
          // Forward-progress guard: if nothing clustered (e.g. a collision event
          // with no to_position), `index` would never advance and this loop would
          // spin forever, never releasing isAnimating. Fall through to the generic
          // handlers below, which always consume exactly one event.
          if (group.length > 0) {
            await playLunge(
              group.filter((entry) => entry.actor_id),
              group[group.length - 1],
              finalMatch,
              cancelled,
            );
            await settleAfter(event.micro_step);
            continue;
          }
        }

        // Melee/ranged strike: keep the board as-is until the attacker lands, then
        // playLunge applies the hit (HP) in sync with the animation.
        if (isMeleeLunge(event)) {
          await playLunge([event], event, finalMatch, cancelled);
          index += 1;
          await settleAfter(event.micro_step);
          continue;
        }

        applyEventToBoard(event, finalMatch);
        await wait(durationFor(event.type, speed));
        index += 1;
        await settleAfter(event.micro_step);
      }
    } catch (error) {
      logClientEvent(
        "battle_animation_error",
        battleSnapshot(finalMatch, [], { error: String(error) }),
      );
    } finally {
      // Only the current run settles the UI. If we were superseded (watchdog or a
      // newer turn), that owner already set the final state and flags — a stale
      // run touching them here would clobber the newer turn.
      if (!cancelled()) {
        // Whatever happened above — finished, threw, or was cut short — the
        // battle must never stay locked in "Идёт ход": land on the authoritative
        // final state (the newest one if a push arrived mid-animation) and unlock
        // the UI (timer, hand, resolve button).
        setMatch(latestFinalMatchRef.current ?? finalMatch);
        setActiveEvent(null);
        resetEffects();
        setIsAnimating(false);
        isPlayingRef.current = false;
      }
    }
    if (!cancelled() && finalMatch.result.status === "finished") {
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
      showCellNotice(position, "Сначала выбери карту в руке");
      return;
    }
    placeCardOnCell(selectedCard, cell);
  }

  // Whether `card` can be planned onto `cell` right now — the same checks as
  // placeCardOnCell but side-effect-free, for drag-target highlighting.
  function canPlaceCard(card: CollectionCard, cell: number): boolean {
    if (isResolving || isAnimating || isFinished) {
      return false;
    }
    const position = cellPosition(cell);
    if (position.row !== 4 || plannedUnitAt(position.row, position.col)) {
      return false;
    }
    const existingUnit = unitAt(position.row, position.col);
    if (existingUnit?.side === "bottom") {
      return false;
    }
    if (existingUnit?.side === "top" && unitAt(position.row - 1, position.col)) {
      return false;
    }
    return availableMana >= card.cost;
  }

  // Validate and add a placement. Shared by click-to-place and drag-and-drop;
  // shows a cell notice and returns false when the spot is not legal.
  function placeCardOnCell(card: CollectionCard, cell: number): boolean {
    const position = cellPosition(cell);
    if (plannedUnitAt(position.row, position.col)) {
      showCellNotice(position, "Клетка уже в плане");
      return false;
    }
    if (position.row !== 4) {
      logBattleEvent("battle_cell_rejected", { reason: "not_spawn_row", position });
      showCellNotice(position, "Ставить можно только на ближайший ряд");
      return false;
    }
    const existingUnit = unitAt(position.row, position.col);
    if (existingUnit?.side === "bottom") {
      logBattleEvent("battle_cell_rejected", { reason: "occupied", position });
      showCellNotice(position, "Клетка уже занята");
      return false;
    }
    if (existingUnit?.side === "top" && unitAt(position.row - 1, position.col)) {
      logBattleEvent("battle_cell_rejected", {
        reason: "blocked_push_target",
        position,
        displacedUnitId: existingUnit.id,
      });
      showCellNotice(position, "Некуда вытолкнуть: клетка за врагом занята");
      return false;
    }
    if (availableMana < card.cost) {
      logBattleEvent("battle_cell_rejected", {
        reason: "not_enough_mana",
        position,
        selectedCardId: card.id,
        availableMana,
      });
      showCellNotice(position, "Не хватает маны");
      return false;
    }
    const nextPlacements = [...placements, { card_id: card.id, ...position }];
    setPlacements(nextPlacements);
    // The planned card is consumed from the hand until the plan is cancelled.
    setSelectedCard(null);
    logClientEvent(
      "battle_plan_added",
      battleSnapshot(match, nextPlacements, {
        added: { card_id: card.id, ...position },
        displacedUnitId: existingUnit?.id ?? null,
        availableManaAfterPlan: availableMana - card.cost,
      }),
    );
    setBattleMessage(
      existingUnit
        ? `${card.name} выталкивает ${shortCardName(existingUnit.card_id)}.`
        : `${card.name} готовится выйти на поле.`,
    );
    return true;
  }

  function handleSelectCard(card: CollectionCard) {
    if (isResolving || isAnimating || isFinished) {
      return;
    }
    setSelectedCard(card);
    logBattleEvent("battle_card_selected", { cardId: card.id, cost: card.cost });
  }

  // --- Drag-and-drop placement (pointer events: one path for mouse and touch) ---

  function handleCardPointerDown(event: React.PointerEvent, card: CollectionCard) {
    if (isResolving || isAnimating || isFinished) {
      return;
    }
    suppressClickRef.current = false;
    dragStartRef.current = { card, startX: event.clientX, startY: event.clientY, active: false };
    // Keep receiving move/up on this button even after the pointer leaves it.
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // Not fatal: some environments reject capture on synthetic/edge pointers.
    }
  }

  function handleCardPointerMove(event: React.PointerEvent) {
    const start = dragStartRef.current;
    if (!start) {
      return;
    }
    if (!start.active) {
      if (Math.hypot(event.clientX - start.startX, event.clientY - start.startY) < DRAG_THRESHOLD) {
        return;
      }
      // Cross the threshold → this is a drag: reflect selection and show the ghost.
      start.active = true;
      setSelectedCard(start.card);
    }
    const cell = cellUnderPoint(event.clientX, event.clientY);
    setDragGhost({
      x: event.clientX,
      y: event.clientY,
      cell,
      valid: cell != null && canPlaceCard(start.card, cell),
      name: start.card.name,
    });
  }

  function handleCardPointerUp(event: React.PointerEvent) {
    const start = dragStartRef.current;
    dragStartRef.current = null;
    setDragGhost(null);
    if (!start || !start.active) {
      // A tap, not a drag — let the button's onClick select the card.
      return;
    }
    // A real drag ended: swallow the trailing click and drop onto the cell (if any).
    suppressClickRef.current = true;
    const cell = cellUnderPoint(event.clientX, event.clientY);
    if (cell != null) {
      placeCardOnCell(start.card, cell);
    }
  }

  function dismissResult() {
    setResultDismissed(true);
  }

  return (
    <div className="battle-page">
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
        {iterationVisible ? (
          // While events actually play, the banner slot shows the current iteration
          // / phase ("итерация N") — takes priority over the generic labels below
          // (isResolving stays true through playback). Sits above the board, so it
          // never covers a unit; the keyed span pops on each change (§18.3).
          <div className="iteration-overlay" role="status">
            <span key={iterationStep ?? "none"}>{iterationLabel(iterationStep)}</span>
          </div>
        ) : isResolving ? (
          <div className="resolve-banner" role="status">
            Сервер разыгрывает ход
          </div>
        ) : isAnimating ? (
          <div className="resolve-banner" role="status">
            Идёт ход
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
                  className={[
                    cell >= 12 ? "board-cell spawn" : "board-cell",
                    dragGhost && dragGhost.cell === cell
                      ? dragGhost.valid
                        ? "drop-ok"
                        : "drop-bad"
                      : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  data-cell={cell}
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
            {/* Render in a stable order (by id), NOT the match.units array order.
                At a collision impact the dying units (the ones mid-strike) get
                moved to the end of match.units by mergeUnitsHp — that reorders
                their DOM nodes while the strike keyframe is running, which can
                restart the animation and make the collision "flash twice". A
                position-independent key order keeps each token's DOM slot fixed;
                stacking during a lunge is handled by .lunging { z-index }. */}
            {[...(match?.units ?? [])]
              .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
              .map((unit) => (
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
            {cellNotices.map((notice) => (
              <span
                className="cell-notice"
                key={notice.key}
                style={{ ["--col"]: notice.col, ["--row"]: notice.row } as React.CSSProperties}
              >
                <span>{notice.text}</span>
              </span>
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
          {handEntries.map((entry) =>
            entry.card ? (
              <button
                className={[
                  "hand-card",
                  selectedCard?.id === entry.cardId && !entry.planned ? "active" : "",
                  entry.planned ? "planned" : "",
                  entry.key === drawnKey ? "drawn" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                disabled={isResolving || isAnimating || isFinished || entry.planned}
                key={entry.key}
                onClick={() => {
                  // Swallow the click that follows a drag; taps fall through to select.
                  if (suppressClickRef.current) {
                    suppressClickRef.current = false;
                    return;
                  }
                  handleSelectCard(entry.card!);
                }}
                onPointerDown={(event) => handleCardPointerDown(event, entry.card!)}
                onPointerMove={handleCardPointerMove}
                onPointerUp={handleCardPointerUp}
              >
                <Card card={entry.card} />
              </button>
            ) : null,
          )}
          {match ? (
            <div
              aria-label={`Карт в колоде: ${deckCount}`}
              className={deckCount > 0 ? "deck-stack" : "deck-stack empty"}
              title="Карт в колоде"
            >
              <strong>{deckCount}</strong>
              <span>колода</span>
            </div>
          ) : (
            <p className="hand-hint">Нажми «Старт», чтобы получить руку из колоды.</p>
          )}
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
  // Server closed the match without an outcome (ruleset changed between
  // deploys) — neither a win nor a loss, no reward line.
  if (match.result.status === "expired") {
    return (
      <div className="result-backdrop" onClick={onClose}>
        <section className="result-panel" onClick={(event) => event.stopPropagation()}>
          <strong>Матч завершён</strong>
          <span>Правила боя обновились — начни новый бой.</span>
          <button onClick={onClose}>Понятно</button>
        </section>
      </div>
    );
  }
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
