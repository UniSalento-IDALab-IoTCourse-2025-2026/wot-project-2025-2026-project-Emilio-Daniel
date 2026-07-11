export class ApiError extends Error {
  constructor(message, { status = 0, code = "network_error", details = {} } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function readableApiError(error) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Sessione scaduta. Effettua nuovamente il login.";
    if (error.status === 403) return "Permessi insufficienti per visualizzare questa risorsa.";
    if (error.status === 404) return "Risorsa non trovata nel backend.";
    return error.message;
  }
  return "Errore di rete o backend non raggiungibile.";
}

