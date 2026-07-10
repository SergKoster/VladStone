import { type CombatMatch, type CombatEvent, type CombatUnit } from "../../api";

type SnapshotPlayers = NonNullable<CombatEvent["snapshot"]["players"]>;

/**
 * Within a single turn's replay, HP only ever decreases (no healing). Combat
 * events carry a snapshot captured *before* their batched damage is applied, so
 * a later event's snapshot can otherwise raise a unit's HP back up and make it
 * "jump". Clamping each snapshot's HP to the min of what's already shown keeps
 * HP monotonic; the precise drop at impact is applied separately (applyEventHp).
 */
function mergeUnitsHp(current: CombatUnit[], snapshot: CombatUnit[]): CombatUnit[] {
  const byId = new Map(current.map((unit) => [unit.id, unit]));
  const merged = snapshot.map((unit) => {
    const prev = byId.get(unit.id);
    return prev ? { ...unit, current_hp: Math.min(prev.current_hp, unit.current_hp) } : unit;
  });
  // Snapshots taken after damage was applied already exclude freshly dead
  // units, but their death event has not played yet — keep them on the board
  // so the death animation can run (the final state removes them at the end).
  const snapshotIds = new Set(snapshot.map((unit) => unit.id));
  current.forEach((unit) => {
    if (!snapshotIds.has(unit.id)) {
      merged.push(unit);
    }
  });
  return merged;
}

// Keyed off the CURRENT players (snapshot values only overlay hero HP and
// mana): snapshots carry no hand/deck/team fields, so replacing player objects
// wholesale would wipe the viewer's hand mid-animation.
export function mergePlayersHp(current: CombatMatch["players"], snapshot: SnapshotPlayers) {
  const byId = new Map(snapshot.map((player) => [player.id, player]));
  return current.map((player) => {
    const snap = byId.get(player.id);
    return snap
      ? {
          ...player,
          mana: snap.mana,
          hero: { ...player.hero, hp: Math.min(player.hero.hp, snap.hero.hp) },
        }
      : player;
  });
}

export function applyEventSnapshot(
  currentMatch: CombatMatch,
  event: CombatEvent,
  finalMatch: CombatMatch,
): CombatMatch {
  return {
    ...currentMatch,
    players: event.snapshot.players
      ? mergePlayersHp(currentMatch.players, event.snapshot.players)
      : currentMatch.players,
    units: event.snapshot.units
      ? mergeUnitsHp(currentMatch.units, event.snapshot.units)
      : currentMatch.units,
    log: [...currentMatch.log, { message: event.message }].slice(-24),
    result: event.type === "match_finished" ? finalMatch.result : currentMatch.result,
  };
}

/**
 * Apply a damaging event's exact post-hit HP to its target.
 *
 * The server emits attack/collision events with a snapshot captured *before*
 * damage is applied (damage is batched after all simultaneous hits), so the
 * snapshot alone shows stale HP. The event's `after_hp` is authoritative, so we
 * patch the target at the moment the hit lands, keeping HP in sync with the
 * strike animation.
 */
export function applyEventHp(match: CombatMatch, event: CombatEvent): CombatMatch {
  if (event.after_hp == null || !event.target_id) {
    return match;
  }
  if (event.target_kind === "hero") {
    return {
      ...match,
      players: match.players.map((player) =>
        player.id === event.target_id
          ? { ...player, hero: { ...player.hero, hp: event.after_hp! } }
          : player,
      ),
    };
  }
  if (event.target_kind === "unit") {
    return {
      ...match,
      units: match.units.map((unit) =>
        unit.id === event.target_id ? { ...unit, current_hp: event.after_hp! } : unit,
      ),
    };
  }
  return match;
}

export function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
