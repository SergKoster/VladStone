import { type CombatEvent, type CombatMatch, type Placement } from "../../api";

export function withCombatEvents(match: CombatMatch, events: CombatEvent[]): CombatMatch {
  return {
    ...match,
    events,
  };
}

export function secondsFromDeadline(match: CombatMatch) {
  if (!match.planning_deadline || match.status !== "planning") {
    return 0;
  }
  return Math.max(0, Math.ceil((Date.parse(match.planning_deadline) - Date.now()) / 1000));
}

export function nextManaGain(currentTurn: number) {
  const nextTurn = currentTurn + 1;
  if (nextTurn % 10 === 0) {
    return 3;
  }
  if (nextTurn % 3 === 0) {
    return 2;
  }
  return 1;
}

const SHORT_CARD_NAMES: Record<string, string> = {
  test_bruiser: "Толстяк",
  test_ranger: "Дальник",
  banka: "Банка",
  dolbiki: "Долбики",
  matesha: "Матеша",
  matesha_plus: "Матеша+",
  zadanie: "Задание",
};

export function shortCardName(cardId: string) {
  return SHORT_CARD_NAMES[cardId] ?? cardId;
}

export function battleSnapshot(
  match: CombatMatch | null,
  placements: Placement[],
  extra: Record<string, unknown> = {},
) {
  const player = match?.players.find((candidate) => candidate.id === match.viewer_id);
  const enemy = match?.players.find(
    (candidate) => player && candidate.team !== player.team,
  );
  return {
    turn: match?.turn ?? null,
    playerMana: player?.mana ?? null,
    botMana: enemy?.mana ?? null,
    playerHeroHp: player?.hero.hp ?? null,
    botHeroHp: enemy?.hero.hp ?? null,
    placements,
    units:
      match?.units.map((unit) => ({
        id: unit.id,
        cardId: unit.card_id,
        side: unit.side,
        row: unit.position.row,
        col: unit.position.col,
        hp: unit.current_hp,
        steps: unit.remaining_steps,
        attacks: unit.remaining_attacks,
      })) ?? [],
    logTail: match?.log.slice(-8).map((entry) => entry.message) ?? [],
    ...extra,
  };
}
