"""Единый v4-каталог для боя, коллекции и выдачи карт.

Игровые определения остаются data-driven в ``content.py``. Этот модуль
собирает их в прикладной каталог: HTTP-представление, DB-проекцию и текущую
стартовую выдачу обязаны брать данные только отсюда.
"""

from collections.abc import Iterable

from app.domain.combat.engine.cards import CardDefinition, CardType
from app.domain.combat.engine.content import BLUEPRINTS, CARDS


def collectible_v4_cards() -> tuple[CardDefinition, ...]:
    """Коллекционные карты текущего live-правила в стабильном порядке."""
    return tuple(card for card in CARDS.values() if card.collectible)


def starter_grant_card_ids() -> tuple[str, ...]:
    """Временная live-выдача первого утверждённого батча v4.

    Все 12 текущих обычных карт выдаются сразу (COMBAT_REWORK §14.1). Состав
    будущего набора 12+ после расширения каталога остаётся решением владельца
    (DESIGN §5); его нельзя неявно выводить из этой функции.
    """
    return tuple(card.id for card in collectible_v4_cards())


def db_projection(card: CardDefinition) -> dict[str, int | str]:
    """Обязательные поля legacy-таблицы ``card_definitions``.

    Таблица хранит только FK и переходную денормализованную проекцию: публичные
    метаданные коллекции отдаёт v4 catalog payload. У заклинаний нет статов
    юнита, поэтому числовые поля получают нейтральный ноль.
    """
    if card.card_type == CardType.UNIT:
        blueprint = BLUEPRINTS[card.blueprint_id]
        return {
            "name": card.name,
            "cost": card.cost,
            "hp": blueprint.stats.hp,
            "damage": blueprint.stats.damage,
            "attack_range": 0,
            "move_steps": blueprint.stats.move_steps,
            "attacks": blueprint.stats.attacks_per_turn,
            "action_priority": "v4",
        }
    return {
        "name": card.name,
        "cost": card.cost,
        "hp": 0,
        "damage": 0,
        "attack_range": 0,
        "move_steps": 0,
        "attacks": 0,
        "action_priority": "v4",
    }


def ids(cards: Iterable[CardDefinition]) -> tuple[str, ...]:
    """Короткий помощник для контрактных проверок и валидации колоды."""
    return tuple(card.id for card in cards)
