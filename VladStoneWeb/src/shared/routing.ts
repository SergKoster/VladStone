import React from "react";

export type StaticRoute = "dashboard" | "collection";
export type AppRoute =
  | { page: StaticRoute }
  | { page: "profile"; handle?: string }
  | { page: "battle"; matchId?: string }
  | { page: "quick" }
  | { page: "invite"; token: string }
  | { page: "lobby"; matchId: string };

export type RouteTarget = StaticRoute | "battle" | "quick" | AppRoute;

const staticRoutes: StaticRoute[] = ["dashboard", "collection"];

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
  if (page === "quick") return { page };
  if (page === "invite" && validSegment(value)) return { page, token: value };
  if (page === "lobby" && validSegment(value)) return { page, matchId: value };
  if (page === "profile") return { page, handle: validSegment(value) ? value : undefined };
  return staticRoutes.includes(page as StaticRoute) ? { page: page as StaticRoute } : { page: defaultRoute };
}

function hashForRoute(route: AppRoute): string {
  if (route.page === "battle" && route.matchId) return `battle/${route.matchId}`;
  if (route.page === "quick") return "quick";
  if (route.page === "invite") return `invite/${route.token}`;
  if (route.page === "lobby") return `lobby/${route.matchId}`;
  if (route.page === "profile" && route.handle) return `profile/${route.handle}`;
  return route.page;
}

function validSegment(value: string | undefined): value is string {
  return Boolean(value && /^[A-Za-z0-9_-]{1,128}$/.test(value));
}
