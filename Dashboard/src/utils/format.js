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

export function aiScoreBand(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) {
    return {
      key: "unknown",
      label: "Non disponibile",
      range: "n/d",
      description: "Score AI non ancora disponibile.",
    };
  }
  if (score < 40) {
    return {
      key: "normal",
      label: "Normalità",
      range: "0-40",
      description: "I dati rientrano nella routine attesa.",
    };
  }
  if (score < 60) {
    return {
      key: "attention",
      label: "Attenzione",
      range: "40-60",
      description: "Segnale da osservare, senza allarme automatico.",
    };
  }
  if (score < 80) {
    return {
      key: "risk",
      label: "Rischio",
      range: "60-80",
      description: "Scostamento importante da revisionare.",
    };
  }
  return {
    key: "critical",
    label: "Massima Allerta",
    range: "80-100",
    description: "Priorità massima di revisione clinica.",
  };
}
