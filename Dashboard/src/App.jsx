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
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      token: session?.access_token,
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
  }, [selectedPatientId, session?.access_token]);

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
  const [rangeMode, setRangeMode] = useState("day");
  const visibleWindows = useMemo(() => filterWindowsByRange(windows, rangeMode), [windows, rangeMode]);
  const chartWindows = visibleWindows.length > 0 ? visibleWindows : windows;

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

      <section className="panel span-2">
        <div className="panel-heading">
          <div>
            <h3>Dati wearable e spaziali</h3>
            <p className="panel-subtitle">Finestra visualizzata: {rangeLabel(rangeMode)}. I valori mancanti restano non acquisiti.</p>
          </div>
          <div className="segmented-control range-control" aria-label="Intervallo dati">
            <button
              className={rangeMode === "day" ? "active" : ""}
              type="button"
              onClick={() => setRangeMode("day")}
            >
              Giorno
            </button>
            <button
              className={rangeMode === "week" ? "active" : ""}
              type="button"
              onClick={() => setRangeMode("week")}
            >
              Settimana
            </button>
          </div>
        </div>
        <WearableSpatialDashboard windows={chartWindows} current={current} />
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

function WearableSpatialDashboard({ windows, current }) {
  const latestFeatures = latestFeaturesFromWindows(windows);

  return (
    <div className="sensor-dashboard">
      <section className="sensor-block">
        <div className="sensor-block-heading">
          <HeartPulse size={18} />
          <h4>Wearable</h4>
        </div>
        <div className="chart-grid">
          <FeatureTrendCard
            title="Frequenza cardiaca media"
            feature="heart_rate_mean"
            unit="bpm"
            windows={windows}
            color="#c83532"
          />
          <FeatureTrendCard
            title="Deviazione frequenza cardiaca"
            feature="heart_rate_std"
            unit="bpm"
            windows={windows}
            color="#c05621"
          />
          <FeatureTrendCard title="SpO2 media" feature="spo2_mean" unit="%" windows={windows} color="#17686c" />
          <FeatureTrendCard title="Passi" feature="steps" unit="" windows={windows} color="#4452ba" />
          <FeatureTrendCard title="Sonno" feature="sleep_minutes" unit="min" windows={windows} color="#6271d9" />
          <FeatureTrendCard title="Sedentarieta" feature="sedentary_minutes" unit="min" windows={windows} color="#744d00" />
          <FeatureTrendCard title="HRV RMSSD" feature="hrv_rmssd" unit="ms" windows={windows} color="#6f4bb8" />
        </div>
        <HrvPanel windows={windows} current={current} latestFeatures={latestFeatures} />
      </section>

      <section className="sensor-block">
        <div className="sensor-block-heading">
          <Home size={18} />
          <h4>Spazio domestico</h4>
        </div>
        <RoomTimeline windows={windows} />
        <RoomMinutesChart windows={windows} />
        <SpatialSummary latestFeatures={latestFeatures} />
      </section>
    </div>
  );
}

function FeatureTrendCard({ title, feature, unit, windows, color }) {
  const status = featureStatus(windows, feature);
  const latest = latestFeatureValue(windows, feature);

  return (
    <article className={`chart-card ${status.kind}`}>
      <div className="chart-card-header">
        <div>
          <span>{title}</span>
          <strong>{formatFeatureValue(latest, unit)}</strong>
        </div>
        <FeatureStatusBadge status={status} />
      </div>
      <TrendChart windows={windows} feature={feature} color={color} unit={unit} title={title} />
    </article>
  );
}

function HrvPanel({ windows, current, latestFeatures }) {
  const status = featureStatus(windows, "hrv_rmssd");
  const latest = latestFeatureValue(windows, "hrv_rmssd");
  const hrvDeclared = (current.watch.available_features ?? []).includes("hrv_rmssd");
  const source = status.kind === "missing"
    ? "Google Health / Fitbit: non acquisito nelle finestre caricate"
    : hrvDeclared
      ? "Google Health / Fitbit: feature dichiarata disponibile dal wearable"
      : "Google Health / Fitbit: valore presente nelle finestre Edge";

  return (
    <article className={`hrv-panel ${status.kind}`}>
      <div>
        <div className="sensor-block-heading compact-heading">
          <Watch size={17} />
          <h4>HRV RMSSD</h4>
        </div>
        <p>{source}</p>
      </div>
      <div className="hrv-value">
        <strong>{formatFeatureValue(latest, "ms")}</strong>
        <FeatureStatusBadge status={status} />
      </div>
      <dl className="mini-detail-list">
        <Detail label="Batteria watch" value={formatFeatureValue(latestFeatures.wearable_battery_pct, "%")} />
        <Detail label="Wearable presente" value={latestFeatures.wearable_present === true ? "Si" : latestFeatures.wearable_present === false ? "No" : "n/d"} />
      </dl>
    </article>
  );
}

function TrendChart({ windows, feature, color, unit, title }) {
  const [hoverPoint, setHoverPoint] = useState(null);
  const values = windows.map((window, index) => ({
    index,
    value: numericFeature(window.features, feature),
    label: formatDateTime(window.window_end),
    shortLabel: formatShortDateTime(window.window_end),
    status: featureStatusForWindow(window.features, feature),
  }));
  const numericValues = values.filter((point) => point.value !== null);
  if (numericValues.length === 0) {
    return <div className="chart-empty">Dato non acquisito</div>;
  }

  const width = 360;
  const height = 154;
  const padding = { top: 16, right: 14, bottom: 34, left: 46 };
  const min = Math.min(...numericValues.map((point) => point.value));
  const max = Math.max(...numericValues.map((point) => point.value));
  const spread = max - min || 1;
  const xStep = values.length > 1 ? (width - padding.left - padding.right) / (values.length - 1) : 0;
  const points = values.map((point) => {
    const x = padding.left + point.index * xStep;
    if (point.value === null) return { ...point, x, y: null };
    const y = height - padding.bottom - ((point.value - min) / spread) * (height - padding.top - padding.bottom);
    return { ...point, x, y };
  });
  const segments = splitChartSegments(points);
  const yTicks = [
    { label: formatAxisValue(max), value: max },
    { label: formatAxisValue((min + max) / 2), value: (min + max) / 2 },
    { label: formatAxisValue(min), value: min },
  ];
  const firstLabel = values[0]?.shortLabel ?? "";
  const lastLabel = values.at(-1)?.shortLabel ?? "";

  function yForValue(value) {
    return height - padding.bottom - ((value - min) / spread) * (height - padding.top - padding.bottom);
  }

  function updateHover(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * width;
    const nearest = numericValues
      .map((point) => points[point.index])
      .filter((point) => point?.value !== null)
      .reduce((best, point) => (Math.abs(point.x - svgX) < Math.abs(best.x - svgX) ? point : best));
    setHoverPoint(nearest);
  }

  return (
    <div className="chart-shell">
      <svg
        className="trend-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Andamento ${title}`}
        tabIndex={0}
        onMouseMove={updateHover}
        onMouseLeave={() => setHoverPoint(null)}
        onFocus={() => setHoverPoint(points[numericValues.at(-1)?.index] ?? null)}
        onBlur={() => setHoverPoint(null)}
      >
        {yTicks.map((tick) => {
          const y = yForValue(tick.value);
          return (
            <g key={`${feature}-${tick.label}-${y}`}>
              <line x1={padding.left} y1={y} x2={width - padding.right} y2={y} className="chart-grid-line" />
              <text x={padding.left - 8} y={y + 4} className="chart-tick-label" textAnchor="end">{tick.label}</text>
            </g>
          );
        })}
        <line x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} className="chart-axis" />
        <line x1={padding.left} y1={padding.top} x2={padding.left} y2={height - padding.bottom} className="chart-axis" />
        <text x={(padding.left + width - padding.right) / 2} y={height - 4} className="chart-axis-title" textAnchor="middle">tempo</text>
        <text x={12} y={height / 2} className="chart-axis-title y-title" textAnchor="middle">valore</text>
        <text x={padding.left} y={height - 18} className="chart-tick-label" textAnchor="start">{firstLabel}</text>
        <text x={width - padding.right} y={height - 18} className="chart-tick-label" textAnchor="end">{lastLabel}</text>
        {segments.map((segment, index) => (
          <polyline
            key={`${feature}-${index}`}
            points={segment.map((point) => `${point.x},${point.y}`).join(" ")}
            fill="none"
            stroke={color}
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
        {hoverPoint && (
          <line
            x1={hoverPoint.x}
            y1={padding.top}
            x2={hoverPoint.x}
            y2={height - padding.bottom}
            className="chart-hover-line"
          />
        )}
        {points.filter((point) => point.y !== null).map((point) => (
          <circle
            key={`${feature}-${point.index}`}
            cx={point.x}
            cy={point.y}
            r={hoverPoint?.index === point.index ? 6 : point.status === "imputed" ? 5 : 3.8}
            fill={point.status === "imputed" ? "#ffffff" : color}
            stroke={color}
            strokeWidth="2"
          />
        ))}
        <rect
          x={padding.left}
          y={padding.top}
          width={width - padding.left - padding.right}
          height={height - padding.top - padding.bottom}
          fill="transparent"
        />
      </svg>
      {hoverPoint && (
        <div
          className={`chart-tooltip ${hoverPoint.x > width / 2 ? "left" : "right"}`}
          style={{ left: `${(hoverPoint.x / width) * 100}%` }}
        >
          <strong>{formatFeatureValue(hoverPoint.value, unit)}</strong>
          <span>{hoverPoint.label}</span>
          <small>{hoverPoint.status === "imputed" ? "dato imputato" : "dato acquisito"}</small>
        </div>
      )}
    </div>
  );
}

function RoomTimeline({ windows }) {
  const rooms = windows.map((window) => ({
    room: dominantRoom(window.features),
    start: window.window_start,
    end: window.window_end,
  }));

  if (rooms.length === 0) {
    return <p className="empty-text">Nessuna finestra spaziale disponibile.</p>;
  }

  return (
    <div className="room-timeline" aria-label="Timeline stanze">
      {rooms.map((item, index) => (
        <span
          key={`${item.end}-${index}`}
          className={`room-segment ${item.room ?? "unknown"}`}
          title={`${roomLabel(item.room)} - ${formatDateTime(item.start)} / ${formatDateTime(item.end)}`}
        />
      ))}
    </div>
  );
}

function RoomMinutesChart({ windows }) {
  const totals = roomKeys.map((room) => ({
    room,
    minutes: sumFeature(windows, `${room}_minutes`),
    status: featureStatus(windows, `${room}_minutes`),
  }));
  const max = Math.max(1, ...totals.map((item) => item.minutes ?? 0));

  return (
    <div className="room-bars" aria-label="Minuti per stanza">
      {totals.map((item) => (
        <div key={item.room} className="room-bar-row">
          <span>{roomLabel(item.room)}</span>
          <div className="room-bar-track">
            {item.minutes === null ? (
              <span className="room-bar-missing">n/d</span>
            ) : (
              <span className={`room-bar-fill ${item.room}`} style={{ width: `${Math.max(4, (item.minutes / max) * 100)}%` }} />
            )}
          </div>
          <strong>{item.minutes === null ? "n/d" : `${item.minutes.toFixed(1)} min`}</strong>
          <FeatureStatusBadge status={item.status} compact />
        </div>
      ))}
    </div>
  );
}

function SpatialSummary({ latestFeatures }) {
  return (
    <div className="spatial-summary">
      <Metric label="Cambi stanza" value={formatFeatureValue(latestFeatures.room_changes, "")} />
      <Metric label="Cambi notturni" value={formatFeatureValue(latestFeatures.night_room_changes, "")} />
      <Metric label="Permanenza max" value={formatFeatureValue(latestFeatures.longest_single_room_minutes, "min")} />
    </div>
  );
}

function FeatureStatusBadge({ status, compact = false }) {
  return <span className={`feature-status ${status.kind} ${compact ? "compact-status" : ""}`}>{status.label}</span>;
}

const roomKeys = ["kitchen", "bedroom", "bathroom", "living_room"];

function filterWindowsByRange(windows, rangeMode) {
  if (!Array.isArray(windows) || windows.length === 0) return [];
  const latestTimestamp = Math.max(...windows.map((window) => new Date(window.window_end).getTime()).filter(Number.isFinite));
  if (!Number.isFinite(latestTimestamp)) return windows;
  const days = rangeMode === "week" ? 7 : 1;
  const minTimestamp = latestTimestamp - days * 24 * 60 * 60 * 1000;
  return windows.filter((window) => {
    const timestamp = new Date(window.window_end).getTime();
    return Number.isFinite(timestamp) && timestamp >= minTimestamp;
  });
}

function rangeLabel(rangeMode) {
  return rangeMode === "week" ? "ultimi 7 giorni" : "ultimo giorno";
}

function latestFeaturesFromWindows(windows) {
  return [...windows].reverse().find((window) => window.features)?.features ?? {};
}

function latestFeatureValue(windows, feature) {
  for (const window of [...windows].reverse()) {
    const value = featureValue(window.features, feature);
    if (!isMissingValue(value)) return value;
  }
  return null;
}

function featureValue(features, feature) {
  if (!features) return null;
  return features[feature];
}

function numericFeature(features, feature) {
  const value = featureValue(features, feature);
  if (isMissingValue(value)) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function isMissingValue(value) {
  if (value === null || value === undefined || value === "") return true;
  if (typeof value === "number" && Number.isNaN(value)) return true;
  if (typeof value === "string" && ["nan", "null", "none", "n/d"].includes(value.trim().toLowerCase())) return true;
  return false;
}

function formatFeatureValue(value, unit) {
  if (isMissingValue(value)) return "n/d";
  if (typeof value === "boolean") return value ? "Si" : "No";
  const numeric = Number(value);
  const formatted = Number.isFinite(numeric) ? Number(numeric.toFixed(2)).toString() : String(value);
  return unit ? `${formatted} ${unit}` : formatted;
}

function formatAxisValue(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "n/d";
  if (Math.abs(numeric) >= 1000) return Math.round(numeric).toString();
  if (Math.abs(numeric) >= 100) return numeric.toFixed(0);
  if (Math.abs(numeric) >= 10) return numeric.toFixed(1);
  return numeric.toFixed(2);
}

function formatShortDateTime(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function featureStatus(windows, feature) {
  if (!windows.length) return { kind: "missing", label: "non acquisito" };
  if (windows.some((window) => featureStatusForWindow(window.features, feature) === "imputed")) {
    return { kind: "imputed", label: "imputato" };
  }
  if (windows.some((window) => !isMissingValue(featureValue(window.features, feature)))) {
    return { kind: "acquired", label: "acquisito" };
  }
  return { kind: "missing", label: "non acquisito" };
}

function featureStatusForWindow(features, feature) {
  if (!features || isMissingValue(features[feature])) return "missing";
  const imputed = features.imputed_features ?? features.imputed ?? features.feature_imputed ?? {};
  if (Array.isArray(imputed) && imputed.includes(feature)) return "imputed";
  if (typeof imputed === "object" && imputed?.[feature] === true) return "imputed";
  return "acquired";
}

function splitChartSegments(points) {
  const segments = [];
  let current = [];
  for (const point of points) {
    if (point.y === null) {
      if (current.length > 0) segments.push(current);
      current = [];
    } else {
      current.push(point);
    }
  }
  if (current.length > 0) segments.push(current);
  return segments;
}

function sumFeature(windows, feature) {
  let total = 0;
  let found = false;
  for (const window of windows) {
    const value = numericFeature(window.features, feature);
    if (value !== null) {
      total += value;
      found = true;
    }
  }
  return found ? total : null;
}

function dominantRoom(features) {
  const values = roomKeys
    .map((room) => ({ room, minutes: numericFeature(features, `${room}_minutes`) }))
    .filter((item) => item.minutes !== null);
  if (values.length === 0) return null;
  values.sort((a, b) => b.minutes - a.minutes);
  return values[0].minutes > 0 ? values[0].room : null;
}

function roomLabel(room) {
  return {
    kitchen: "Cucina",
    bedroom: "Camera",
    bathroom: "Bagno",
    living_room: "Soggiorno",
    unknown: "Non acquisita",
  }[room ?? "unknown"] ?? room;
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
        type: "custom",
        priority: taskPriorityForAlert(alert.level),
        title: `Follow-up ${levelLabel(alert.level)}`,
        instructions: `Rivedere l'alert ${alert.alert_id}: ${alert.title}.`,
        payload: {
          workflow: "alert_follow_up",
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
