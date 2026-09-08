# Hook Dashboard

Questa cartella e' pronta per estrarre la logica da `App.jsx`.

Hook previsti:

- `usePatientData`: caricamento REST, endpoint opzionali e cache offline.
- `usePatientRealtime`: WebSocket paziente e refresh su eventi.
- `useDashboardFilters`: filtri condivisi per finestre, timeline, alert e task.

La cache offline e' gia' implementata lato `App.jsx`; il prossimo refactor puo' spostarla
qui senza cambiare comportamento.
