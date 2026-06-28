const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8001/api";
const WS_BASE_URL =
  import.meta.env.VITE_WS_BASE_URL ?? API_BASE_URL.replace(/^http/, "ws").replace(/\/api$/, "");

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function createWebSocket(path: string) {
  return new WebSocket(`${WS_BASE_URL}${path}`);
}

export function sendClientEvent(event: string, payload: Record<string, unknown>) {
  void fetch(`${API_BASE_URL}/telemetry/client-events`, {
    method: "POST",
    credentials: "include",
    keepalive: true,
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ event, payload }),
  }).catch(() => undefined);
}
