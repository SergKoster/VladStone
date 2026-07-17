import { type CombatEvent, type CombatMatch } from "../../api";

export type LungeEffect = {
  unitId: string;
  dx: number;
  dy: number;
};

export type BattlePopup = {
  key: number;
  row: number;
  col: number;
  amount: number;
  kind: "damage" | "heal" | "status";
  /** V9: id статуса для подписи попапа («Яд +3»); имя берётся из каталога. */
  statusId?: string;
};

export type CellPulse = {
  key: number;
  row: number;
  col: number;
  kind: "spell" | "ability-spawn" | "ability-death" | "ability";
};

/** Визуал области выбирается по серверной причине, а не по тексту события. */
export function cellPulseKind(event: CombatEvent): CellPulse["kind"] {
  if (event.type !== "ability_triggered") return "spell";
  if (event.ability_trigger === "on_spawn") return "ability-spawn";
  if (event.ability_trigger === "on_death") return "ability-death";
  return "ability";
}

/** Выпад атаки; при коллизии оба участника сходятся в заявленной клетке. */
export function lungeEffects(event: CombatEvent, match: CombatMatch): LungeEffect[] {
  if (event.type !== "attack" && event.type !== "collision") return [];
  const destination = event.to_position;
  if (!destination) return [];

  const actor = event.actor_id ? match.units.find((unit) => unit.id === event.actor_id) : null;
  const actorFrom = event.from_position ?? actor ?? null;
  const effects: LungeEffect[] = [];
  if (event.actor_id && actorFrom) {
    effects.push(offsetTo(event.actor_id, actorFrom, destination));
  }

  if (event.type === "collision" && event.target_id) {
    const target = match.units.find((unit) => unit.id === event.target_id);
    if (target) effects.push(offsetTo(event.target_id, target, destination));
  }
  return effects;
}

/** Попап для серверного события HP; позиция цели берётся из живого кадра. */
export function popupForEvent(
  event: CombatEvent,
  before: CombatMatch,
  key: number,
): BattlePopup | null {
  // V9: наложение статуса всплывает над целью («Яд +3») по структурным полям.
  if (event.type === "status_applied" && event.status_id) {
    const target = event.target_id
      ? before.units.find((unit) => unit.id === event.target_id)
      : null;
    if (!target) return null;
    return {
      key,
      row: target.row,
      col: target.col,
      amount: event.status_stacks ?? 0,
      kind: "status",
      statusId: event.status_id,
    };
  }
  if (event.type !== "attack" && event.type !== "damage" && event.type !== "heal") {
    return null;
  }
  const position =
    event.to_position ??
    (event.target_id ? before.units.find((unit) => unit.id === event.target_id) : null);
  if (!position) return null;

  const hpDelta =
    event.before_hp !== null && event.after_hp !== null
      ? Math.abs(event.after_hp - event.before_hp)
      : Math.abs(event.damage ?? 0);
  if (hpDelta <= 0) return null;
  return {
    key,
    row: position.row,
    col: position.col,
    amount: hpDelta,
    kind: event.type === "heal" ? "heal" : "damage",
  };
}

function offsetTo(
  unitId: string,
  from: { row: number; col: number },
  to: { row: number; col: number },
): LungeEffect {
  return {
    unitId,
    dx: (to.col - from.col) * 100,
    dy: (to.row - from.row) * 100,
  };
}
