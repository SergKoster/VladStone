"""Карты v4: коллекционная запись, отделённая от юнита (COMBAT_REWORK §10.7).

Юнит-карта ссылается на UnitBlueprint; заклинание — на скрипт эффектов
(spell_id; сами скрипты приходят со словарём эффектов, P2.9). Токены —
collectible=False: полные статы и цена (видны при просмотре карты-матери),
в коллекции не числятся, с руки не разыгрываются, но механики могут положить
токен в руку.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from app.domain.combat.models import Rarity


class CardType(StrEnum):
    UNIT = "unit"
    SPELL = "spell"


class CardDefinition(BaseModel):
    model_config = {"frozen": True}

    id: str
    name: str
    cost: int = Field(ge=0)
    rarity: Rarity = Rarity.COMMON
    card_type: CardType
    collectible: bool = True
    blueprint_id: str | None = None
    spell_id: str | None = None

    @model_validator(mode="after")
    def _payload_matches_type(self) -> "CardDefinition":
        if self.card_type == CardType.UNIT:
            if self.blueprint_id is None or self.spell_id is not None:
                raise ValueError(f"Unit card {self.id!r} must reference exactly a blueprint_id")
        else:
            if self.spell_id is None or self.blueprint_id is not None:
                raise ValueError(f"Spell card {self.id!r} must reference exactly a spell_id")
        return self


def collectible_cards(cards: list[CardDefinition]) -> list[CardDefinition]:
    """Что попадает в коллекцию/каталог: токены отфильтрованы."""
    return [card for card in cards if card.collectible]
