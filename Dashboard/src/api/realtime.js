import { config } from "../config.js";

export function openPatientSocket(patientId, { token, onEvent, onStatus }) {
  if (!patientId) return () => {};

  let closedByClient = false;
  let socket = null;

  const connect = () => {
    onStatus?.("connecting");
    const encodedToken = token ? `?token=${encodeURIComponent(token)}` : "";
    socket = new WebSocket(`${config.wsBaseUrl}/patients/${patientId}${encodedToken}`);

    socket.onopen = () => onStatus?.("connected");
    socket.onmessage = (message) => {
      try {
        onEvent?.(JSON.parse(message.data));
      } catch {
        onStatus?.("invalid_event");
      }
    };
    socket.onerror = () => onStatus?.("error");
    socket.onclose = () => {
      if (!closedByClient) {
        onStatus?.("reconnecting");
        window.setTimeout(connect, 3000);
      }
    };
  };

  connect();

  return () => {
    closedByClient = true;
    if (socket) socket.close();
  };
}

