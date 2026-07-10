BOARD_ROWS = 5
BOARD_COLS = 3
HERO_HP = 20
MANA_CAP = 10
# v2: participant model (R12) — per-player deck/hand/team, no "player"/"bot"
# hardcode. Matches saved under v1 keep a state shape the new code no longer
# plays; the ruleset gate (ARCH §8.7) expires them.
RULESET_VERSION = 2
TURN_DURATION_SECONDS = 30
# After a turn resolves, the next planning deadline is pushed back by a budget
# that covers the client-side resolution animation, so animating micro-steps
# never eats into a player's planning time (the turn timer stays frozen until
# the animation is done). Scaled by the number of emitted combat events.
RESOLVE_STEP_SECONDS = 0.85
MAX_RESOLVE_BUFFER_SECONDS = 22
