export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8090/api/v1",
  wsBaseUrl: import.meta.env.VITE_WS_BASE_URL ?? "ws://127.0.0.1:8090/ws/v1",
  dataSource: import.meta.env.VITE_DATA_SOURCE ?? "mock",
  staleAfterMinutes: 12,
};

