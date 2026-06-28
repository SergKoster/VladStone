import React from "react";

export type AppRoute = "dashboard" | "collection" | "battle" | "profile";

const routes: AppRoute[] = ["dashboard", "collection", "battle", "profile"];

export function useHashRoute(defaultRoute: AppRoute = "dashboard") {
  const [route, setRouteState] = React.useState<AppRoute>(() => readHashRoute(defaultRoute));

  React.useEffect(() => {
    const handleHashChange = () => setRouteState(readHashRoute(defaultRoute));
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, [defaultRoute]);

  function setRoute(nextRoute: AppRoute) {
    window.location.hash = nextRoute;
    setRouteState(nextRoute);
  }

  return [route, setRoute] as const;
}

function readHashRoute(defaultRoute: AppRoute) {
  const route = window.location.hash.replace("#", "");
  return routes.includes(route as AppRoute) ? (route as AppRoute) : defaultRoute;
}
