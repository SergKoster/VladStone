import { type CombatResponse, type MatchSocketMessage, createMatchSocket } from "../../api";

export type MatchRealtimeStatus =
  | "Realtime не подключен"
  | "Realtime подключается..."
  | "Realtime подключен"
  | "Realtime переподключается...";

export function connectMatchRealtime({
  matchId,
  getResumeCursor,
  onSnapshot,
  onStatus,
  onUpdate,
}: {
  matchId: string;
  getResumeCursor?: () => { turn: number; sequence: number } | null;
  onSnapshot: (payload: CombatResponse) => void;
  onStatus: (status: MatchRealtimeStatus) => void;
  onUpdate: (payload: CombatResponse) => void;
}) {
  let socket: WebSocket | null = null;
  let reconnectTimerId: number | undefined;
  let pingTimerId: number | undefined;
  let reconnectAttempt = 0;
  let didCloseIntentionally = false;

  const connect = () => {
    onStatus("Realtime подключается...");
    socket = createMatchSocket(matchId, getResumeCursor?.() ?? null);
    socket.onopen = () => {
      reconnectAttempt = 0;
      onStatus("Realtime подключен");
      pingTimerId = window.setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }));
        }
      }, 10000);
    };
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as MatchSocketMessage;
      if (message.type === "pong") {
        return;
      }
      if (message.type === "match.snapshot") {
        onSnapshot(message);
        return;
      }
      onUpdate(message);
    };
    socket.onclose = () => {
      if (pingTimerId) {
        window.clearInterval(pingTimerId);
      }
      if (didCloseIntentionally) {
        return;
      }
      onStatus("Realtime переподключается...");
      const delay = Math.min(1000 * 2 ** reconnectAttempt, 10000);
      reconnectAttempt += 1;
      reconnectTimerId = window.setTimeout(connect, delay);
    };
    socket.onerror = () => {
      socket?.close();
    };
  };

  connect();

  return () => {
    didCloseIntentionally = true;
    if (reconnectTimerId) {
      window.clearTimeout(reconnectTimerId);
    }
    if (pingTimerId) {
      window.clearInterval(pingTimerId);
    }
    socket?.close();
  };
}
