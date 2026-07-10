"""Фиксированный словарь примитивов Effect (ARCH §5.1) — чистые данные.

Карта = композиция известных примитивов + селектор целей (Q1): произвольного
кода на карту нет — это ключ к отказоустойчивости. Новый примитив добавляется
в словарь редко, тестируется один раз и переиспользуется всеми картами.
Исполнение примитивов — в engine/apply.py; здесь только формы данных с
валидацией на конструировании.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.combat.engine.stances import Stance
from app.domain.combat.engine.statuses import KNOWN_STATUSES, STATUS_FORCED_STANCE
from app.domain.combat.engine.tags import KNOWN_TAGS


class DealDamage(BaseModel):
    model_config = {"frozen": True}

    kind: Literal["deal_damage"] = "deal_damage"
    amount: int = Field(gt=0)
    # F4: юниты с тегом structure (башни) по умолчанию НЕ получают урон от
    # эффектов — только карты, где пробитие прописано явно.
    affects_structures: bool = False


class Heal(BaseModel):
    model_config = {"frozen": True}

    kind: Literal["heal"] = "heal"
    # Потолка HP нет (Q4): оверхил легален и намеренно не ограничивается.
    amount: int = Field(gt=0)


class ApplyStatus(BaseModel):
    model_config = {"frozen": True}

    kind: Literal["apply_status"] = "apply_status"
    status_id: str
    stacks: int = Field(default=1, ge=1)
    ttl: int | None = Field(default=None, ge=1)

    @field_validator("status_id")
    @classmethod
    def _known_plain_status(cls, status_id: str) -> str:
        if status_id not in KNOWN_STATUSES:
            raise ValueError(f"Unknown status {status_id!r}; register it in engine/statuses.py")
        if status_id == STATUS_FORCED_STANCE:
            raise ValueError("Use the change_stance effect to impose a stance")
        return status_id


class ChangeStance(BaseModel):
    model_config = {"frozen": True}

    kind: Literal["change_stance"] = "change_stance"
    stance: Stance
    # None = постоянная смена; число — на сколько ходов (E4).
    ttl: int | None = Field(default=None, ge=1)


class GrantTag(BaseModel):
    model_config = {"frozen": True}

    kind: Literal["grant_tag"] = "grant_tag"
    tag: str

    @field_validator("tag")
    @classmethod
    def _known_tag(cls, tag: str) -> str:
        if tag not in KNOWN_TAGS:
            raise ValueError(f"Unknown tag {tag!r}; register it in engine/tags.py")
        return tag


class Push(BaseModel):
    model_config = {"frozen": True}

    kind: Literal["push"] = "push"
    cells: int = Field(default=1, ge=1)
    # Направление относительно СТОРОНЫ ЦЕЛИ: forward — к её врагу («Толчок»
    # продвигает своего), backward — к её краю (оттолкнуть штурмующего).
    direction: Literal["forward", "backward"] = "forward"


class KillIf(BaseModel):
    """Условная казнь («Жнец»: уничтожить всех с Ядом 2+; «добей, если 1 HP»)."""

    model_config = {"frozen": True}

    kind: Literal["kill_if"] = "kill_if"
    status_id: str | None = None
    min_stacks: int = Field(default=1, ge=1)
    max_hp: int | None = None

    @model_validator(mode="after")
    def _has_a_condition(self) -> "KillIf":
        if self.status_id is None and self.max_hp is None:
            raise ValueError("kill_if needs a condition: status_id and/or max_hp")
        if self.status_id is not None and self.status_id not in KNOWN_STATUSES:
            raise ValueError(f"Unknown status {self.status_id!r}")
        return self


class SpawnToken(BaseModel):
    model_config = {"frozen": True}

    kind: Literal["spawn_token"] = "spawn_token"
    # Токен-карта (collectible=false); ссылка проверяется при применении
    # против реестра карт контекста.
    card_id: str


class DrawCard(BaseModel):
    model_config = {"frozen": True}

    kind: Literal["draw_card"] = "draw_card"
    count: int = Field(default=1, ge=1)
    who: Literal["self", "opponent"] = "self"


class ModifyMana(BaseModel):
    model_config = {"frozen": True}

    kind: Literal["modify_mana"] = "modify_mana"
    # Отрицательное = отнять («кража маны» = modify_mana(-N, opponent) +
    # modify_mana(+N, self) в одном скрипте, R13).
    amount: int
    who: Literal["self", "opponent"] = "self"

    @field_validator("amount")
    @classmethod
    def _non_zero(cls, amount: int) -> int:
        if amount == 0:
            raise ValueError("modify_mana amount must be non-zero")
        return amount


Effect = Annotated[
    DealDamage
    | Heal
    | ApplyStatus
    | ChangeStance
    | GrantTag
    | Push
    | KillIf
    | SpawnToken
    | DrawCard
    | ModifyMana,
    Field(discriminator="kind"),
]
