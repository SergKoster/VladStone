from app.domain.combat.rules import BRUISER_CARD, RANGER_CARD, STARTER_CARDS

STARTER_CARD_COPIES = {
    BRUISER_CARD.id: 2,
    RANGER_CARD.id: 1,
}
# Every other test card is granted as a single copy.
for _card in STARTER_CARDS:
    STARTER_CARD_COPIES.setdefault(_card.id, 1)

ASCENSION_LABELS = {
    "default": "Дефолт",
    "ascended": "Возвышенный",
    "ascended_plus": "Возвышенный+",
}


def starter_catalog_payload() -> list[dict]:
    """Card catalog served to the client so card stats live on the server only.

    Stats come from the combat domain (single source of truth, also used to seed
    the DB). `copies` reflects the default starter grant; per-player ownership is
    served separately by /me/collection.
    """
    return [
        {
            "id": card.id,
            "name": card.name,
            "cost": card.cost,
            "rarity": card.rarity.value,
            "hp": card.stats.hp,
            "damage": card.stats.damage,
            "range": card.stats.attack_range,
            "steps": card.stats.move_steps,
            "attacks": card.stats.attacks,
            "copies": STARTER_CARD_COPIES.get(card.id, 1),
            "ascension": ASCENSION_LABELS["default"],
        }
        for card in STARTER_CARDS
    ]

