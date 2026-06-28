from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PlayerSide(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"


class ActionPriority(StrEnum):
    ATTACK_FIRST = "attack_first"
    MOVE_FIRST = "move_first"


class CombatEventType(StrEnum):
    SPAWN = "spawn"
    SPAWN_BLOCKED = "spawn_blocked"
    PUSH = "push"
    MOVE = "move"
    MOVE_BLOCKED = "move_blocked"
    ATTACK = "attack"
    DAMAGE = "damage"
    COLLISION = "collision"
    COLLISION_STEP = "collision_step"
    DEATH = "death"
    HERO_HIT = "hero_hit"
    MATCH_FINISHED = "match_finished"


class CombatTargetKind(StrEnum):
    UNIT = "unit"
    HERO = "hero"
    CELL = "cell"
    MATCH = "match"


class MatchLifecycleStatus(StrEnum):
    PLANNING = "planning"
    RESOLVING = "resolving"
    FINISHED = "finished"
    EXPIRED = "expired"


class Position(BaseModel):
    row: int = Field(ge=0)
    col: int = Field(ge=0)


class UnitStats(BaseModel):
    hp: int = Field(gt=0)
    damage: int = Field(gt=0)
    attack_range: int = Field(gt=0)
    move_steps: int = Field(ge=0)
    attacks: int = Field(ge=0)
    action_priority: ActionPriority = ActionPriority.ATTACK_FIRST


class CardDefinition(BaseModel):
    id: str
    name: str
    cost: int = Field(ge=0)
    stats: UnitStats


class UnitState(BaseModel):
    id: str
    owner_id: str
    side: PlayerSide
    card_id: str
    position: Position
    stats: UnitStats
    current_hp: int = Field(gt=0)
    remaining_steps: int = Field(ge=0)
    remaining_attacks: int = Field(ge=0)


class HeroState(BaseModel):
    owner_id: str
    side: PlayerSide
    hp: int = Field(default=20, ge=0)


class PlayerState(BaseModel):
    id: str
    side: PlayerSide
    mana: int = Field(default=0, ge=0)
    hero: HeroState


class CombatLogEntry(BaseModel):
    message: str


class CombatEvent(BaseModel):
    type: CombatEventType
    message: str
    actor_id: str | None = None
    target_id: str | None = None
    target_kind: CombatTargetKind | None = None
    damage: int | None = None
    from_position: Position | None = None
    to_position: Position | None = None
    before_hp: int | None = None
    after_hp: int | None = None
    sequence: int | None = None
    micro_step: int | None = None
    snapshot: dict = Field(default_factory=dict)


class MatchResult(BaseModel):
    status: str = "active"
    winner_id: str | None = None
    reward_coins: int = 0


class MatchState(BaseModel):
    id: str
    ruleset_version: int = 1
    status: MatchLifecycleStatus = MatchLifecycleStatus.PLANNING
    turn: int = Field(default=1, ge=1)
    rows: int = 5
    cols: int = 3
    mana_cap: int = 10
    planning_deadline: datetime | None = None
    players: list[PlayerState]
    units: list[UnitState] = Field(default_factory=list)
    log: list[CombatLogEntry] = Field(default_factory=list)
    events: list[CombatEvent] = Field(default_factory=list)
    result: MatchResult = Field(default_factory=MatchResult)
