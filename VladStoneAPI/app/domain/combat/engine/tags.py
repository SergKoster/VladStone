"""Реестр тегов юнитов (F6, COMBAT_REWORK §18.7).

Теги — данные для таргетинга и правил ("structure" не получает урон от
заклинаний по умолчанию — F4; "immovable" иммунен к смене стойки — F3).
Свободные строки запрещены: опечатка в теге = молчаливое «не совпало» = баг,
поэтому всё, что не в реестре, отбрасывается валидацией на загрузке (I7),
а не всплывает в бою.
"""

TAG_STRUCTURE = "structure"
TAG_TOWER = "tower"
TAG_IMMOVABLE = "immovable"

KNOWN_TAGS: frozenset[str] = frozenset({TAG_STRUCTURE, TAG_TOWER, TAG_IMMOVABLE})


def validate_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    unknown = [tag for tag in tags if tag not in KNOWN_TAGS]
    if unknown:
        raise ValueError(f"Unknown unit tags {unknown}; register them in engine/tags.py")
    # Deterministic serialization (I3): stored sorted and deduplicated.
    return tuple(sorted(set(tags)))
