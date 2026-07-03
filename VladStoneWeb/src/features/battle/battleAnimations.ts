import React from "react";

import { type CombatEvent } from "../../api";

export type LungeEffect = { unitId: string; dx: number; dy: number };
export type DamagePopup = {
  key: number;
  row: number;
  col: number;
  amount: number;
  kind: "unit" | "hero";
};

const MELEE_TYPES = new Set(["attack", "collision", "collision_step", "hero_hit"]);
const COLLISION_TYPES = new Set(["collision", "collision_step"]);
// How far past the board edge a unit leaps when striking the enemy hero.
const HERO_OVERSHOOT = 45;
// How far past the board edge (in cells) to pop the damage burst on a hero.
const HERO_POPUP_OFFSET = 0.62;

export function isCollision(event: CombatEvent): boolean {
  return COLLISION_TYPES.has(event.type);
}

/** Melee events where the actor lunges toward a target (and is not a marker event). */
export function isMeleeLunge(event: CombatEvent): boolean {
  return MELEE_TYPES.has(event.type) && Boolean(event.actor_id);
}

function actorSide(event: CombatEvent): "top" | "bottom" | null {
  return event.snapshot.units?.find((unit) => unit.id === event.actor_id)?.side ?? null;
}

/**
 * Offset (in % of a cell) so the attacker jumps the full distance onto its
 * target — adjacent or several tiles away — landing right on top of it.
 */
export function computeLunge(event: CombatEvent): LungeEffect | null {
  if (!event.actor_id) {
    return null;
  }
  if (event.type === "hero_hit") {
    // Leap from the unit's row to the enemy hero just past the board edge.
    const from = event.from_position;
    const side = actorSide(event);
    if (!from || !side) {
      return null;
    }
    const edgeRow = side === "top" ? 4 : 0;
    const overshoot = side === "top" ? HERO_OVERSHOOT : -HERO_OVERSHOOT;
    return { unitId: event.actor_id, dx: 0, dy: (edgeRow - from.row) * 100 + overshoot };
  }
  const from = event.from_position;
  const to = event.to_position;
  if (!from || !to) {
    return null;
  }
  return {
    unitId: event.actor_id,
    dx: (to.col - from.col) * 100,
    dy: (to.row - from.row) * 100,
  };
}

/** Where to float the damage number for a damaging event, or null if none. */
export function damageLocation(event: CombatEvent): { row: number; col: number; kind: "unit" | "hero" } | null {
  if (!event.damage || event.damage <= 0) {
    return null;
  }
  if (event.type === "hero_hit") {
    const col = event.from_position?.col ?? 1;
    // Pop the burst on the hero itself (just past the board edge), not on the
    // tile in front of it. Enemy hero sits above row 0, player hero below row 4.
    const row = actorSide(event) === "top" ? 4 + HERO_POPUP_OFFSET : -HERO_POPUP_OFFSET;
    return { row, col, kind: "hero" };
  }
  const to = event.to_position;
  if (!to) {
    return null;
  }
  return { row: to.row, col: to.col, kind: "unit" };
}

/** Transient battle effects (lunge, floating damage, dying units) for the active turn. */
export function useBattleEffects() {
  // Multiple units can lunge at once (e.g. both sides of a collision).
  const [lunges, setLunges] = React.useState<LungeEffect[]>([]);
  const [popups, setPopups] = React.useState<DamagePopup[]>([]);
  const [dyingIds, setDyingIds] = React.useState<string[]>([]);
  const popupKey = React.useRef(0);

  const addPopup = React.useCallback(
    (popup: Omit<DamagePopup, "key">, ttlMs: number) => {
      const key = popupKey.current++;
      setPopups((current) => [...current, { ...popup, key }]);
      window.setTimeout(() => {
        setPopups((current) => current.filter((entry) => entry.key !== key));
      }, ttlMs);
    },
    [],
  );

  const markDying = React.useCallback((unitId: string) => {
    setDyingIds((current) => (current.includes(unitId) ? current : [...current, unitId]));
  }, []);

  const clearLunges = React.useCallback(() => setLunges([]), []);

  const reset = React.useCallback(() => {
    setLunges([]);
    setPopups([]);
    setDyingIds([]);
  }, []);

  return { lunges, setLunges, clearLunges, popups, addPopup, dyingIds, markDying, reset };
}
