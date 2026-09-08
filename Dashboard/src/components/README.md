# Componenti Dashboard

Questa cartella contiene i componenti estratti o pronti da estrarre da `App.jsx`.

Stato attuale:

- `ErrorBoundary.jsx` evita pagina bianca in caso di errore render.
- `common/ClinicalPrimitives.jsx` contiene primitivi condivisi estratti da `App.jsx`:
  `Metric`, `Detail`, `StatusPill`, `ViewEmptyState`.

Prossimi spostamenti sicuri:

- `components/ai`: valutazione comportamentale, confidenza, metriche modello, drift.
- `components/patient`: quadro clinico, giornata tipo, grafici.
- `components/alerts`: lista alert, workflow e cancellazione.
- `components/tasks`: composer task e dettaglio risultato.
- `components/system`: diagnostica rapida e stato tecnico.

La regola e' spostare un componente alla volta e lanciare `npm test` + `npm run build`.
