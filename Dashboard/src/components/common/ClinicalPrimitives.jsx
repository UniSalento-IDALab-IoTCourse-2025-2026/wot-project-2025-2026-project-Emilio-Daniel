import React from "react";

export function ViewEmptyState({ icon, title, text }) {
  return (
    <div className="view-empty-state">
      <span>{icon}</span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

export function Metric({ icon, label, value, tone }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      {icon && <span className="metric-icon">{icon}</span>}
      <div><span>{label}</span><strong>{value}</strong></div>
    </div>
  );
}

export function Detail({ label, value, suffix = "" }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value ?? "n/d"}{suffix}</dd>
    </>
  );
}

export function StatusPill({ status }) {
  const label = {
    idle: "Realtime inattivo",
    connecting: "Connessione realtime",
    connected: "Realtime attivo",
    reconnecting: "Riconnessione realtime",
    error: "Errore realtime",
    invalid_event: "Evento non valido",
  }[status] ?? status;
  return <span className={`status-pill ${status}`}>{label}</span>;
}
