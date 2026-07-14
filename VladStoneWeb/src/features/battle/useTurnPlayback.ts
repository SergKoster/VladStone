import React from "react";

import { type CombatEvent, type CombatMatch } from "../../api";
import {
  INTER_ITERATION_PAUSE,
  INTRA_ITERATION_PAUSE,
  WATCHDOG_MS,
} from "./animationConfig";
import { applySnapshot, groupKey } from "./turnPlayback";

export function useTurnPlayback() {
  const [animatedMatch, setAnimatedMatch] = React.useState<CombatMatch | null>(null);
  const [activeEvent, setActiveEvent] = React.useState<CombatEvent | null>(null);
  const [isAnimating, setIsAnimating] = React.useState(false);
  const isPlayingRef = React.useRef(false);
  const generationRef = React.useRef(0);
  const watchdogRef = React.useRef<number | null>(null);

  const clearWatchdog = React.useCallback(() => {
    if (watchdogRef.current !== null) {
      window.clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
  }, []);

  const playTurn = React.useCallback(
    async (
      preMatch: CombatMatch,
      events: CombatEvent[],
      finalMatch: CombatMatch,
    ): Promise<void> => {
      // Синхронный замок: два источника результата не запускают корутины
      // поверх друг друга. Полный дедуп WS-эха остаётся в A6.
      if (isPlayingRef.current) return;
      isPlayingRef.current = true;
      const generation = ++generationRef.current;
      let current = preMatch;

      const settleOnFinal = () => {
        if (generationRef.current !== generation) return;
        generationRef.current += 1; // останавливает хвост текущей корутины
        clearWatchdog();
        isPlayingRef.current = false;
        setAnimatedMatch(finalMatch);
        setActiveEvent(null);
        setIsAnimating(false);
      };
      const armWatchdog = () => {
        clearWatchdog();
        watchdogRef.current = window.setTimeout(settleOnFinal, WATCHDOG_MS);
      };

      setAnimatedMatch(preMatch);
      setActiveEvent(null);
      setIsAnimating(true);
      armWatchdog();

      try {
        for (let index = 0; index < events.length; index += 1) {
          if (generationRef.current !== generation) return;
          const event = events[index];
          let next = applySnapshot(current, event.snapshot, finalMatch.units);
          if (event.type === "death" && event.actor_id) {
            next = {
              ...next,
              units: next.units.filter((unit) => unit.id !== event.actor_id),
            };
          }
          current = next;
          setAnimatedMatch(next);
          setActiveEvent(event);
          armWatchdog();

          const following = events[index + 1];
          if (!following) continue;
          const pauseMs =
            groupKey(following) === groupKey(event)
              ? INTRA_ITERATION_PAUSE
              : INTER_ITERATION_PAUSE;
          await pause(pauseMs);
        }
      } finally {
        settleOnFinal();
      }
    },
    [clearWatchdog],
  );

  React.useEffect(
    () => () => {
      generationRef.current += 1;
      isPlayingRef.current = false;
      clearWatchdog();
    },
    [clearWatchdog],
  );

  return { activeEvent, animatedMatch, isAnimating, playTurn };
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
