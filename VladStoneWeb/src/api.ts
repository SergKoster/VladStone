import { API_BASE_URL, createWebSocket, request, sendClientEvent } from "./shared/apiClient";

export type AuthUser = {
  id: number;
  email: string;
};

export type AuthResponse = {
  access_token: string;
  user: AuthUser;
};

export type ProfileResponse = {
  id: number;
  email: string;
  nickname: string;
  coins: number;
  created_at: string;
};

export type Rarity = "common" | "uncommon" | "rare" | "epic" | "legendary";

export type CollectionCard = CombatCatalogCard & {
  copies: number;
};

export type CombatStance = "attack" | "defense";

export type CombatUnitStatus = { id: string; stacks: number; ttl: number | null };

/** Юнит боя v4: позиция row/col, стойка, статусы, флаг башни. */
export type CombatUnit = {
  id: string;
  owner_id: string;
  side: "top" | "bottom";
  blueprint_id: string;
  /** id карты для арта; у башен null. */
  card_id: string | null;
  row: number;
  col: number;
  current_hp: number;
  max_hp: number;
  damage: number;
  move_steps: number;
  attacks_per_turn: number;
  stance: CombatStance;
  /** V6: ходов (включая текущий) до самостоятельной смены стойки; null = не сменится. */
  stance_turns_left: number | null;
  is_tower: boolean;
  statuses: CombatUnitStatus[];
  remaining_steps: number;
  remaining_attacks: number;
};

/** Постоянный слот башни линии; уничтоженная башня не возвращается в units. */
export type CombatTowerSlot = {
  owner_id: string;
  side: "top" | "bottom";
  col: number;
  status: "alive" | "destroyed";
  tower_id: string;
  blueprint_id: string;
  current_hp: number;
  max_hp: number;
};

/** Карта каталога боя v4 (/combat/catalog): арт, статы, покрытия, зона спавна. */
export type CombatCatalogCard = {
  id: string;
  name: string;
  cost: number;
  rarity: Rarity;
  card_type: "unit" | "spell";
  /** Утверждённое серверное описание механики, общее для боя и коллекции. */
  rules_text: string;
  board: { rows: number; cols: number };
  stats?: { hp: number; damage: number; attacks_per_turn: number; move_steps: number };
  coverage_attack?: Array<{ forward: number; col: number }>;
  coverage_defense?: Array<{ forward: number; col: number }>;
  /** Ряды зоны спавна, считая от своего края (1 = задний). */
  spawn_rows?: number[];
  damage_defense?: number | null;
  spell_id?: string;
};

/** Публичное объяснение status id для боевого UI; длительность берётся с юнита. */
export type CombatStatusDefinition = {
  id: string;
  name: string;
  description: string;
  icon: string;
  decay: "ttl" | "stacks" | "permanent";
};

export type CombatEvent = {
  type:
    | "spawn"
    | "spawn_blocked"
    | "push"
    | "move"
    | "move_blocked"
    | "attack"
    | "damage"
    | "collision"
    | "collision_step"
    | "death"
    | "hero_hit"
    | "match_finished"
    // События движка v4 (P2.12): до подмены движка сервер их не шлёт;
    // проигрыватель обрабатывает неизвестные типы общим путём (снапшот+лог).
    | "heal"
    | "spell_cast"
    | "stance_changed"
    | "status_applied"
    | "status_expired"
    | "ability_triggered"
    | "tag_granted"
    | "executed"
    | "card_drawn"
    | "mana_changed"
    | "fizzled"
    | "stat_buffed"
    | "budget_modified"
    | "unit_waited";
  message: string;
  actor_id: string | null;
  target_id: string | null;
  target_kind: "unit" | "hero" | "cell" | "match" | null;
  damage: number | null;
  from_position: { row: number; col: number } | null;
  to_position: { row: number; col: number } | null;
  before_hp: number | null;
  after_hp: number | null;
  sequence: number | null;
  micro_step: number | null;
  /** Фаза хода v4 (spells/spawn/iterations/end/draw); у MVP-событий null. */
  phase?: string | null;
  /** Структурный хук способности: нужен для отличия спавна от смерти. */
  ability_trigger?: string | null;
  /** Примитив эффекта способности, например deal_damage или heal. */
  effect_kind?: string | null;
  /** Серверная причина, почему юнит не совершил действия за ход (U1). */
  wait_reason?:
    | "defense_no_target"
    | "attack_no_target"
    | "path_blocked"
    | "no_action_budget"
    | null;
  /** V9: структурные данные статуса (status_applied/expired) для попапа. */
  status_id?: string | null;
  status_stacks?: number | null;
  /** V7: карта видимого розыгрыша (spell_cast/spawn); у скрытых событий null. */
  card_id?: string | null;
  /** Полная область визуального эффекта, включая пустые клетки поля. */
  affected_cells: Array<{ row: number; col: number }>;
  snapshot: CombatEventSnapshot;
};

/** Облегчённый срез игрока внутри снапшота события. */
export type CombatSnapshotPlayer = {
  id: string;
  mana: number;
  /** U3: публичные счётчики для покадровой стопки колоды. Optional — снапшоты
      ходов, сохранённые до этого поля, докатываются из состояния матча. */
  deck_count?: number;
  hand_count?: number;
};

/** Облегчённый юнит снапшота A1; остальные поля берутся из состояния матча. */
export type CombatSnapshotUnit = {
  id: string;
  card_id: string | null;
  side: "top" | "bottom";
  row: number;
  col: number;
  current_hp: number;
  max_hp: number;
  stance: CombatStance;
  /** V6: optional — снапшоты, сохранённые до поля, докатываются из состояния. */
  stance_turns_left?: number | null;
  is_tower: boolean;
  remaining_steps: number;
  remaining_attacks: number;
};

export type CombatEventSnapshot = {
  players: CombatSnapshotPlayer[];
  units: CombatSnapshotUnit[];
};

export type CombatMatch = {
  id: string;
  ruleset_version: number;
  status: "waiting_for_opponent" | "planning" | "resolving" | "finished" | "expired";
  turn: number;
  rows: number;
  cols: number;
  mana_cap: number;
  planning_deadline: string | null;
  /** Время планирования текущего хода, сек (эндшпиль сжимает — DESIGN §3.5).
      Серверное число: клиент капает им видимый таймер, формулу не дублирует. */
  planning_seconds: number;
  players: Array<{
    id: string;
    side: "top" | "bottom";
    /** Team index; allies share a team, the enemy is any other team. */
    team: number;
    is_bot: boolean;
    mana: number;
    /** Public confirmation state; the actual plan remains private. */
    ready: boolean;
    /** Server-authoritative hand — populated only for the viewer's own seat. */
    hand: string[];
    hand_count: number;
    /** Cards left in the deck; order and contents are a server-side secret. */
    deck_count: number;
  }>;
  /** Which seat this payload was serialized for (the client's own player). */
  viewer_id: string | null;
  units: CombatUnit[];
  /** Server-authoritative проекция пяти линий, включая разрушенные башни. */
  tower_slots: CombatTowerSlot[];
  log: Array<{ message: string }>;
  events: CombatEvent[];
  result: {
    /** "expired" — матч закрыт сервером (напр. сменились правила боя), не проигрыш. */
    status: "active" | "finished" | "expired";
    winner_id: string | null;
    winner_team: number | null;
    reward_coins: number;
  };
};

export type CombatResponse = {
  match: CombatMatch;
  events: CombatEvent[];
  /** Ход, породивший events; не выводится клиентом косвенно из match.turn. */
  resolved_turn: number | null;
  /** Последняя sequence полной ленты; часть ключа дедупликации HTTP/WS. */
  last_sequence: number | null;
};

export type MatchInviteResponse = {
  match: CombatMatch;
  invite: { share_path: string; expires_at: string; status: string };
};

export type MatchLobbyResponse = {
  match: CombatMatch;
  invite: { expires_at: string; status: string };
};

export type MatchSocketMessage =
  | ({ type: "match.snapshot" | "match.updated" } & CombatResponse)
  | { type: "pong" };

export type Placement = {
  card_id: string;
  row: number;
  col: number;
};

export type SpellCast = {
  card_id: string;
  row?: number | null;
  col?: number | null;
};

export function requestEmailCode(email: string) {
  return request<{ ok: boolean; dev_code: string | null }>("/auth/email/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function verifyEmailCode(email: string, code: string) {
  return request<AuthResponse>("/auth/email/verify", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });
}

export function googleDevLogin(email: string) {
  return request<AuthResponse>("/auth/google/dev-login", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export type AuthProviders = {
  google: boolean;
  dev_login: boolean;
  email_code: boolean;
};

export function getAuthProviders() {
  return request<AuthProviders>("/auth/providers");
}

// Real Google OAuth is a full-page redirect, not a fetch: the browser must
// follow the API -> Google -> API chain so Google can show its consent screen.
export function googleLoginUrl() {
  return `${API_BASE_URL}/auth/google/login`;
}

export function getMe() {
  return request<ProfileResponse>("/me");
}

export function getCombatCatalog() {
  return request<{ cards: CombatCatalogCard[]; statuses: CombatStatusDefinition[] }>(
    "/combat/catalog",
  );
}

export function getCollection() {
  return request<{ cards: CollectionCard[] }>("/me/collection");
}

export function logout() {
  return request<{ ok: boolean }>("/auth/logout", {
    method: "POST",
  });
}

export function startCombat() {
  return request<CombatResponse>("/combat/start", {
    method: "POST",
  });
}

export function getCombat(matchId: string) {
  return request<CombatResponse>(`/combat/${matchId}`);
}

export function getActiveCombats() {
  return request<{ matches: CombatMatch[] }>("/combat/active");
}

export function createMatchInvite() {
  return request<MatchInviteResponse>("/matches/invite", { method: "POST" });
}

export function joinMatchInvite(token: string) {
  return request<CombatResponse>("/matches/join", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export function getMatchLobby(matchId: string) {
  return request<MatchLobbyResponse>(`/matches/${matchId}/lobby`);
}

export function cancelMatchInvite(matchId: string) {
  return request<void>(`/matches/${matchId}/invite`, { method: "DELETE" });
}

// V3: интент-стриминг — сервер хранит последний план и применит его на
// дедлайне; клиент шлёт с debounce по мере планирования.
export function planCombat(
  matchId: string,
  turn: number,
  placements: Placement[],
  spells: SpellCast[] = [],
) {
  return request<{ ok: boolean; turn: number }>("/combat/plan", {
    method: "POST",
    body: JSON.stringify({ match_id: matchId, turn, placements, spells }),
  });
}

// V3: «Готов» (несёт финальный план атомарно) или снятие готовности.
// Резолв придёт по WS после окна бот-Готов (2 с).
export function readyCombat(
  matchId: string,
  turn: number,
  ready: boolean,
  placements: Placement[],
  spells: SpellCast[] = [],
) {
  return request<{ ok: boolean; turn: number; ready: boolean }>("/combat/ready", {
    method: "POST",
    body: JSON.stringify({ match_id: matchId, turn, ready, placements, spells }),
  });
}

export function resolveCombat(
  matchId: string,
  turn: number,
  placements: Placement[],
  spells: SpellCast[] = [],
) {
  return request<CombatResponse>("/combat/resolve", {
    method: "POST",
    body: JSON.stringify({ match_id: matchId, turn, placements, spells }),
  });
}

export function createMatchSocket(matchId: string) {
  return createWebSocket(`/ws/matches/${matchId}`);
}

export function logClientEvent(event: string, payload: Record<string, unknown>) {
  sendClientEvent(event, payload);
}
