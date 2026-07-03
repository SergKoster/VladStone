from app.domain.combat.models import ActionPriority, CardDefinition, Rarity, UnitStats

BRUISER_CARD = CardDefinition(
    id="test_bruiser",
    name="Тестовый толстяк",
    cost=3,
    rarity=Rarity.COMMON,
    stats=UnitStats(
        hp=4,
        damage=2,
        attack_range=1,
        move_steps=1,
        attacks=1,
        action_priority=ActionPriority.ATTACK_FIRST,
    ),
)

RANGER_CARD = CardDefinition(
    id="test_ranger",
    name="Тестовый дальник",
    cost=2,
    rarity=Rarity.UNCOMMON,
    stats=UnitStats(
        hp=2,
        damage=1,
        attack_range=2,
        move_steps=1,
        attacks=2,
        action_priority=ActionPriority.ATTACK_FIRST,
    ),
)

STARTER_CARDS = [BRUISER_CARD, RANGER_CARD]
CARD_BY_ID = {card.id: card for card in STARTER_CARDS}
