BOARD_ROWS = 5
BOARD_COLS = 3
HERO_HP = 20
MANA_CAP = 10
# v3: combat engine v4 goes live (stances, 5 towers, phased resolver,
# data-driven cards). The state shape changed again (BattleStateV4); the
# ruleset gate (ARCH §8.7) expires any v1/v2 match still in the DB.
RULESET_VERSION = 3
TURN_DURATION_SECONDS = 30
# Эндшпиль (DESIGN §3.5): начиная с этого хода время планирования падает на
# 1 с за ход, но не ниже пола. Оба числа — балансные ручки O10.
TURN_TIMER_SHRINK_START_TURN = 15
TURN_TIMER_FLOOR_SECONDS = 10
# Время на клиентскую анимацию: таймер следующего планирования не идёт, пока
# клиент последовательно проигрывает серверные combat events.
RESOLVE_STEP_SECONDS = 0.85
MAX_RESOLVE_BUFFER_SECONDS = 12
