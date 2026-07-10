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

export type CollectionCard = {
  id: string;
  name: string;
  cost: number;
  rarity: Rarity;
  hp: number;
  damage: number;
  range: number;
  steps: number;
  attacks: number;
  copies: number;
  ascension: "Дефолт" | "Возвышенный" | "Возвышенный+";
};

export type CombatUnit = {
  id: string;
  owner_id: string;
  side: "top" | "bottom";
  card_id: string;
  position: { row: number; col: number };
  current_hp: number;
  remaining_steps: number;
  remaining_attacks: number;
  stats: {
    hp: number;
    damage: number;
    attack_range: number;
    move_steps: number;
    attacks: number;
    action_priority: string;
  };
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
    | "fizzled";
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
  snapshot: {
    players?: CombatSnapshotPlayer[];
    units?: CombatUnit[];
  };
};

/** Player slice inside event snapshots: hero/mana state only — no hand/deck. */
export type CombatSnapshotPlayer = {
  id: string;
  side: "top" | "bottom";
  mana: number;
  hero: { owner_id: string; side: "top" | "bottom"; hp: number };
};

export type CombatMatch = {
  id: string;
  ruleset_version: number;
  status: "planning" | "resolving" | "finished" | "expired";
  turn: number;
  rows: number;
  cols: number;
  mana_cap: number;
  planning_deadline: string | null;
  players: Array<{
    id: string;
    side: "top" | "bottom";
    /** Team index; allies share a team, the enemy is any other team. */
    team: number;
    is_bot: boolean;
    mana: number;
    hero: { owner_id: string; side: "top" | "bottom"; hp: number };
    /** Server-authoritative hand — populated only for the viewer's own seat. */
    hand: string[];
    hand_count: number;
    /** Cards left in the deck; order and contents are a server-side secret. */
    deck_count: number;
  }>;
  /** Which seat this payload was serialized for (the client's own player). */
  viewer_id: string | null;
  units: CombatUnit[];
  log: Array<{ message: string }>;
  events: CombatEvent[];
  result: {
    /** "expired" — матч закрыт сервером (напр. сменились правила боя), не проигрыш. */
    status: "active" | "finished" | "expired";
    winner_id: string | null;
    reward_coins: number;
  };
};

export type CombatResponse = {
  match: CombatMatch;
  events: CombatEvent[];
};

export type MatchSocketMessage =
  | ({ type: "match.snapshot" | "match.updated" } & CombatResponse)
  | { type: "pong" };

export type Placement = {
  card_id: string;
  row: number;
  col: number;
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

export function getCardCatalog() {
  return request<{ cards: CollectionCard[] }>("/combat/catalog");
}

export function getCollection() {
  return request<{ cards: CollectionCard[] }>("/me/collection");
}

export function ascendCard(cardId: string, ascension = "default") {
  return request<{ cards: CollectionCard[] }>(`/me/collection/${cardId}/ascend`, {
    method: "POST",
    body: JSON.stringify({ ascension }),
  });
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

export function resolveCombat(matchId: string, turn: number, placements: Placement[]) {
  return request<CombatResponse>("/combat/resolve", {
    method: "POST",
    body: JSON.stringify({ match_id: matchId, turn, placements }),
  });
}

export function createMatchSocket(matchId: string) {
  return createWebSocket(`/ws/matches/${matchId}`);
}

export function logClientEvent(event: string, payload: Record<string, unknown>) {
  sendClientEvent(event, payload);
}
