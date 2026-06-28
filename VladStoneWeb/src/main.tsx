import React from "react";
import { createRoot } from "react-dom/client";

import "./styles.css";
import {
  type AuthUser,
  type CollectionCard,
  getCollection,
  getMe,
  googleDevLogin,
  logout,
  requestEmailCode,
  verifyEmailCode,
} from "./api";
import { AuthScreen } from "./features/auth/AuthScreen";
import { Battle } from "./features/battle/Battle";
import { Collection } from "./features/collection/Collection";
import { Dashboard } from "./features/dashboard/Dashboard";
import { Profile } from "./features/profile/Profile";
import { t } from "./i18n";
import { starterCards } from "./shared/cards";
import { useHashRoute } from "./shared/routing";
import { useServerResource } from "./shared/serverState";

function App() {
  const [route, setRoute] = useHashRoute();
  const [email, setEmail] = React.useState("");
  const [code, setCode] = React.useState("");
  const [devCode, setDevCode] = React.useState<string | null>(null);
  const [authUser, setAuthUser] = React.useState<AuthUser | null>(null);
  const [authMessage, setAuthMessage] = React.useState("");
  const profileState = useServerResource(
    () => (authUser ? getMe() : Promise.resolve(null)),
    [authUser?.id],
    null,
  );
  const collectionState = useServerResource<CollectionCard[]>(
    () => (authUser ? getCollection().then((payload) => payload.cards) : Promise.resolve(starterCards)),
    [authUser?.id],
    starterCards,
  );
  const profile = profileState.data;
  const collection = collectionState.data;

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

  async function handleGoogleDevLogin() {
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
    collectionState.setData(starterCards);
    setCode("");
    setDevCode(null);
    setRoute("dashboard");
  }

  if (!authUser) {
    return (
      <AuthScreen
        authMessage={authMessage}
        code={code}
        devCode={devCode}
        email={email}
        onCodeChange={setCode}
        onEmailChange={setEmail}
        onGoogleLogin={handleGoogleDevLogin}
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
          <NavButton active={route === "dashboard"} onClick={() => setRoute("dashboard")}>
            {t.dashboard}
          </NavButton>
          <NavButton active={route === "collection"} onClick={() => setRoute("collection")}>
            {t.collection}
          </NavButton>
          <NavButton active={route === "battle"} onClick={() => setRoute("battle")}>
            {t.battle}
          </NavButton>
          <NavButton active={route === "profile"} onClick={() => setRoute("profile")}>
            {t.profile}
          </NavButton>
        </nav>
        <button className="secondary" onClick={handleLogout}>
          Выйти
        </button>
      </aside>
      <section className="content">
        {route === "dashboard" && (
          <Dashboard
            coins={profile?.coins ?? 0}
            collectionCount={new Set(collection.map((card) => card.id)).size}
            onPlay={() => setRoute("battle")}
          />
        )}
        {route === "collection" && (
          <Collection cards={collection} onCollectionChange={collectionState.setData} />
        )}
        {route === "battle" && (
          <Battle onBattleFinished={() => profileState.refresh().catch(() => undefined)} />
        )}
        {route === "profile" && (
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
