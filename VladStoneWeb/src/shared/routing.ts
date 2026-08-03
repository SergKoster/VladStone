import React from "react";

export type StaticRoute = "dashboard" | "collection" | "profile";
export type AppRoute =
  | { page: StaticRoute }
  | { page: "battle"; matchId?: string }
  | { page: "invite"; token: string }
  | { page: "lobby"; matchId: string };

export type RouteTarget = StaticRoute | "battle" | AppRoute;

const staticRoutes: StaticRoute[] = ["dashboard", "collection", "profile"];

export function useHashRoute(defaultRoute: StaticRoute = "dashboard") {
  const [route, setRouteState] = React.useState<AppRoute>(() => readHashRoute(defaultRoute));

  React.useEffect(() => {
    const handleHashChange = () => setRouteState(readHashRoute(defaultRoute));
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, [defaultRoute]);

  function setRoute(target: RouteTarget) {
    const route: AppRoute = typeof target === "string" ? { page: target } : target;
    window.location.hash = hashForRoute(route);
    setRouteState(route);
  }

  return [route, setRoute] as const;
}

function readHashRoute(defaultRoute: StaticRoute): AppRoute {
  const route = window.location.hash.replace(/^#\/?/, "");
  const [page, value] = route.split("/", 2);
  if (page === "battle") return { page, matchId: validSegment(value) ? value : undefined };
  if (page === "invite" && validSegment(value)) return { page, token: value };
  if (page === "lobby" && validSegment(value)) return { page, matchId: value };
  return staticRoutes.includes(page as StaticRoute) ? { page: page as StaticRoute } : { page: defaultRoute };
}

function hashForRoute(route: AppRoute): string {
  if (route.page === "battle" && route.matchId) return `battle/${route.matchId}`;
  if (route.page === "invite") return `invite/${route.token}`;
  if (route.page === "lobby") return `lobby/${route.matchId}`;
  return route.page;
}

function validSegment(value: string | undefined): value is string {
  return Boolean(value && /^[A-Za-z0-9_-]{1,128}$/.test(value));
}
