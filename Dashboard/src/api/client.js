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
  summary24h: (patientId, session) => request(`/patients/${patientId}/summary/24h`, { token: session?.access_token }),
  timeline: (patientId, session, options = {}) => {
    const params = new URLSearchParams({ page_size: String(options.page_size ?? 80) });
    if (options.event_type && options.event_type !== "all") params.set("event_type", options.event_type);
    if (options.date_from) params.set("date_from", options.date_from);
    if (options.date_to) params.set("date_to", options.date_to);
    if (options.page) params.set("page", String(options.page));
    return request(`/patients/${patientId}/timeline?${params.toString()}`, { token: session?.access_token });
  },
  spatialSummary: (patientId, session, options = {}) => {
    const params = new URLSearchParams({ days: String(options.days ?? 7) });
    if (options.date_from) params.set("date_from", options.date_from);
    if (options.date_to) params.set("date_to", options.date_to);
    return request(`/patients/${patientId}/spatial-summary?${params.toString()}`, { token: session?.access_token });
  },
  reportData: (patientId, session, options = {}) =>
    request(`/patients/${patientId}/report-data?days=${encodeURIComponent(String(options.days ?? 7))}`, {
      token: session?.access_token,
    }),
  windows: (patientId, session, options = {}) => {
    const params = new URLSearchParams({ limit: String(options.limit ?? 200) });
    if (options.date_from) params.set("date_from", options.date_from);
    if (options.date_to) params.set("date_to", options.date_to);
    return request(`/patients/${patientId}/windows?${params.toString()}`, { token: session?.access_token });
  },
  decisions: (patientId, session, options = {}) =>
    request(`/patients/${patientId}/decisions?limit=${encodeURIComponent(String(options.limit ?? 200))}`, {
      token: session?.access_token,
    }),
  alerts: (patientId, session) => request(`/patients/${patientId}/alerts`, { token: session?.access_token }),
  alertDetails: (alertId, session) => request(`/alerts/${alertId}/details`, { token: session?.access_token }),
  tasks: (patientId, session) => request(`/patients/${patientId}/tasks`, { token: session?.access_token }),
  questionnaireTemplates: (session) => request("/questionnaires/templates", { token: session?.access_token }),
  questionnaireSchedules: (patientId, session, options = {}) => {
    const params = new URLSearchParams();
    if (options.include_suspended !== undefined) params.set("include_suspended", String(options.include_suspended));
    return request(`/questionnaires/patients/${patientId}/schedules${params.toString() ? `?${params.toString()}` : ""}`, {
      token: session?.access_token,
    });
  },
  createQuestionnaireSchedule: (patientId, payload, session) =>
    request(`/questionnaires/patients/${patientId}/schedules`, {
      method: "POST",
      token: session?.access_token,
      body: payload,
    }),
  suspendQuestionnaireSchedule: (scheduleId, session) =>
    request(`/questionnaires/schedules/${scheduleId}/suspend`, {
      method: "PATCH",
      token: session?.access_token,
    }),
  generateQuestionnaireTask: (scheduleId, session, force = false) =>
    request(`/questionnaires/schedules/${scheduleId}/generate-due-task`, {
      method: "POST",
      token: session?.access_token,
      body: { force },
    }),
  questionnaireResults: (patientId, session, options = {}) =>
    request(`/questionnaires/patients/${patientId}/results?limit=${encodeURIComponent(String(options.limit ?? 80))}`, {
      token: session?.access_token,
    }),
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
  deleteAlert: (alertId, session) =>
    request(`/alerts/${alertId}`, {
      method: "DELETE",
      token: session?.access_token,
    }),
  createTask: (patientId, task, session) =>
    request(`/patients/${patientId}/tasks`, {
      method: "POST",
      token: session?.access_token,
      body: task,
    }),
  createCaregiverMessage: (patientId, message, session) =>
    request(`/patients/${patientId}/caregiver-messages`, {
      method: "POST",
      token: session?.access_token,
      body: message,
    }),
  cancelTask: (taskId, note, session) =>
    request(`/tasks/${taskId}/cancel`, {
      method: "PATCH",
      token: session?.access_token,
      body: { note },
    }),
  deleteTask: (taskId, session) =>
    request(`/tasks/${taskId}`, {
      method: "DELETE",
      token: session?.access_token,
    }),
  updateTaskMedicalNote: (taskId, medicalNote, session) =>
    request(`/tasks/${taskId}/medical-note`, {
      method: "PATCH",
      token: session?.access_token,
      body: { medical_note: medicalNote },
    }),
};
