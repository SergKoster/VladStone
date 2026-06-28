import { type CombatEvent, type CombatMatch } from "../../api";

export function applyEventSnapshot(
  currentMatch: CombatMatch,
  event: CombatEvent,
  finalMatch: CombatMatch,
): CombatMatch {
  return {
    ...currentMatch,
    players: event.snapshot.players ?? currentMatch.players,
    units: event.snapshot.units ?? currentMatch.units,
    log: [...currentMatch.log, { message: event.message }].slice(-24),
    result: event.type === "match_finished" ? finalMatch.result : currentMatch.result,
  };
}

export function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
