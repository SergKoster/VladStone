import React from "react";

export function useServerResource<T>(
  load: () => Promise<T>,
  deps: React.DependencyList,
  initialData: T,
) {
  const [data, setData] = React.useState<T>(initialData);
  const [error, setError] = React.useState<unknown>(null);
  const [isLoading, setIsLoading] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const nextData = await load();
      setData(nextData);
      return nextData;
    } catch (nextError) {
      setError(nextError);
      throw nextError;
    } finally {
      setIsLoading(false);
    }
  }, deps);

  React.useEffect(() => {
    void refresh().catch(() => undefined);
  }, [refresh]);

  return { data, error, isLoading, refresh, setData };
}
