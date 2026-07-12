import {
  Activity,
  AlertTriangle,
  ArrowDownUp,
  CheckCircle2,
  Clock3,
  ClipboardList,
  HeartPulse,
  Home,
  LogOut,
  MonitorCog,
  RefreshCcw,
  Server,
  ShieldCheck,
  Stethoscope,
  Users,
  Watch,
  Wifi,
} from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { api, clearSession, loadSession, saveSession } from "./api/client.js";
import { readableApiError } from "./api/errors.js";
import { openPatientSocket } from "./api/realtime.js";
import { config } from "./config.js";
import { formatDateTime, isStale, levelLabel, scoreText } from "./utils/format.js";

const tabs = [
  { id: "patient", label: "Paziente", icon: HeartPulse },
  { id: "alerts", label: "Alert", icon: AlertTriangle },
  { id: "tasks", label: "Task", icon: ClipboardList },
  { id: "system", label: "Sistema", icon: MonitorCog },
];

export function App() {
  const [session, setSession] = useState(() => loadSession());

  if (!session) {
    return <Login onLogin={setSession} />;
  }

  return <Dashboard session={session} onLogout={() => {
    clearSession();
    setSession(null);
  }} />;
}

function Login({ onLogin }) {
  const [email, setEmail] = useState("doctor@example.test");
  const [password, setPassword] = useState("password-demo");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const payload = await api.login({ email, password });
      saveSession(payload);
      onLogin(payload);
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="login-title">
        <div className="brand-row">
          <div className="brand-mark"><Stethoscope size={24} /></div>
          <div>
            <p className="eyebrow">Triage IoT</p>
            <h1 id="login-title">Dashboard medico</h1>
          </div>
        </div>
        <p className="muted">
          Accesso dimostrativo per monitorare routine, alert e stato tecnico del sistema.
        </p>
        <form className="login-form" onSubmit={submit}>
          <label>
            Email
            <input value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" />
          </label>
          <label>
            Password
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete="current-password"
            />
          </label>
          {error && <p className="error-text" role="alert">{error}</p>}
          <button className="primary-button" type="submit" disabled={loading}>
            <ShieldCheck size={18} />
            {loading ? "Accesso..." : "Accedi"}
          </button>
        </form>
        <p className="tiny-note">Fonte dati: {config.dataSource}</p>
      </section>
    </main>
  );
}

function Dashboard({ session, onLogout }) {
  const [patients, setPatients] = useState([]);
  const [selectedPatientId, setSelectedPatientId] = useState(null);
  const [activeTab, setActiveTab] = useState("patient");
  const [patientSort, setPatientSort] = useState("severity");
  const [patientFilter, setPatientFilter] = useState("all");
  const [state, setState] = useState({ loading: true, error: "", data: null });
  const [wsStatus, setWsStatus] = useState("idle");
  const [events, setEvents] = useState([]);

  async function loadPatients() {
    setState((previous) => ({ ...previous, loading: true, error: "" }));
    try {
      const payload = await api.patients(session);
      const items = payload.items ?? [];
      setPatients(items);
      if (!selectedPatientId && items[0]) {
        const first = [...items].sort((a, b) => severityRank(b.level) - severityRank(a.level))[0];
        setSelectedPatientId(first.patient_id);
      }
    } catch (error) {
      setState({ loading: false, error: readableApiError(error), data: null });
    }
  }

  async function loadPatientData(patientId, options = {}) {
    if (!patientId) return;
    const background = options.background === true;
    if (!background) {
      setState({ loading: true, error: "", data: null });
    }
    try {
      const [current, windows, decisions, alerts, tasks, system] = await Promise.all([
        api.current(patientId, session),
        api.windows(patientId, session),
        api.decisions(patientId, session),
        api.alerts(patientId, session),
        api.tasks(patientId, session),
        api.systemStatus(patientId, session),
      ]);
      setState({
        loading: false,
        error: "",
        data: {
          current,
          windows: windows.items ?? [],
          decisions: decisions.items ?? [],
          alerts: alerts.items ?? [],
          tasks: tasks.items ?? [],
          system,
        },
      });
    } catch (error) {
      if (background) {
        setState((previous) => ({ ...previous, loading: false }));
      } else {
        setState({ loading: false, error: readableApiError(error), data: null });
      }
    }
  }

  useEffect(() => {
    loadPatients();
  }, []);

  useEffect(() => {
    loadPatientData(selectedPatientId);
  }, [selectedPatientId]);

  useEffect(() => {
    if (!selectedPatientId) return undefined;
    return openPatientSocket(selectedPatientId, {
      onStatus: setWsStatus,
      onEvent: (event) => {
        setEvents((previous) => [event, ...previous].slice(0, 8));
        if (
          [
            "decision_updated",
            "alert_created",
            "alert_acknowledged",
            "alert_resolved",
            "task_created",
            "system_status_updated",
          ].includes(event.event_type)
        ) {
          loadPatientData(selectedPatientId, { background: true });
        }
      },
    });
  }, [selectedPatientId]);

  const selectedPatient = useMemo(
    () => patients.find((patient) => patient.patient_id === selectedPatientId),
    [patients, selectedPatientId]
  );

  const visiblePatients = useMemo(
    () => sortPatients(filterPatients(patients, patientFilter), patientSort),
    [patients, patientFilter, patientSort]
  );

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Navigazione principale">
        <div className="sidebar-header">
          <div className="brand-mark"><Stethoscope size={22} /></div>
          <div>
            <p className="eyebrow">IoT ADL</p>
            <h1>Medico</h1>
          </div>
        </div>

        <section className="sidebar-section">
          <div className="section-title">
            <Users size={16} />
            Pazienti
          </div>
          <PatientListControls
            sortMode={patientSort}
            filterMode={patientFilter}
            onSortChange={setPatientSort}
            onFilterChange={setPatientFilter}
          />
          {patients.length === 0 && <p className="empty-text">Nessun paziente assegnato.</p>}
          {patients.length > 0 && visiblePatients.length === 0 && (
            <p className="empty-text">Nessun paziente nel filtro scelto.</p>
          )}
          <div className="patient-list">
            {visiblePatients.map((patient) => (
              <button
                key={patient.patient_id}
                className={`patient-button ${patient.patient_id === selectedPatientId ? "active" : ""} ${isStale(patient.last_update) ? "stale" : ""}`}
                type="button"
                onClick={() => setSelectedPatientId(patient.patient_id)}
              >
                <span className={`level-dot ${patient.level}`} />
                <span>
                  <strong>{patient.display_name}</strong>
                  <small className="patient-meta-line">
                    <Home size={13} />
                    {patient.current_room ?? "stanza n/d"}
                  </small>
                  <small className="patient-meta-line">
                    <Watch size={13} />
                    {patient.watch_present ? "watch ok" : "watch assente"}
                    <Server size={13} />
                    {patient.edge_online ? "edge online" : "edge offline"}
                  </small>
                  <small className="patient-meta-line">
                    <span className={`signal-chip ${signalKind(patient)}`}>
                      {signalLabel(patient)}
                    </span>
                    {isStale(patient.last_update) && <span className="stale-chip">obsoleto</span>}
                  </small>
                  <small>{levelLabel(patient.level)} · {patient.current_room ?? "stanza n/d"}</small>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="sidebar-section">
          <div className="section-title">Vista</div>
          <nav className="tab-list">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  className={`tab-button ${activeTab === tab.id ? "active" : ""}`}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                >
                  <Icon size={17} />
                  {tab.label}
                </button>
              );
            })}
          </nav>
        </section>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Ambiente {config.dataSource}</p>
            <h2>{selectedPatient?.display_name ?? "Paziente"}</h2>
          </div>
          <div className="topbar-actions">
            <StatusPill status={wsStatus} />
            <button className="icon-button" type="button" onClick={() => loadPatientData(selectedPatientId)} title="Aggiorna dati">
              <RefreshCcw size={18} />
            </button>
            <button className="secondary-button" type="button" onClick={onLogout}>
              <LogOut size={17} />
              Esci
            </button>
          </div>
        </header>

        {state.loading && <LoadingState />}
        {!state.loading && state.error && <ErrorState message={state.error} />}
        {!state.loading && !state.error && !state.data && <EmptyState />}
        {!state.loading && !state.error && state.data && (
          <>
            <OverviewStrip patients={patients} selectedPatientId={selectedPatientId} />
            <TriageNotice />
            {activeTab === "patient" && <PatientView data={state.data} />}
            {activeTab === "alerts" && (
              <AlertsView
                data={state.data}
                session={session}
                patientId={selectedPatientId}
                onChanged={() => loadPatientData(selectedPatientId)}
              />
            )}
            {activeTab === "tasks" && <TasksView data={state.data} session={session} patientId={selectedPatientId} onChanged={() => loadPatientData(selectedPatientId)} />}
            {activeTab === "system" && <SystemView data={state.data} events={events} wsStatus={wsStatus} />}
          </>
        )}
      </section>
    </main>
  );
}

function TriageNotice() {
  return (
    <div className="notice">
      <Activity size={18} />
      <span>Indicatori per triage e priorita di revisione. La valutazione clinica resta al medico.</span>
    </div>
  );
}

function LoadingState() {
  return <div className="state-card">Caricamento dati paziente...</div>;
}

function ErrorState({ message }) {
  return <div className="state-card error-state" role="alert">{message}</div>;
}

function EmptyState() {
  return <div className="state-card">Nessun dato disponibile per questa vista.</div>;
}

function PatientListControls({ sortMode, filterMode, onSortChange, onFilterChange }) {
  return (
    <div className="patient-controls" aria-label="Controlli lista pazienti">
      <div className="segmented-control" aria-label="Ordinamento pazienti">
        <button
          className={sortMode === "severity" ? "active" : ""}
          type="button"
          onClick={() => onSortChange("severity")}
        >
          <ArrowDownUp size={14} />
          Severita
        </button>
        <button
          className={sortMode === "updated" ? "active" : ""}
          type="button"
          onClick={() => onSortChange("updated")}
        >
          <Clock3 size={14} />
          Update
        </button>
      </div>
      <select
        className="filter-select"
        value={filterMode}
        onChange={(event) => onFilterChange(event.target.value)}
        aria-label="Filtro pazienti"
      >
        <option value="all">Tutti</option>
        <option value="clinical">Comportamentali</option>
        <option value="technical">Tecnici</option>
        <option value="stale">Obsoleti</option>
      </select>
    </div>
  );
}

function OverviewStrip({ patients, selectedPatientId }) {
  const counts = patients.reduce(
    (accumulator, patient) => {
      accumulator.total += 1;
      accumulator[patient.level] = (accumulator[patient.level] ?? 0) + 1;
      if (isStale(patient.last_update)) accumulator.stale += 1;
      if (signalKind(patient) === "technical") accumulator.technicalSignals += 1;
      if (signalKind(patient) === "clinical") accumulator.clinicalSignals += 1;
      return accumulator;
    },
    {
      total: 0,
      green: 0,
      yellow: 0,
      orange: 0,
      red: 0,
      technical: 0,
      stale: 0,
      clinicalSignals: 0,
      technicalSignals: 0,
    }
  );
  const selected = patients.find((patient) => patient.patient_id === selectedPatientId);

  return (
    <section className="overview-strip" aria-label="Overview pazienti">
      <OverviewMetric label="Monitorati" value={counts.total} />
      <OverviewMetric label="Alta priorita" value={counts.red + counts.orange} tone={counts.red ? "red" : "orange"} />
      <OverviewMetric label="Tecnici" value={counts.technicalSignals} tone="technical" />
      <OverviewMetric label="Obsoleti" value={counts.stale} tone={counts.stale ? "yellow" : "green"} />
      <div className="selected-summary">
        <span className={`level-dot ${selected?.level ?? "green"}`} />
        <div>
          <strong>{selected?.display_name ?? "Nessun paziente selezionato"}</strong>
          <small>{selected ? `${levelLabel(selected.level)} - ${signalLabel(selected)}` : "Seleziona dalla lista"}</small>
        </div>
      </div>
    </section>
  );
}

function OverviewMetric({ label, value, tone }) {
  return (
    <div className={`overview-metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PatientView({ data }) {
  const { current, windows, decisions } = data;
  const stale = isStale(current.last_update);
  const latestDecision = decisions.at(-1);

  return (
    <div className="content-grid">
      <section className="panel span-2">
        <div className="panel-heading">
          <h3>Stato corrente</h3>
          {stale && <span className="badge warning">Dati obsoleti</span>}
        </div>
        <div className="metric-row">
          <Metric label="Livello" value={levelLabel(current.level)} tone={current.level} />
          <Metric label="Score" value={scoreText(current.anomaly_score)} />
          <Metric label="Stanza" value={current.current_room ?? "n/d"} />
          <Metric label="Ultimo update" value={formatDateTime(current.last_update)} />
        </div>
      </section>

      <section className="panel">
        <h3>Wearable</h3>
        <dl className="detail-list">
          <Detail label="Presente" value={current.watch.present ? "Si" : "No"} />
          <Detail label="Batteria" value={current.watch.battery_pct ?? "n/d"} suffix={current.watch.battery_pct ? "%" : ""} />
          <Detail label="Feature" value={(current.watch.available_features ?? []).join(", ") || "n/d"} />
        </dl>
      </section>

      <section className="panel">
        <h3>Ultima decisione AI</h3>
        {latestDecision ? (
          <dl className="detail-list">
            <Detail label="Modello" value={latestDecision.model_label} />
            <Detail label="Score" value={scoreText(latestDecision.anomaly_score)} />
            <Detail label="Finestra" value={`${formatDateTime(latestDecision.window_start)} - ${formatDateTime(latestDecision.window_end)}`} />
          </dl>
        ) : (
          <p className="empty-text">Nessuna decisione disponibile.</p>
        )}
      </section>

      <section className="panel span-2">
        <h3>Finestre recenti</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fine finestra</th>
                <th>HR media</th>
                <th>SpO2</th>
                <th>Cucina</th>
                <th>Cambi stanza</th>
              </tr>
            </thead>
            <tbody>
              {windows.map((window) => (
                <tr key={window.window_id ?? window.window_end}>
                  <td>{formatDateTime(window.window_end)}</td>
                  <td>{window.features.heart_rate_mean ?? "n/d"}</td>
                  <td>{window.features.spo2_mean ?? "n/d"}</td>
                  <td>{window.features.kitchen_minutes ?? "n/d"} min</td>
                  <td>{window.features.room_changes ?? "n/d"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function AlertsView({ data, session, patientId, onChanged }) {
  const [levelFilter, setLevelFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [rangeFilter, setRangeFilter] = useState("all");
  const [notes, setNotes] = useState({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const filteredAlerts = useMemo(
    () => filterAlerts(data.alerts, { levelFilter, statusFilter, rangeFilter }),
    [data.alerts, levelFilter, statusFilter, rangeFilter]
  );
  const activeAlerts = data.alerts.filter((alert) => alert.status !== "resolved").length;

  function noteFor(alertId) {
    return notes[alertId] ?? "";
  }

  function updateNote(alertId, value) {
    setNotes((previous) => ({ ...previous, [alertId]: value }));
  }

  async function acknowledge(alert) {
    const confirmed = window.confirm(`Prendere in carico l'alert ${alert.alert_id}?`);
    if (!confirmed) return;
    setBusy(`${alert.alert_id}:ack`);
    setError("");
    try {
      await api.acknowledgeAlert(alert.alert_id, session);
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function resolve(alert) {
    const note = noteFor(alert.alert_id).trim();
    if (!note) {
      setError("Inserisci una nota clinica prima di risolvere l'alert.");
      return;
    }
    const confirmed = window.confirm(`Segnare come risolto l'alert ${alert.alert_id}?`);
    if (!confirmed) return;
    setBusy(`${alert.alert_id}:resolve`);
    setError("");
    try {
      await api.resolveAlert(alert.alert_id, note, session);
      updateNote(alert.alert_id, "");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function createAlertTask(alert) {
    setBusy(`${alert.alert_id}:task`);
    setError("");
    try {
      await api.createTask(alert.patient_id ?? patientId, {
        type: "alert_follow_up",
        priority: taskPriorityForAlert(alert.level),
        title: `Follow-up ${levelLabel(alert.level)}`,
        instructions: `Rivedere l'alert ${alert.alert_id}: ${alert.title}.`,
        payload: {
          source_alert_id: alert.alert_id,
          source_level: alert.level,
          source_status: alert.status,
          source_category: alert.category,
          source_score: alertScore(alert),
        },
      }, session);
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <h3>Alert</h3>
        <span className="badge">{activeAlerts} attivi</span>
      </div>
      <div className="alert-toolbar" aria-label="Filtri alert">
        <label>
          Livello
          <select value={levelFilter} onChange={(event) => setLevelFilter(event.target.value)}>
            <option value="all">Tutti</option>
            <option value="yellow">Yellow</option>
            <option value="orange">Orange</option>
            <option value="red">Red</option>
            <option value="technical">Technical</option>
          </select>
        </label>
        <label>
          Stato
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">Tutti</option>
            <option value="new">Nuovi</option>
            <option value="acknowledged">Presi in carico</option>
            <option value="resolved">Risolti</option>
          </select>
        </label>
        <label>
          Intervallo
          <select value={rangeFilter} onChange={(event) => setRangeFilter(event.target.value)}>
            <option value="all">Tutto</option>
            <option value="24h">Ultime 24 ore</option>
            <option value="7d">Ultimi 7 giorni</option>
          </select>
        </label>
        <span className="badge">{filteredAlerts.length} visibili</span>
      </div>
      {error && <p className="error-text">{error}</p>}
      {data.alerts.length === 0 ? (
        <p className="empty-text">Nessun alert pubblicabile nello scenario corrente.</p>
      ) : filteredAlerts.length === 0 ? (
        <p className="empty-text">Nessun alert corrisponde ai filtri selezionati.</p>
      ) : (
        <div className="alert-list">
          {filteredAlerts.map((alert) => {
            const resolved = alert.status === "resolved";
            const busyForAlert = busy.startsWith(`${alert.alert_id}:`);
            const reasons = alertReasonList(alert);
            return (
            <article key={alert.alert_id} className={`alert-item ${alert.level}`}>
              <div className="alert-content">
                <div className="alert-title-row">
                  <span className={`badge ${alert.level}`}>{levelLabel(alert.level)}</span>
                  <span className={`status-pill ${alert.status}`}>{alertStatusLabel(alert.status)}</span>
                </div>
                <h4>{alert.title}</h4>
                <p>{alert.description}</p>
                <dl className="alert-meta-grid">
                  <Detail label="Timestamp" value={formatDateTime(alertTimestamp(alert))} />
                  <Detail label="Score" value={scoreText(alertScore(alert))} />
                  <Detail label="Categoria" value={alert.category ?? "n/d"} />
                  <Detail label="Stato" value={alertStatusLabel(alert.status)} />
                </dl>
                {reasons.length > 0 && (
                  <ul className="reason-list" aria-label="Motivi alert">
                    {reasons.map((reason) => (
                      <li key={`${alert.alert_id}-${reason}`}>{reason}</li>
                    ))}
                  </ul>
                )}
                <div className="alert-ownership">
                  <span>
                    Presa in carico: {alert.acknowledged_by ?? "n/d"}
                    {alert.acknowledged_at ? ` - ${formatDateTime(alert.acknowledged_at)}` : ""}
                  </span>
                  <span>
                    Risoluzione: {alert.resolved_by ?? "n/d"}
                    {alert.resolved_at ? ` - ${formatDateTime(alert.resolved_at)}` : ""}
                  </span>
                </div>
                <small>{formatDateTime(alert.opened_at)} · stato {alert.status}</small>
              </div>
              <div className="alert-actions">
                <button className="secondary-button" type="button" disabled={resolved || busyForAlert} onClick={() => acknowledge(alert)}>
                  <CheckCircle2 size={16} />
                  Prendi in carico
                </button>
                <label className="note-field">
                  Nota risoluzione
                  <textarea
                    value={noteFor(alert.alert_id)}
                    onChange={(event) => updateNote(alert.alert_id, event.target.value)}
                    placeholder="Scrivi la motivazione della risoluzione"
                    disabled={resolved}
                  />
                </label>
                <button className="primary-button compact" type="button" disabled={resolved || busyForAlert} onClick={() => resolve(alert)}>
                  Risolvi
                </button>
                <button className="secondary-button compact" type="button" disabled={busyForAlert} onClick={() => createAlertTask(alert)}>
                  <ClipboardList size={16} />
                  Crea task
                </button>
              </div>
            </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function TasksView({ data, session, patientId, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function createCheckIn() {
    setBusy(true);
    setError("");
    try {
      await api.createTask(patientId, {
        type: "check_in",
        priority: "normal",
        title: "Controllo benessere",
        instructions: "Rispondi a queste brevi domande.",
        payload: {
          questions: [
            {
              id: "q1",
              type: "single_choice",
              text: "Come ti senti adesso?",
              options: ["bene", "cosi_cosi", "male"],
            },
          ],
        },
      }, session);
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <h3>Task paziente</h3>
        <button className="primary-button compact" type="button" onClick={createCheckIn} disabled={busy}>
          <ClipboardList size={16} />
          Crea check-in
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {data.tasks.length === 0 ? (
        <p className="empty-text">Nessun task presente.</p>
      ) : (
        <div className="task-list">
          {data.tasks.map((task) => (
            <article key={task.task_id} className="task-item">
              <div>
                <h4>{task.title}</h4>
                <p>{task.instructions ?? "Nessuna istruzione aggiuntiva."}</p>
              </div>
              <span className="badge">{task.status}</span>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function SystemView({ data, events, wsStatus }) {
  const status = data.system;
  return (
    <div className="content-grid">
      <section className="panel">
        <h3>Edge Node</h3>
        <dl className="detail-list">
          <Detail label="Online" value={status.edge.online ? "Si" : "No"} />
          <Detail label="Qualita dati" value={status.edge.quality_status} />
          <Detail label="Coda MQTT" value={status.edge.mqtt_queue_depth} />
          <Detail label="Ultimo ciclo" value={formatDateTime(status.edge.last_cycle_at)} />
        </dl>
      </section>
      <section className="panel">
        <h3>Sensori</h3>
        <dl className="detail-list">
          <Detail label="Watch" value={status.sensors.watch.status} />
          <Detail label="BLE" value={status.sensors.ble.status} />
          <Detail label="Google Health" value={status.sensors.google_health.status} />
          <Detail label="WebSocket" value={wsStatus} />
        </dl>
      </section>
      <section className="panel span-2">
        <h3>Eventi realtime</h3>
        {events.length === 0 ? (
          <p className="empty-text">In attesa di eventi WebSocket.</p>
        ) : (
          <div className="event-list">
            {events.map((event) => (
              <div key={event.event_id} className="event-item">
                <Wifi size={16} />
                <span>{event.event_type}</span>
                <small>{formatDateTime(event.timestamp)}</small>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function filterAlerts(alerts, filters) {
  return alerts.filter((alert) => {
    if (filters.levelFilter !== "all" && alert.level !== filters.levelFilter) return false;
    if (filters.statusFilter !== "all" && alert.status !== filters.statusFilter) return false;
    if (filters.rangeFilter === "all") return true;

    const timestamp = new Date(alertTimestamp(alert)).getTime();
    if (Number.isNaN(timestamp)) return true;
    const maxAgeMs = filters.rangeFilter === "24h" ? 24 * 60 * 60 * 1000 : 7 * 24 * 60 * 60 * 1000;
    return Date.now() - timestamp <= maxAgeMs;
  });
}

function alertTimestamp(alert) {
  return alert.opened_at ?? alert.timestamp ?? alert.created_at ?? alert.updated_at;
}

function alertScore(alert) {
  return alert.anomaly_score ?? alert.score ?? alert.payload?.anomaly_score ?? null;
}

function alertReasonList(alert) {
  const rawReasons = alert.reasons ?? alert.payload?.reasons;
  if (Array.isArray(rawReasons)) return rawReasons.filter(Boolean);
  if (typeof rawReasons === "string" && rawReasons.trim()) return [rawReasons.trim()];
  return alert.description ? [alert.description] : [];
}

function alertStatusLabel(status) {
  return {
    new: "Nuovo",
    acknowledged: "Preso in carico",
    resolved: "Risolto",
  }[status] ?? status ?? "n/d";
}

function taskPriorityForAlert(level) {
  if (level === "red") return "high";
  if (level === "orange") return "medium";
  if (level === "technical") return "technical";
  return "normal";
}

function Metric({ label, value, tone }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Detail({ label, value, suffix = "" }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value ?? "n/d"}{suffix}</dd>
    </>
  );
}

function StatusPill({ status }) {
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

function severityRank(level) {
  return { red: 5, orange: 4, yellow: 3, technical: 2, green: 1 }[level] ?? 0;
}

function sortPatients(patients, sortMode) {
  const ordered = [...patients];
  if (sortMode === "updated") {
    return ordered.sort((a, b) => new Date(b.last_update ?? 0).getTime() - new Date(a.last_update ?? 0).getTime());
  }
  return ordered.sort((a, b) => {
    const severityDiff = severityRank(b.level) - severityRank(a.level);
    if (severityDiff !== 0) return severityDiff;
    return new Date(b.last_update ?? 0).getTime() - new Date(a.last_update ?? 0).getTime();
  });
}

function filterPatients(patients, filterMode) {
  if (filterMode === "clinical") {
    return patients.filter((patient) => signalKind(patient) === "clinical");
  }
  if (filterMode === "technical") {
    return patients.filter((patient) => signalKind(patient) === "technical");
  }
  if (filterMode === "stale") {
    return patients.filter((patient) => isStale(patient.last_update));
  }
  return patients;
}

function signalKind(patient) {
  if (patient.signal_type === "behavioral") return "clinical";
  if (patient.signal_type) return patient.signal_type;
  if (patient.level === "technical" || patient.edge_online === false || patient.watch_present === false) return "technical";
  if (["yellow", "orange", "red"].includes(patient.level)) return "clinical";
  return "routine";
}

function signalLabel(patient) {
  const kind = signalKind(patient);
  if (kind === "technical") return "guasto tecnico";
  if (kind === "clinical") return "segnale comportamentale";
  return "routine";
}
