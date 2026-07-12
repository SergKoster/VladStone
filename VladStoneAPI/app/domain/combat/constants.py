BOARD_ROWS = 5
BOARD_COLS = 3
HERO_HP = 20
MANA_CAP = 10
# v3: combat engine v4 goes live (stances, 5 towers, phased resolver,
# data-driven cards). The state shape changed again (BattleStateV4); the
# ruleset gate (ARCH §8.7) expires any v1/v2 match still in the DB.
RULESET_VERSION = 3
TURN_DURATION_SECONDS = 30
# BattleV4 currently applies the resolved state without frame-by-frame animation,
# so no animation budget is added to the next planning deadline. Restore the
# buffer limit when event-by-event animations return.
RESOLVE_STEP_SECONDS = 0.85
MAX_RESOLVE_BUFFER_SECONDS = 0
