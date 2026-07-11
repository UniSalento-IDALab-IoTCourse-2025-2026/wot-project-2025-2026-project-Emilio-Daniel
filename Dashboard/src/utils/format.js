import { config } from "../config.js";

export function formatDateTime(value) {
  if (!value) return "Dato non disponibile";
  return new Intl.DateTimeFormat("it-IT", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function isStale(value) {
  if (!value) return true;
  const ageMs = Date.now() - new Date(value).getTime();
  return ageMs > config.staleAfterMinutes * 60 * 1000;
}

export function levelLabel(level) {
  const labels = {
    green: "Routine",
    yellow: "Attenzione",
    orange: "Anomalia",
    red: "Priorita alta",
    technical: "Tecnico",
  };
  return labels[level] ?? "Sconosciuto";
}

export function scoreText(value) {
  if (value === null || value === undefined) return "n/d";
  return Number(value).toFixed(1);
}

