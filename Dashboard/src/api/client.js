import { config } from "../config.js";
import { ApiError } from "./errors.js";

const TOKEN_KEY = "iot_dashboard_session";

export function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(TOKEN_KEY) || "null");
  } catch {
    return null;
  }
}

export function saveSession(session) {
  localStorage.setItem(TOKEN_KEY, JSON.stringify(session));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
}

async function request(path, { method = "GET", body, token } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new ApiError("Backend non raggiungibile.", {
      code: "network_error",
      details: { reason: String(error) },
    });
  }

  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const apiError = payload.error ?? {};
    throw new ApiError(apiError.message ?? "Errore API.", {
      status: response.status,
      code: apiError.code ?? "http_error",
      details: apiError.details ?? {},
    });
  }
  return payload;
}

export const api = {
  login: (credentials) => request("/auth/login", { method: "POST", body: credentials }),
  patients: (session) => request("/patients", { token: session?.access_token }),
  current: (patientId, session) => request(`/patients/${patientId}/current`, { token: session?.access_token }),
  windows: (patientId, session) => request(`/patients/${patientId}/windows?limit=12`, { token: session?.access_token }),
  decisions: (patientId, session) => request(`/patients/${patientId}/decisions?limit=8`, { token: session?.access_token }),
  alerts: (patientId, session) => request(`/patients/${patientId}/alerts`, { token: session?.access_token }),
  tasks: (patientId, session) => request(`/patients/${patientId}/tasks`, { token: session?.access_token }),
  systemStatus: (patientId, session) => request(`/patients/${patientId}/system-status`, { token: session?.access_token }),
  acknowledgeAlert: (alertId, session) =>
    request(`/alerts/${alertId}/acknowledge`, {
      method: "PATCH",
      token: session?.access_token,
      body: { user_id: session?.user?.user_id },
    }),
  resolveAlert: (alertId, note, session) =>
    request(`/alerts/${alertId}/resolve`, {
      method: "PATCH",
      token: session?.access_token,
      body: { user_id: session?.user?.user_id, note },
    }),
  createTask: (patientId, task, session) =>
    request(`/patients/${patientId}/tasks`, {
      method: "POST",
      token: session?.access_token,
      body: task,
    }),
};

