import React from "react";
import { createRoot } from "react-dom/client";

import "./styles.css";
import {
  type AuthProviders,
  type AuthUser,
  type CombatCatalogCard,
  type CombatMatch,
  type CombatStatusDefinition,
  type CollectionCard,
  type PublicProfileResponse,
  getAuthProviders,
  getCollection,
  getCombatCatalog,
  getActiveCombats,
  getMe,
  getPublicProfile,
  createMatchInvite,
  googleDevLogin,
  googleLoginUrl,
  logout,
  requestEmailCode,
  updateMyHandle,
  verifyEmailCode,
} from "./api";
import { AuthScreen } from "./features/auth/AuthScreen";
import { BattleV4 } from "./features/battle/BattleV4";
import { Collection } from "./features/collection/Collection";
import { Dashboard } from "./features/dashboard/Dashboard";
import { CreatedInviteLobby, JoinInvite, PENDING_INVITE_ROUTE_KEY } from "./features/invite/InviteLobby";
import { QuickMatch } from "./features/matchmaking/QuickMatch";
import { Friends } from "./features/social/Friends";
import { Profile } from "./features/profile/Profile";
import { HandleOnboarding } from "./features/profile/HandleOnboarding";
import { t } from "./i18n";
import { useHashRoute } from "./shared/routing";
import { useServerResource } from "./shared/serverState";

type BattleSidebarControls = {
  start: () => void;
  startDisabled: boolean;
  surrender: () => void;
  surrenderDisabled: boolean;
};

function App() {
  const [route, setRoute] = useHashRoute();
  const [email, setEmail] = React.useState("");
  const [code, setCode] = React.useState("");
  const [devCode, setDevCode] = React.useState<string | null>(null);
  const [authUser, setAuthUser] = React.useState<AuthUser | null>(null);
  const [authMessage, setAuthMessage] = React.useState("");
  const [inviteMessage, setInviteMessage] = React.useState("");
  const [battleSidebarControls, setBattleSidebarControls] =
    React.useState<BattleSidebarControls | null>(null);
  const [sessionChecked, setSessionChecked] = React.useState(false);
  const [providers, setProviders] = React.useState<AuthProviders | null>(null);

  React.useEffect(() => {
    // The refresh cookie may already hold a live session: page reload or the
    // return leg of the Google OAuth redirect. Restore it before showing auth.
    getMe()
      .then((profile) => setAuthUser({ id: profile.id, email: profile.email }))
      .catch(() => undefined)
      .finally(() => setSessionChecked(true));
    getAuthProviders()
      .then(setProviders)
      .catch(() => undefined);
    const params = new URLSearchParams(window.location.search);
    if (params.get("auth_error")) {
      setAuthMessage("Не удалось войти через Google. Попробуй еще раз.");
      params.delete("auth_error");
      const query = params.toString();
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
      );
    }
  }, []);
  React.useEffect(() => {
    if (!authUser) return;
    const pendingRoute = window.sessionStorage.getItem(PENDING_INVITE_ROUTE_KEY);
    if (pendingRoute && window.location.hash !== pendingRoute) {
      window.location.hash = pendingRoute;
    }
  }, [authUser]);
  const profileState = useServerResource(
    () => (authUser ? getMe() : Promise.resolve(null)),
    [authUser?.id],
    null,
  );
  const publicHandle = route.page === "profile" ? route.handle : undefined;
  const publicProfileState = useServerResource<PublicProfileResponse | null>(
    () => (publicHandle ? getPublicProfile(publicHandle) : Promise.resolve(null)),
    [publicHandle],
    null,
  );
  const collectionState = useServerResource<CollectionCard[]>(
    () => (authUser ? getCollection().then((payload) => payload.cards) : Promise.resolve([])),
    [authUser?.id],
    [],
  );
  // Combat catalog (v4): battle needs card data (art, cost, coverage, spawn
  // zone) for any card id — hand, spells, bot units — regardless of ownership.
  const catalogState = useServerResource<{
    cards: CombatCatalogCard[];
    statuses: CombatStatusDefinition[];
  }>(
    getCombatCatalog,
    [],
    { cards: [], statuses: [] },
  );
  const profile = profileState.data;
  const collection = collectionState.data;
  const catalog = catalogState.data.cards;
  const statusCatalog = catalogState.data.statuses;

  React.useEffect(() => {
    publicProfileState.setData(null);
  }, [publicHandle]);

  React.useEffect(() => {
    if (
      route.page === "profile" &&
      route.handle &&
      publicProfileState.data &&
      route.handle !== publicProfileState.data.handle
    ) {
      setRoute({ page: "profile", handle: publicProfileState.data.handle });
    }
  }, [publicProfileState.data, route, setRoute]);

  // API may still be starting while Vite is already reachable. Do not leave
  // the battle with an empty catalog forever after that first transient error:
  // unknown hand cards would otherwise render as spell fallbacks and be
  // impossible to plan.
  React.useEffect(() => {
    if (catalog.length > 0) return undefined;
    const retry = window.setInterval(() => {
      void catalogState.refresh().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(retry);
  }, [catalog.length, catalogState.refresh]);

  async function handleRequestCode() {
    setAuthMessage("");
    try {
      const response = await requestEmailCode(email);
      setDevCode(response.dev_code);
      setAuthMessage("Код создан. В dev-режиме он показан ниже.");
    } catch {
      setAuthMessage("Не удалось получить код. Проверь, что API запущен.");
    }
  }

  async function handleVerifyCode() {
    setAuthMessage("");
    try {
      const response = await verifyEmailCode(email, code);
      setAuthUser(response.user);
    } catch {
      setAuthMessage("Код не подошел или истек.");
    }
  }

  async function handleGoogleLogin() {
    if (providers?.google) {
      if (route.page === "invite") {
        window.sessionStorage.setItem(PENDING_INVITE_ROUTE_KEY, window.location.hash);
      }
      // Real OAuth: leave the app entirely; we come back with the cookie set.
      window.location.href = googleLoginUrl();
      return;
    }
    const loginEmail = email || "google-player@example.com";
    try {
      const response = await googleDevLogin(loginEmail);
      setEmail(loginEmail);
      setAuthUser(response.user);
    } catch {
      setAuthMessage("Не удалось войти через Google dev login.");
    }
  }

  async function handleLogout() {
    await logout().catch(() => undefined);
    setAuthUser(null);
    profileState.setData(null);
    collectionState.setData([]);
    setCode("");
    setDevCode(null);
    setRoute("dashboard");
  }

  async function handleSetHandle(handle: string) {
    const updated = await updateMyHandle(handle);
    profileState.setData(updated);
  }

  async function handleRename(handle: string) {
    const updated = await updateMyHandle(handle);
    profileState.setData(updated);
    publicProfileState.setData(null);
    setRoute({ page: "profile", handle: updated.handle ?? undefined });
  }

  const openExistingMatch = React.useCallback(
    (match: CombatMatch) => {
      setRoute(
        match.status === "waiting_for_opponent"
          ? { page: "lobby", matchId: match.id }
          : { page: "battle", matchId: match.id },
      );
    },
    [setRoute],
  );

  async function handleQuickMatched(matchId: string) {
    const active = await getActiveCombats()
      .then((payload) => payload.matches.find((match) => match.id === matchId) ?? null)
      .catch(() => null);
    if (active) {
      openExistingMatch(active);
    } else {
      setRoute({ page: "battle", matchId });
    }
  }

  async function handleCreateInvite() {
    setInviteMessage("");
    try {
      const response = await createMatchInvite();
      window.sessionStorage.setItem(`vladstone.invite.${response.match.id}`, response.invite.share_path);
      setRoute({ page: "lobby", matchId: response.match.id });
    } catch {
      const existing = await getActiveCombats()
        .then((payload) => payload.matches[0] ?? null)
        .catch(() => null);
      if (existing) {
        openExistingMatch(existing);
      } else {
        setInviteMessage("Не удалось создать приглашение. Попробуй ещё раз.");
      }
    }
  }

  const handleBattleControlsChange = React.useCallback(
    (controls: BattleSidebarControls | null) => setBattleSidebarControls(controls),
    [],
  );

  if (!sessionChecked) {
    // Blank flash instead of a misleading login screen while we ask the
    // server whether the cookie is still a valid session.
    return null;
  }

  if (!authUser && route.page === "profile" && route.handle) {
    return publicProfileState.data ? (
      <main className="public-profile-shell">
        <Profile profile={publicProfileState.data} />
      </main>
    ) : null;
  }

  if (!authUser) {
    return (
      <AuthScreen
        authMessage={authMessage}
        code={code}
        devCode={devCode}
        email={email}
        emailEnabled={providers === null || providers.email_code}
        googleEnabled={providers === null || providers.google || providers.dev_login}
        onCodeChange={setCode}
        onEmailChange={setEmail}
        onGoogleLogin={handleGoogleLogin}
        onRequestCode={handleRequestCode}
        onVerifyCode={handleVerifyCode}
      />
    );
  }

  if (profile === null) return null;
  if (profile.onboarding_required || !profile.handle) {
    return <HandleOnboarding onSubmit={handleSetHandle} />;
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div>
          <p className="brand">{t.appName}</p>
          <p className="muted">MVP dev build</p>
        </div>
        <nav>
          <NavButton active={route.page === "dashboard"} onClick={() => setRoute("dashboard")}>
            {t.dashboard}
          </NavButton>
          <NavButton active={route.page === "collection"} onClick={() => setRoute("collection")}>
            {t.collection}
          </NavButton>
          <NavButton active={route.page === "friends"} onClick={() => setRoute("friends")}>
            Друзья
          </NavButton>
          <NavButton active={route.page === "battle"} onClick={() => setRoute("battle")}>
            {t.battle}
          </NavButton>
          <NavButton
            active={route.page === "profile"}
            onClick={() => setRoute({ page: "profile", handle: profile.handle ?? undefined })}
          >
            {t.profile}
          </NavButton>
        </nav>
        {route.page === "battle" ? (
          <div aria-label="Действия боя" className="battle-sidebar-controls">
            <button
              className="secondary"
              disabled={battleSidebarControls?.startDisabled ?? true}
              onClick={() => battleSidebarControls?.start()}
            >
              Новый бой
            </button>
            <button
              className="battle-surrender"
              disabled={battleSidebarControls?.surrenderDisabled ?? true}
              onClick={() => battleSidebarControls?.surrender()}
            >
              Сдаться
            </button>
          </div>
        ) : null}
        <button className="secondary" onClick={handleLogout}>
          Выйти
        </button>
      </aside>
      {/* U2: у маршрута боя свой layout-модификатор — широкий экран отдан бою,
          остальные страницы сохраняют прежнюю ширину (.page). */}
      <section className={route.page === "battle" ? "content content-battle" : "content"}>
        {route.page === "dashboard" && (
          <Dashboard
            coins={profile?.coins ?? 0}
            collectionCount={new Set(collection.map((card) => card.id)).size}
            collectionTotal={catalog.length}
            onInvite={() => void handleCreateInvite()}
            onPlay={() => setRoute("battle")}
            onQuick={() => setRoute("quick")}
            message={inviteMessage}
          />
        )}
        {route.page === "collection" && (
          <Collection
            cards={collection}
            catalog={catalog}
          />
        )}
        {route.page === "friends" && (
          <Friends onBattle={(matchId) => setRoute({ page: "battle", matchId })} />
        )}
        {route.page === "battle" && (
          <BattleV4
            key={route.matchId ?? "active-or-pve"}
            cards={catalog}
            initialMatchId={route.matchId}
            onBattleControlsChange={handleBattleControlsChange}
            onExistingMatch={openExistingMatch}
            statuses={statusCatalog}
            onBattleFinished={() => profileState.refresh().catch(() => undefined)}
          />
        )}
        {route.page === "lobby" && (
          <CreatedInviteLobby
            matchId={route.matchId}
            onBack={() => setRoute("dashboard")}
            onStarted={() => setRoute({ page: "battle", matchId: route.matchId })}
          />
        )}
        {route.page === "invite" && (
          <JoinInvite
            token={route.token}
            onBack={() => setRoute("dashboard")}
            onExistingMatch={openExistingMatch}
            onJoined={(matchId) => setRoute({ page: "battle", matchId })}
          />
        )}
        {route.page === "quick" && (
          <QuickMatch
            onBack={() => setRoute("dashboard")}
            onMatched={(matchId) => void handleQuickMatched(matchId)}
          />
        )}
        {route.page === "profile" && (
          <Profile
            email={publicProfileState.data?.handle === profile.handle ? profile.email : undefined}
            onRename={publicProfileState.data?.handle === profile.handle ? handleRename : undefined}
            profile={
              publicProfileState.data ?? {
                handle: profile.handle,
                avatar_key: null,
                created_at: profile.created_at,
                collection: {
                  owned: new Set(collection.map((card) => card.id)).size,
                  total: catalog.length,
                },
              }
            }
          />
        )}
      </section>
    </main>
  );
}

function NavButton(props: React.PropsWithChildren<{ active: boolean; onClick: () => void }>) {
  return (
    <button className={props.active ? "nav-button active" : "nav-button"} onClick={props.onClick}>
      {props.children}
    </button>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
