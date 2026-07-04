from datetime import UTC, datetime, timedelta

from app.domain.combat.cards import DECK_CARD_IDS
from app.domain.combat.models import CombatEventType, PlayerSide, Position
from app.domain.combat.rules import (
    BRUISER_CARD,
    RANGER_CARD,
    add_turn_mana,
    apply_placements,
    apply_simple_bot_turn,
    create_demo_match,
    create_player_match,
    create_unit,
    is_valid_spawn_position,
    resolve_turn,
    reward_for_result,
)
from app.domain.combat.timing import is_planning_deadline_expired


def test_deck_cycle_deals_hand_draws_and_reshuffles() -> None:
    match = create_player_match()

    # Full test deck: every catalog card exactly once, split hand/deck.
    assert len(match.player_hand) == 3
    assert len(match.player_deck) == len(DECK_CARD_IDS) - 3
    assert sorted(match.player_hand + match.player_deck) == sorted(DECK_CARD_IDS)

    # Each resolved turn draws exactly one card into the hand.
    resolved = resolve_turn(match)
    assert len(resolved.player_hand) == 4
    assert len(resolved.player_deck) == len(DECK_CARD_IDS) - 4

    # When the deck runs out, a fresh shuffled deck is built from the cards
    # that are not in hand, and drawing continues.
    resolved.player_deck = []
    resolved.player_hand = ["banka", "test_ranger"]
    redrawn = resolve_turn(resolved)
    assert len(redrawn.player_hand) == 3
    assert len(redrawn.player_deck) == len(DECK_CARD_IDS) - 3
    assert sorted(redrawn.player_hand + redrawn.player_deck) == sorted(DECK_CARD_IDS)


def test_placements_from_hand_consume_only_played_cards() -> None:
    match = create_player_match()
    match.player_hand = ["banka", "zadanie", "test_ranger"]
    player = next(candidate for candidate in match.players if candidate.id == "player")
    player.mana = 2

    updated = apply_placements(
        match,
        [
            ("banka", Position(row=4, col=0)),
            # Too expensive for 2 mana: skipped, must stay in hand.
            ("zadanie", Position(row=4, col=1)),
            # Not in hand: skipped.
            ("test_bruiser", Position(row=4, col=2)),
        ],
        owner_id="player",
        side=PlayerSide.BOTTOM,
        from_hand=True,
    )

    assert updated.player_hand == ["zadanie", "test_ranger"]
    assert [unit.card_id for unit in updated.units] == ["banka"]


def test_bot_alternates_bruiser_lane_0_and_ranger_lane_1() -> None:
    match = create_player_match()
    bot = next(candidate for candidate in match.players if candidate.id == "bot")

    # Not enough mana for the bruiser yet: the bot saves up instead of skipping
    # ahead in its pattern.
    skipped = apply_simple_bot_turn(match)
    assert not [unit for unit in skipped.units if unit.owner_id == "bot"]
    assert skipped.bot_spawn_count == 0

    bot.mana = 10
    first = apply_simple_bot_turn(match)  # spawn 1: bruiser to lane 0
    assert [(u.card_id, u.position.col) for u in first.units if u.owner_id == "bot"] == [
        ("test_bruiser", 0)
    ]

    second = apply_simple_bot_turn(first)  # spawn 2: ranger to lane 1
    bot_units = [(u.card_id, u.position.col) for u in second.units if u.owner_id == "bot"]
    assert ("test_ranger", 1) in bot_units
    assert second.bot_spawn_count == 2


def test_mana_schedule_and_cap() -> None:
    assert add_turn_mana(0, 1) == 2
    assert add_turn_mana(2, 2) == 3
    assert add_turn_mana(3, 3) == 5
    assert add_turn_mana(9, 10) == 10


def test_match_has_server_planning_deadline_and_refreshes_it_after_resolve() -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    match = create_player_match(now=started_at)

    assert match.planning_deadline == started_at + timedelta(seconds=30)
    assert not is_planning_deadline_expired(match, now=started_at + timedelta(seconds=29))
    assert is_planning_deadline_expired(match, now=started_at + timedelta(seconds=30))

    resolved_at = started_at + timedelta(seconds=10)
    resolved = resolve_turn(match, now=resolved_at)

    assert resolved.turn == 2
    assert resolved.planning_deadline == resolved_at + timedelta(seconds=30)


def test_spawn_zone_is_nearest_row_to_hero() -> None:
    assert is_valid_spawn_position(PlayerSide.TOP, Position(row=0, col=2))
    assert is_valid_spawn_position(PlayerSide.BOTTOM, Position(row=4, col=0))
    assert not is_valid_spawn_position(PlayerSide.TOP, Position(row=1, col=2))


def test_attack_first_unit_attacks_before_moving() -> None:
    match = create_demo_match()
    match.units[0].position = Position(row=1, col=1)
    match.units[1].position = Position(row=2, col=1)

    resolved = resolve_turn(match)

    bottom = next(unit for unit in resolved.units if unit.id == "bottom_bruiser")
    assert bottom.current_hp == 3
    assert any("top_ranger attacked bottom_bruiser" in entry.message for entry in resolved.log)
    assert not any("top_ranger moved" in entry.message for entry in resolved.log)


def test_collision_consumes_actions_and_continues_resolve() -> None:
    match = create_demo_match()
    top_player = match.players[0]
    bottom_player = match.players[1]
    match.units = [
        create_unit(
            unit_id="top_bruiser",
            owner_id=top_player.id,
            side=top_player.side,
            card=BRUISER_CARD,
            position=Position(row=1, col=0),
        ),
        create_unit(
            unit_id="bottom_bruiser",
            owner_id=bottom_player.id,
            side=bottom_player.side,
            card=BRUISER_CARD,
            position=Position(row=3, col=0),
        ),
    ]

    resolved = resolve_turn(match)

    assert any("collided" in entry.message for entry in resolved.log)
    top = next(unit for unit in resolved.units if unit.id == "top_bruiser")
    bottom = next(unit for unit in resolved.units if unit.id == "bottom_bruiser")
    # Actions were consumed during resolution (units stayed put), and the
    # planning state shows the refreshed budget for the next turn.
    assert top.position == Position(row=1, col=0)
    assert bottom.position == Position(row=3, col=0)
    assert top.current_hp == 2
    assert bottom.current_hp == 2
    assert top.remaining_steps == top.stats.move_steps
    assert bottom.remaining_steps == bottom.stats.move_steps


def test_same_micro_turn_move_conflict_consumes_steps_for_both_units() -> None:
    match = create_demo_match()
    top_player = match.players[0]
    bottom_player = match.players[1]
    match.units = [
        create_unit(
            unit_id="top_walker",
            owner_id=top_player.id,
            side=top_player.side,
            card=BRUISER_CARD,
            position=Position(row=1, col=1),
        ),
        create_unit(
            unit_id="bottom_walker",
            owner_id=bottom_player.id,
            side=bottom_player.side,
            card=BRUISER_CARD,
            position=Position(row=3, col=1),
        ),
    ]
    for unit in match.units:
        unit.stats = unit.stats.model_copy(update={"attacks": 0})

    resolved = resolve_turn(match)

    top = next(unit for unit in resolved.units if unit.id == "top_walker")
    bottom = next(unit for unit in resolved.units if unit.id == "bottom_walker")
    # The conflict consumed their steps during resolution: both stayed put.
    assert top.position == Position(row=1, col=1)
    assert bottom.position == Position(row=3, col=1)


def test_second_same_cell_collision_without_attacks_only_consumes_steps() -> None:
    match = create_demo_match()
    top_player = match.players[0]
    bottom_player = match.players[1]
    match.units = [
        create_unit(
            unit_id="top_bruiser",
            owner_id=top_player.id,
            side=top_player.side,
            card=BRUISER_CARD,
            position=Position(row=1, col=0),
        ),
        create_unit(
            unit_id="bottom_bruiser",
            owner_id=bottom_player.id,
            side=bottom_player.side,
            card=BRUISER_CARD,
            position=Position(row=3, col=0),
        ),
    ]
    for unit in match.units:
        unit.stats = unit.stats.model_copy(update={"move_steps": 2, "attacks": 1})

    resolved = resolve_turn(match)

    top = next(unit for unit in resolved.units if unit.id == "top_bruiser")
    bottom = next(unit for unit in resolved.units if unit.id == "bottom_bruiser")
    # Steps and the single attack were consumed during resolution, so both
    # units stayed put and traded exactly one hit each.
    assert top.position == Position(row=1, col=0)
    assert bottom.position == Position(row=3, col=0)
    assert top.current_hp == 2
    assert bottom.current_hp == 2


def test_player_can_spawn_on_enemy_in_spawn_row_and_push_it_back() -> None:
    match = create_player_match()
    player = next(candidate for candidate in match.players if candidate.id == "player")
    bot = next(candidate for candidate in match.players if candidate.id == "bot")
    player.mana = 3
    enemy = create_unit(
        unit_id="enemy_at_spawn",
        owner_id=bot.id,
        side=bot.side,
        card=RANGER_CARD,
        position=Position(row=4, col=1),
    )
    match.units = [enemy]

    updated = apply_placements(
        match,
        [("test_bruiser", Position(row=4, col=1))],
        owner_id=player.id,
        side=player.side,
    )

    pushed = next(unit for unit in updated.units if unit.id == "enemy_at_spawn")
    spawned = next(unit for unit in updated.units if unit.owner_id == player.id)
    assert pushed.position == Position(row=3, col=1)
    assert spawned.position == Position(row=4, col=1)
    assert next(candidate for candidate in updated.players if candidate.id == "player").mana == 0
    assert any("was pushed" in entry.message for entry in updated.log)
    push_event = next(event for event in updated.events if event.type == CombatEventType.PUSH)
    assert push_event.actor_id == "enemy_at_spawn"
    assert push_event.from_position == Position(row=4, col=1)
    assert push_event.to_position == Position(row=3, col=1)
    spawn_event = next(event for event in updated.events if event.type == CombatEventType.SPAWN)
    assert spawn_event.actor_id == spawned.id
    assert spawn_event.to_position == Position(row=4, col=1)


def test_overkill_attack_is_not_wasted_on_a_doomed_target() -> None:
    match = create_demo_match()
    top_player = match.players[0]
    bottom_player = match.players[1]
    match.units = [
        create_unit(
            unit_id="top_ranger_a",
            owner_id=top_player.id,
            side=top_player.side,
            card=RANGER_CARD,
            position=Position(row=1, col=1),
        ),
        create_unit(
            unit_id="top_ranger_b",
            owner_id=top_player.id,
            side=top_player.side,
            card=RANGER_CARD,
            position=Position(row=0, col=1),
        ),
        create_unit(
            unit_id="bottom_target",
            owner_id=bottom_player.id,
            side=bottom_player.side,
            card=RANGER_CARD,
            position=Position(row=2, col=1),
        ),
    ]
    match.units[0].stats = match.units[0].stats.model_copy(update={"attacks": 1})
    match.units[1].stats = match.units[1].stats.model_copy(update={"attacks": 1})
    match.units[2].current_hp = 1
    match.units[2].stats = match.units[2].stats.model_copy(update={"attacks": 0})

    resolved = resolve_turn(match)

    attacks_on_target = [
        event
        for event in resolved.events
        if event.type == CombatEventType.ATTACK and event.target_id == "bottom_target"
    ]
    # Only one attacker spends its hit on the 1-HP target; the other keeps its attack.
    assert len(attacks_on_target) == 1
    assert all(unit.id != "bottom_target" for unit in resolved.units)


def test_ranger_does_not_move_when_attack_is_available() -> None:
    match = create_demo_match()
    match.units[0].position = Position(row=1, col=1)
    match.units[1].position = Position(row=3, col=1)

    resolved = resolve_turn(match)

    assert any("top_ranger attacked bottom_bruiser" in entry.message for entry in resolved.log)
    assert not any("top_ranger moved" in entry.message for entry in resolved.log)


def test_combat_events_include_replay_fields_for_animation() -> None:
    match = create_demo_match()
    match.units[0].position = Position(row=1, col=1)
    match.units[1].position = Position(row=3, col=1)

    resolved = resolve_turn(match)

    attack_event = next(event for event in resolved.events if event.type == CombatEventType.ATTACK)
    assert attack_event.actor_id == "top_ranger"
    assert attack_event.target_id == "bottom_bruiser"
    assert attack_event.target_kind == "unit"
    assert attack_event.damage == 1
    assert attack_event.from_position == Position(row=1, col=1)
    assert attack_event.to_position == Position(row=3, col=1)
    assert attack_event.before_hp == 4
    assert attack_event.after_hp == 3

    move_event = next(event for event in resolved.events if event.type == CombatEventType.MOVE)
    assert move_event.from_position is not None
    assert move_event.to_position is not None

    micro_steps = [event.micro_step for event in resolved.events]
    assert micro_steps == sorted(micro_steps)
    assert micro_steps[0] == 1
    sequences = [event.sequence for event in resolved.events]
    assert sequences == micro_steps


def test_collision_event_contains_replay_fields() -> None:
    match = create_demo_match()
    top_player = match.players[0]
    bottom_player = match.players[1]
    match.units = [
        create_unit(
            unit_id="top_bruiser",
            owner_id=top_player.id,
            side=top_player.side,
            card=BRUISER_CARD,
            position=Position(row=1, col=0),
        ),
        create_unit(
            unit_id="bottom_bruiser",
            owner_id=bottom_player.id,
            side=bottom_player.side,
            card=BRUISER_CARD,
            position=Position(row=3, col=0),
        ),
    ]

    resolved = resolve_turn(match)

    collision_event = next(
        event
        for event in resolved.events
        if event.type == CombatEventType.COLLISION and event.target_id == "bottom_bruiser"
    )
    assert collision_event.actor_id == "top_bruiser"
    assert collision_event.damage == 2
    assert collision_event.to_position == Position(row=2, col=0)
    assert collision_event.before_hp == 4
    assert collision_event.after_hp == 2


def test_death_event_contains_replay_fields() -> None:
    match = create_demo_match()
    match.units[0].position = Position(row=1, col=1)
    match.units[1].position = Position(row=2, col=1)
    match.units[1].current_hp = 1
    match.units[1].stats = match.units[1].stats.model_copy(update={"attacks": 0})

    resolved = resolve_turn(match)

    death_event = next(event for event in resolved.events if event.type == CombatEventType.DEATH)
    assert death_event.actor_id == "bottom_bruiser"
    assert death_event.from_position == Position(row=2, col=1)
    assert death_event.after_hp == 0


def test_hero_hit_and_match_finished_events_contain_replay_fields() -> None:
    match = create_player_match()
    player = next(candidate for candidate in match.players if candidate.id == "player")
    bot = next(candidate for candidate in match.players if candidate.id == "bot")
    player.hero.hp = 1
    match.units = [
        create_unit(
            unit_id="bot_ranger_at_hero",
            owner_id=bot.id,
            side=bot.side,
            card=RANGER_CARD,
            position=Position(row=4, col=0),
        )
    ]

    resolved = resolve_turn(match)

    hero_hit = next(event for event in resolved.events if event.type == CombatEventType.HERO_HIT)
    assert hero_hit.actor_id == "bot_ranger_at_hero"
    assert hero_hit.target_id == "player"
    assert hero_hit.damage == 1
    assert hero_hit.before_hp == 1
    assert hero_hit.after_hp == 0
    finished = next(
        event for event in resolved.events if event.type == CombatEventType.MATCH_FINISHED
    )
    assert finished.target_id == "bot"
    assert finished.sequence == len(resolved.events)


def test_resolve_survives_multiple_turns_with_bot_and_player_placements() -> None:
    match = create_player_match()
    for turn_index in range(6):
        match = apply_placements(
            match,
            [("test_ranger", Position(row=4, col=turn_index % 3))],
            owner_id="player",
            side=PlayerSide.BOTTOM,
        )
        match = apply_simple_bot_turn(match)
        match = resolve_turn(match)

    assert match.turn == 7
    assert all(unit.current_hp > 0 for unit in match.units)


def test_unit_at_enemy_edge_without_attacks_does_not_crash() -> None:
    match = create_player_match()
    player = next(candidate for candidate in match.players if candidate.id == "player")
    match.turn = 5
    player.mana = 2
    match.units = [
        create_unit(
            unit_id="bottom_ranger_at_edge",
            owner_id=player.id,
            side=player.side,
            card=RANGER_CARD,
            position=Position(row=0, col=1),
        )
    ]
    match.units[0].remaining_attacks = 0

    resolved = resolve_turn(match)

    assert resolved.turn == 6
    assert resolved.units[0].position == Position(row=0, col=1)


def test_match_finishes_when_player_hero_reaches_zero_hp() -> None:
    match = create_player_match()
    player = next(candidate for candidate in match.players if candidate.id == "player")
    bot = next(candidate for candidate in match.players if candidate.id == "bot")
    player.hero.hp = 1
    match.units = [
        create_unit(
            unit_id="bot_ranger_at_hero",
            owner_id=bot.id,
            side=bot.side,
            card=RANGER_CARD,
            position=Position(row=4, col=0),
        )
    ]

    resolved = resolve_turn(match)
    repeated = resolve_turn(resolved)

    assert resolved.result.status == "finished"
    assert resolved.result.winner_id == "bot"
    assert resolved.result.reward_coins == 1
    assert player.hero.hp == 1
    resolved_player = next(candidate for candidate in resolved.players if candidate.id == "player")
    assert resolved_player.hero.hp == 0
    assert repeated.result.status == "finished"
    assert any(event.type == CombatEventType.MATCH_FINISHED for event in resolved.events)


def test_reward_values() -> None:
    assert reward_for_result(did_win=True) == 5
    assert reward_for_result(did_win=False) == 1
