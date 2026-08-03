import React from "react";
import { createRoot } from "react-dom/client";

import "./styles.css";
import {
  type AuthProviders,
  type AuthUser,
  type CombatCatalogCard,
  type CombatStatusDefinition,
  type CollectionCard,
  getAuthProviders,
  getCollection,
  getCombatCatalog,
  getMe,
  createMatchInvite,
  googleDevLogin,
  googleLoginUrl,
  logout,
  requestEmailCode,
  verifyEmailCode,
} from "./api";
import { AuthScreen } from "./features/auth/AuthScreen";
import { BattleV4 } from "./features/battle/BattleV4";
import { Collection } from "./features/collection/Collection";
import { Dashboard } from "./features/dashboard/Dashboard";
import { CreatedInviteLobby, JoinInvite, PENDING_INVITE_ROUTE_KEY } from "./features/invite/InviteLobby";
import { Profile } from "./features/profile/Profile";
import { t } from "./i18n";
import { useHashRoute } from "./shared/routing";
import { useServerResource } from "./shared/serverState";

function App() {
  const [route, setRoute] = useHashRoute();
  const [email, setEmail] = React.useState("");
  const [code, setCode] = React.useState("");
  const [devCode, setDevCode] = React.useState<string | null>(null);
  const [authUser, setAuthUser] = React.useState<AuthUser | null>(null);
  const [authMessage, setAuthMessage] = React.useState("");
  const [inviteMessage, setInviteMessage] = React.useState("");
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

  async function handleCreateInvite() {
    setInviteMessage("");
    try {
      const response = await createMatchInvite();
      window.sessionStorage.setItem(`vladstone.invite.${response.match.id}`, response.invite.share_path);
      setRoute({ page: "lobby", matchId: response.match.id });
    } catch {
      setInviteMessage("Не удалось создать приглашение. Попробуй ещё раз.");
    }
  }

  if (!sessionChecked) {
    // Blank flash instead of a misleading login screen while we ask the
    // server whether the cookie is still a valid session.
    return null;
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
          <NavButton active={route.page === "battle"} onClick={() => setRoute("battle")}>
            {t.battle}
          </NavButton>
          <NavButton active={route.page === "profile"} onClick={() => setRoute("profile")}>
            {t.profile}
          </NavButton>
        </nav>
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
            onInvite={() => void handleCreateInvite()}
            onPlay={() => setRoute("battle")}
            message={inviteMessage}
          />
        )}
        {route.page === "collection" && (
          <Collection
            cards={collection}
            catalog={catalog}
          />
        )}
        {route.page === "battle" && (
          <BattleV4
            key={route.matchId ?? "active-or-pve"}
            cards={catalog}
            initialMatchId={route.matchId}
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
            onJoined={(matchId) => setRoute({ page: "battle", matchId })}
          />
        )}
        {route.page === "profile" && (
          <Profile
            createdAt={profile?.created_at}
            email={profile?.email ?? authUser.email}
            nickname={profile?.nickname ?? "Player"}
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
