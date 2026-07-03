BOARD_ROWS = 5
BOARD_COLS = 3
HERO_HP = 20
MANA_CAP = 10
RULESET_VERSION = 1
TURN_DURATION_SECONDS = 30
# After a turn resolves, the next planning deadline is pushed back by a budget
# that covers the client-side resolution animation, so animating micro-steps
# never eats into a player's planning time (the turn timer stays frozen until
# the animation is done). Scaled by the number of emitted combat events.
RESOLVE_STEP_SECONDS = 0.85
MAX_RESOLVE_BUFFER_SECONDS = 22
