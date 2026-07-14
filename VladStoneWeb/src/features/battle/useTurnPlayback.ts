import React from "react";

import { type CombatEvent, type CombatMatch } from "../../api";
import {
  AREA_PULSE_MS,
  DEATH_FADE_MS,
  INTER_ITERATION_PAUSE,
  INTRA_ITERATION_PAUSE,
  LUNGE_IMPACT_MS,
  LUNGE_MS,
  MOVE_MS,
  POPUP_TTL_MS,
  SPAWN_MS,
  WATCHDOG_MS,
} from "./animationConfig";
import {
  type BattlePopup,
  type CellPulse,
  type LungeEffect,
  lungeEffects,
  popupForEvent,
} from "./battleAnimations";
import { applyEventSnapshot, groupKey } from "./turnPlayback";

export function useTurnPlayback() {
  const [animatedMatch, setAnimatedMatch] = React.useState<CombatMatch | null>(null);
  const [activeEvent, setActiveEvent] = React.useState<CombatEvent | null>(null);
  const [isAnimating, setIsAnimating] = React.useState(false);
  const [lunges, setLunges] = React.useState<LungeEffect[]>([]);
  const [popups, setPopups] = React.useState<BattlePopup[]>([]);
  const [cellPulses, setCellPulses] = React.useState<CellPulse[]>([]);
  const [dyingIds, setDyingIds] = React.useState<string[]>([]);
  const [spawningIds, setSpawningIds] = React.useState<string[]>([]);
  const isPlayingRef = React.useRef(false);
  const generationRef = React.useRef(0);
  const watchdogRef = React.useRef<number | null>(null);
  const effectKeyRef = React.useRef(0);
  const effectTimersRef = React.useRef<number[]>([]);

  const clearWatchdog = React.useCallback(() => {
    if (watchdogRef.current !== null) {
      window.clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
  }, []);

  const clearEffectTimers = React.useCallback(() => {
    effectTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    effectTimersRef.current = [];
  }, []);

  const resetEffects = React.useCallback(() => {
    clearEffectTimers();
    setLunges([]);
    setPopups([]);
    setCellPulses([]);
    setDyingIds([]);
    setSpawningIds([]);
  }, [clearEffectTimers]);

  const scheduleEffect = React.useCallback((callback: () => void, ms: number) => {
    const timer = window.setTimeout(() => {
      effectTimersRef.current = effectTimersRef.current.filter((id) => id !== timer);
      callback();
    }, ms);
    effectTimersRef.current.push(timer);
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
        setLunges([]);
        setDyingIds([]);
        setSpawningIds([]);
        setIsAnimating(false);
      };
      const armWatchdog = () => {
        clearWatchdog();
        watchdogRef.current = window.setTimeout(settleOnFinal, WATCHDOG_MS);
      };

      resetEffects();
      setAnimatedMatch(preMatch);
      setActiveEvent(null);
      setIsAnimating(true);
      armWatchdog();

      try {
        for (let index = 0; index < events.length; index += 1) {
          if (generationRef.current !== generation) return;
          const event = events[index];
          setActiveEvent(event);
          armWatchdog();

          if (event.affected_cells.length > 0) {
            const pulseKey = ++effectKeyRef.current;
            const pulses = event.affected_cells.map((cell, cellIndex) => ({
              key: pulseKey * 1_000 + cellIndex,
              row: cell.row,
              col: cell.col,
            }));
            setCellPulses((existing) => [...existing, ...pulses]);
            scheduleEffect(
              () =>
                setCellPulses((existing) =>
                  existing.filter((pulse) => !pulses.some((added) => added.key === pulse.key)),
                ),
              AREA_PULSE_MS,
            );
          }

          const eventLunges = lungeEffects(event, current);
          if (eventLunges.length > 0) {
            setLunges(eventLunges);
            await pause(LUNGE_IMPACT_MS);
          }

          const before = current;
          current = applyEventSnapshot(current, event, finalMatch.units);
          setAnimatedMatch(current);

          const popup = popupForEvent(event, before, ++effectKeyRef.current);
          if (popup) {
            setPopups((existing) => [...existing, popup]);
            scheduleEffect(
              () => setPopups((existing) => existing.filter((item) => item.key !== popup.key)),
              POPUP_TTL_MS,
            );
          }

          // У коллизии сервер сначала сообщает саму встречу, затем два
          // damage-события той же итерации. Применяем оба на пике общего
          // выпада, иначе числа HP запаздывают до возврата токенов на места.
          if (event.type === "collision") {
            const participants = new Set([event.actor_id, event.target_id]);
            while (index + 1 < events.length) {
              const impactEvent = events[index + 1];
              if (
                impactEvent.type !== "damage" ||
                groupKey(impactEvent) !== groupKey(event) ||
                !participants.has(impactEvent.target_id)
              ) {
                break;
              }
              index += 1;
              const beforeImpact = current;
              current = applyEventSnapshot(current, impactEvent, finalMatch.units);
              setAnimatedMatch(current);
              const impactPopup = popupForEvent(
                impactEvent,
                beforeImpact,
                ++effectKeyRef.current,
              );
              if (impactPopup) {
                setPopups((existing) => [...existing, impactPopup]);
                scheduleEffect(
                  () =>
                    setPopups((existing) =>
                      existing.filter((item) => item.key !== impactPopup.key),
                    ),
                  POPUP_TTL_MS,
                );
              }
            }
          }

          if (eventLunges.length > 0) {
            await pause(Math.max(0, LUNGE_MS - LUNGE_IMPACT_MS));
            setLunges([]);
          } else if (event.type === "move" || event.type === "push") {
            await pause(MOVE_MS);
          }

          if (event.type === "spawn" && event.actor_id) {
            const unitId = event.actor_id;
            setSpawningIds((existing) => [...new Set([...existing, unitId])]);
            scheduleEffect(
              () => setSpawningIds((existing) => existing.filter((id) => id !== unitId)),
              SPAWN_MS,
            );
          }

          if (event.type === "death" && event.actor_id) {
            const unitId = event.actor_id;
            setDyingIds((existing) => [...new Set([...existing, unitId])]);
            await pause(DEATH_FADE_MS);
            current = {
              ...current,
              units: current.units.filter((unit) => unit.id !== unitId),
            };
            setAnimatedMatch(current);
            setDyingIds((existing) => existing.filter((id) => id !== unitId));
          }

          const following = events[index + 1];
          const pauseMs =
            following && groupKey(following) === groupKey(event)
              ? INTRA_ITERATION_PAUSE
              : INTER_ITERATION_PAUSE;
          // Пауза обязательна и после последнего события. Без await React
          // объединяет обновление последнего кадра с settleOnFinal(), поэтому
          // короткий ход (а иногда и весь ход из одного события) визуально
          // перескакивает прямо в финальное состояние.
          await pause(pauseMs);
        }
      } finally {
        settleOnFinal();
      }
    },
    [clearWatchdog, resetEffects, scheduleEffect],
  );

  React.useEffect(
    () => () => {
      generationRef.current += 1;
      isPlayingRef.current = false;
      clearWatchdog();
      clearEffectTimers();
    },
    [clearEffectTimers, clearWatchdog],
  );

  return {
    activeEvent,
    animatedMatch,
    cellPulses,
    dyingIds,
    isAnimating,
    lunges,
    playTurn,
    popups,
    spawningIds,
  };
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
