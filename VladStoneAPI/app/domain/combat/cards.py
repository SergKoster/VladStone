from app.domain.combat.models import ActionPriority, CardDefinition, Rarity, UnitStats

# Все характеристики временно = 1 (решение владельца, июль 2026): статы и
# механики обсуждаются по одной карте в рамках переработки боя
# (docs/COMBAT_REWORK.md). Редкости — черновые, для витрины коллекции.
# id карт вечны (DESIGN §4.5) — менять можно имена, но не id.


def _stats_one() -> UnitStats:
    return UnitStats(
        hp=1,
        damage=1,
        attack_range=1,
        move_steps=1,
        attacks=1,
        action_priority=ActionPriority.ATTACK_FIRST,
    )


def _card(card_id: str, name: str, rarity: Rarity) -> CardDefinition:
    return CardDefinition(id=card_id, name=name, cost=1, rarity=rarity, stats=_stats_one())


BRUISER_CARD = _card("test_bruiser", "Толстяк", Rarity.COMMON)
RANGER_CARD = _card("test_ranger", "Дальник", Rarity.UNCOMMON)

STARTER_CARDS = [
    BRUISER_CARD,
    _card("banka", "Банка", Rarity.COMMON),
    _card("red_skull", "Красный череп", Rarity.COMMON),
    RANGER_CARD,
    _card("dolbiki", "Долбики", Rarity.UNCOMMON),
    _card("mushrooms", "Грибной лес", Rarity.UNCOMMON),
    _card("matesha", "Матеша", Rarity.RARE),
    _card("evil_dolbiki", "Злые Долбики", Rarity.RARE),
    _card("matesha_plus", "Матеша+", Rarity.EPIC),
    _card("epic_serega", "Эпик Серёга", Rarity.EPIC),
    _card("zadanie", "Задание", Rarity.LEGENDARY),
]
CARD_BY_ID = {card.id: card for card in STARTER_CARDS}

# Pre-built test deck: every catalog card exactly once.
DECK_CARD_IDS = [card.id for card in STARTER_CARDS]
