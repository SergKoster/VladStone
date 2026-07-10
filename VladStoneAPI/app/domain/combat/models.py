from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PlayerSide(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"


class ActionPriority(StrEnum):
    ATTACK_FIRST = "attack_first"
    MOVE_FIRST = "move_first"


class Rarity(StrEnum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


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
    # События движка v4 (P2.12); до подмены движка MVP их не эмитит.
    HEAL = "heal"
    SPELL_CAST = "spell_cast"
    STANCE_CHANGED = "stance_changed"
    STATUS_APPLIED = "status_applied"
    STATUS_EXPIRED = "status_expired"
    ABILITY_TRIGGERED = "ability_triggered"
    TAG_GRANTED = "tag_granted"
    EXECUTED = "executed"
    CARD_DRAWN = "card_drawn"
    MANA_CHANGED = "mana_changed"
    FIZZLED = "fizzled"


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
    rarity: Rarity = Rarity.COMMON
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
    # Team index (R12): 1v1, co-op boss and 2v2 are all configurations of the
    # same model. The board side is derived from the team at match creation
    # (side_for_team); allies share a side.
    team: int = Field(default=0, ge=0)
    is_bot: bool = False
    # Account behind this seat; None for bots and anonymous dev matches.
    user_id: int | None = None
    mana: int = Field(default=0, ge=0)
    hero: HeroState
    # Per-player deck cycle. Deck order AND contents are server-side secrets:
    # the API layer exposes only deck_count, and a hand only to its owner.
    deck: list[str] = Field(default_factory=list)
    hand: list[str] = Field(default_factory=list)
    # Scripted test-bot memory: how many units it has spawned, drives its
    # alternating pattern. Meaningless (and 0) for humans.
    bot_spawn_count: int = Field(default=0, ge=0)


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
    # Фаза хода v4 («spells»/«spawn»/«iterations»/«end»/«draw») — для подписей
    # оверлея итераций (§18.3); у MVP-событий отсутствует.
    phase: str | None = None
    snapshot: dict = Field(default_factory=dict)


class MatchResult(BaseModel):
    status: str = "active"
    # Sole player of the winning team when it has exactly one member (1v1);
    # None for draws and (future) multi-player teams — winner_team is then
    # the authoritative field.
    winner_id: str | None = None
    winner_team: int | None = None
    reward_coins: int = 0


class MatchState(BaseModel):
    id: str
    ruleset_version: int = 1
    status: MatchLifecycleStatus = MatchLifecycleStatus.PLANNING
    turn: int = Field(default=1, ge=1)
    # Resolver iteration (micro-turn) counter, stamped onto each event's
    # `micro_step`. Reset to 0 at the start of every turn: setup spawns are
    # iteration 0, the first micro-turn is 1, the next is 2, and so on. Lets the
    # client tell "same iteration" (tight pause) from "next iteration" (long pause).
    current_iteration: int = Field(default=0, ge=0)
    rows: int = 5
    cols: int = 3
    mana_cap: int = 10
    planning_deadline: datetime | None = None
    players: list[PlayerState]
    units: list[UnitState] = Field(default_factory=list)
    log: list[CombatLogEntry] = Field(default_factory=list)
    events: list[CombatEvent] = Field(default_factory=list)
    result: MatchResult = Field(default_factory=MatchResult)
