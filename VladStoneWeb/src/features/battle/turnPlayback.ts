import {
  type CombatEvent,
  type CombatEventSnapshot,
  type CombatMatch,
  type CombatSnapshotUnit,
  type CombatUnit,
} from "../../api";

/** Наложить облегчённый снапшот события на полное состояние матча. */
export function applySnapshot(
  match: CombatMatch,
  snapshot: CombatEventSnapshot,
  fallbackUnits: CombatUnit[] = [],
): CombatMatch {
  const manaByPlayer = new Map(snapshot.players.map((player) => [player.id, player.mana]));
  const currentUnits = new Map(match.units.map((unit) => [unit.id, unit]));
  const fallbackById = new Map(fallbackUnits.map((unit) => [unit.id, unit]));
  const snapshotIds = new Set(snapshot.units.map((unit) => unit.id));

  const unitsFromSnapshot = snapshot.units.map((unit) =>
    mergeSnapshotUnit(
      unit,
      currentUnits.get(unit.id) ?? fallbackById.get(unit.id),
      match,
    ),
  );
  // Отсутствие в A1-снапшоте означает «не жив на момент события», но токен
  // остаётся на доске до отдельного death-события, чтобы исчезновение не
  // опережало серверную последовательность.
  const retainedUnits = match.units.filter((unit) => !snapshotIds.has(unit.id));

  return {
    ...match,
    players: match.players.map((player) => ({
      ...player,
      mana: manaByPlayer.get(player.id) ?? player.mana,
    })),
    units: [...unitsFromSnapshot, ...retainedUnits].sort(compareUnitIds),
  };
}

function compareUnitIds(a: CombatUnit, b: CombatUnit): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** Ключ визуальной группы: фаза + номер итерации. */
export function groupKey(event: CombatEvent): string {
  return `${event.phase}:${event.micro_step}`;
}

function mergeSnapshotUnit(
  snapshot: CombatSnapshotUnit,
  base: CombatUnit | undefined,
  match: CombatMatch,
): CombatUnit {
  const inferredOwner = match.players.find((player) => player.side === snapshot.side)?.id ?? "";
  return {
    id: snapshot.id,
    owner_id: base?.owner_id ?? inferredOwner,
    side: snapshot.side,
    blueprint_id: base?.blueprint_id ?? snapshot.card_id ?? snapshot.id,
    card_id: snapshot.card_id,
    row: snapshot.row,
    col: snapshot.col,
    current_hp: snapshot.current_hp,
    max_hp: snapshot.max_hp,
    damage: base?.damage ?? 0,
    move_steps: base?.move_steps ?? 0,
    attacks_per_turn: base?.attacks_per_turn ?? 0,
    stance: snapshot.stance,
    is_tower: snapshot.is_tower,
    // Снапшот A1 не несёт статусы/бюджеты. Существующие значения сохраняем;
    // новый короткоживущий токен получает безопасные нейтральные значения.
    statuses: base?.statuses ?? [],
    remaining_steps: base?.remaining_steps ?? 0,
    remaining_attacks: base?.remaining_attacks ?? 0,
  };
}
