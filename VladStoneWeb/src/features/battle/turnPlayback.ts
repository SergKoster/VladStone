import {
  type CombatEvent,
  type CombatEventSnapshot,
  type CombatMatch,
  type CombatResponse,
  type CombatSnapshotUnit,
  type CombatUnit,
} from "../../api";

/**
 * Идентификатор уже завершённого сервером хода.
 *
 * После обычного резолва сервер переводит planning N -> planning N+1, а при
 * завершении матча оставляет номер N. Последняя sequence отличает неполный
 * поток событий от полного при будущем resume/reconnect-контракте.
 */
export function responsePlaybackKey(response: CombatResponse): string {
  const resolvedTurn =
    response.match.status === "planning"
      ? Math.max(0, response.match.turn - 1)
      : response.match.turn;
  const lastSequence = response.events.reduce(
    (highest, event) => Math.max(highest, event.sequence ?? -1),
    -1,
  );
  return `${response.match.id}:${resolvedTurn}:${lastSequence}`;
}

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

/** Применить кадр события и точное after_hp даже если цель уже выпала из снапшота. */
export function applyEventSnapshot(
  match: CombatMatch,
  event: CombatEvent,
  fallbackUnits: CombatUnit[] = [],
): CombatMatch {
  const next = applySnapshot(match, event.snapshot, fallbackUnits);
  const hpUnitId = event.target_id ?? (event.type === "death" ? event.actor_id : null);
  const afterHp = event.after_hp;
  if (!hpUnitId || afterHp === null) return next;
  return {
    ...next,
    units: next.units.map((unit) =>
      unit.id === hpUnitId ? { ...unit, current_hp: afterHp } : unit,
    ),
  };
}

function compareUnitIds(a: CombatUnit, b: CombatUnit): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** Ключ визуальной группы: фаза + номер итерации. */
export function groupKey(event: CombatEvent): string {
  return `${event.phase}:${event.micro_step}`;
}

/** Подпись A5 — только для реально присутствующей серверной фазы. */
export function phaseLabel(event: CombatEvent | null): string | null {
  switch (event?.phase) {
    case "spells":
      return "Заклинания";
    case "spawn":
      return "Появление воинов";
    case "iterations":
      return `Итерация ${event.micro_step}`;
    case "end":
      return "Конец хода";
    default:
      return null;
  }
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
