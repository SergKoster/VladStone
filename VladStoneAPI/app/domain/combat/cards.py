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

# Test cards from res/Cards photos: ascending mana cost, roughly balanced stats,
# one card per rarity tier so every frame colour is visible in game.
BANKA_CARD = CardDefinition(
    id="banka",
    name="Банка",
    cost=1,
    rarity=Rarity.COMMON,
    stats=UnitStats(
        hp=2,
        damage=1,
        attack_range=1,
        move_steps=1,
        attacks=1,
        action_priority=ActionPriority.ATTACK_FIRST,
    ),
)

DOLBIKI_CARD = CardDefinition(
    id="dolbiki",
    name="Долбики",
    cost=2,
    rarity=Rarity.UNCOMMON,
    stats=UnitStats(
        hp=3,
        damage=1,
        attack_range=1,
        move_steps=2,
        attacks=1,
        action_priority=ActionPriority.ATTACK_FIRST,
    ),
)

MATESHA_CARD = CardDefinition(
    id="matesha",
    name="Матеша",
    cost=3,
    rarity=Rarity.RARE,
    stats=UnitStats(
        hp=3,
        damage=2,
        attack_range=2,
        move_steps=1,
        attacks=1,
        action_priority=ActionPriority.ATTACK_FIRST,
    ),
)

MATESHA_PLUS_CARD = CardDefinition(
    id="matesha_plus",
    name="Матеша+",
    cost=4,
    rarity=Rarity.EPIC,
    stats=UnitStats(
        hp=5,
        damage=2,
        attack_range=1,
        move_steps=1,
        attacks=2,
        action_priority=ActionPriority.ATTACK_FIRST,
    ),
)

ZADANIE_CARD = CardDefinition(
    id="zadanie",
    name="Задание",
    cost=5,
    rarity=Rarity.LEGENDARY,
    stats=UnitStats(
        hp=7,
        damage=3,
        attack_range=1,
        move_steps=1,
        attacks=1,
        action_priority=ActionPriority.ATTACK_FIRST,
    ),
)

STARTER_CARDS = [
    BANKA_CARD,
    RANGER_CARD,
    DOLBIKI_CARD,
    BRUISER_CARD,
    MATESHA_CARD,
    MATESHA_PLUS_CARD,
    ZADANIE_CARD,
]
CARD_BY_ID = {card.id: card for card in STARTER_CARDS}

# Pre-built test deck: every catalog card exactly once.
DECK_CARD_IDS = [card.id for card in STARTER_CARDS]
