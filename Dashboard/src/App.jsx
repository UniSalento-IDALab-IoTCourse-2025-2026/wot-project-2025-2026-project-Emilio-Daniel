import {
  Activity,
  AlertTriangle,
  ArrowDownUp,
  Bell,
  BrainCircuit,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  ClipboardList,
  Eye,
  EyeOff,
  Gauge,
  HeartPulse,
  Home,
  Info,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Mail,
  MapPin,
  Menu,
  MessageSquare,
  MonitorCog,
  Plus,
  RefreshCcw,
  Search,
  Send,
  Server,
  ShieldCheck,
  UserRound,
  UserRoundCheck,
  Users,
  Watch,
  Wifi,
  X,
} from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { api, clearSession, loadSession, saveSession } from "./api/client.js";
import { readableApiError } from "./api/errors.js";
import { openPatientSocket } from "./api/realtime.js";
import { config } from "./config.js";
import { aiScoreBand, formatDateTime, isStale, levelLabel, scoreText } from "./utils/format.js";

const tabs = [
  { id: "patient", label: "Quadro clinico", shortLabel: "Paziente", icon: HeartPulse },
  { id: "alerts", label: "Segnalazioni", shortLabel: "Alert", icon: AlertTriangle },
  { id: "tasks", label: "Attività", shortLabel: "Task", icon: ClipboardList },
  { id: "system", label: "Stato sistema", shortLabel: "Sistema", icon: MonitorCog },
];

const PATIENT_PROFILE_STORAGE_KEY = "iot_dashboard_patient_profiles_v1";

const taskTemplates = {
  wellbeing: {
    label: "Check-in benessere",
    type: "check_in",
    title: "Check-in benessere",
    instructions: "Rispondi a poche domande sul tuo stato attuale.",
    expectedScore: "Nessuno score automatico",
    payload: {
      questionnaire: "wellbeing_check_in",
      questions: [
        {
          id: "mood",
          type: "single_choice",
          text: "Come ti senti adesso?",
          options: ["Bene", "Cosi cosi", "Male"],
        },
        {
          id: "energy",
          type: "single_choice",
          text: "Quanto ti senti attivo?",
          options: ["Normale", "Poco attivo", "Molto stanco"],
        },
      ],
    },
    scoring: null,
  },
  phq2: {
    label: "PHQ-2",
    type: "check_in",
    title: "PHQ-2 - screening umore",
    instructions: "Compila le due domande riferite agli ultimi giorni. Uso dimostrativo da validare con il docente.",
    expectedScore: "0-6, interpretazione da validare",
    payload: {
      questionnaire: "phq_2_demo",
      license_note: "Verificare con il docente condizioni di riproduzione e uso didattico.",
      questions: [
        {
          id: "phq2_interest",
          type: "scale",
          text: "Scarso interesse o piacere nel fare le cose",
          options: ["Mai", "Alcuni giorni", "Piu della meta dei giorni", "Quasi ogni giorno"],
        },
        {
          id: "phq2_mood",
          type: "scale",
          text: "Umore giu, depresso o senza speranza",
          options: ["Mai", "Alcuni giorni", "Piu della meta dei giorni", "Quasi ogni giorno"],
        },
      ],
    },
    scoring: null,
  },
  cognitive_short: {
    label: "Test breve dimostrativo",
    type: "cognitive_test",
    title: "Test cognitivo breve",
    instructions: "Completa il breve test dimostrativo proposto dal medico.",
    expectedScore: "0-100, risposte esatte",
    payload: {
      questionnaire: "short_cognitive_demo",
      questions: [
        { id: "simple_sum", type: "text", text: "Quanto fa 2 + 2?" },
        { id: "recall_word", type: "text", text: "Ripeti la parola indicata nell'app companion." },
      ],
    },
    scoring: {
      type: "exact_match",
      expected_answers: {
        simple_sum: "4",
        recall_word: "casa",
      },
    },
  },
  mmse: {
    label: "MMSE",
    type: "cognitive_test",
    title: "MMSE - somministrazione ufficiale",
    instructions: "Esegui il test solo con supervisione clinica e modulo ufficiale autorizzato. La dashboard non riproduce gli item del test.",
    expectedScore: "0-30, da modulo ufficiale",
    payload: {
      questionnaire: "mmse_official_supervised",
      license_note: "MMSE/MMSE-2 richiede verifica di licenza e uso del materiale ufficiale autorizzato.",
      administration_mode: "clinician_supervised_official_form",
      max_score: 30,
      questions: [
        {
          id: "official_total_score",
          type: "number",
          text: "Punteggio totale riportato dal modulo ufficiale autorizzato",
          min: 0,
          max: 30,
        },
        {
          id: "clinical_domains_note",
          type: "text",
          text: "Nota sulle aree osservate, senza trascrivere domande o item del test",
        },
      ],
    },
    scoring: null,
  },
  moca: {
    label: "MoCA",
    type: "cognitive_test",
    title: "MoCA - somministrazione ufficiale",
    instructions: "Esegui il test solo con supervisione clinica e materiale MoCA autorizzato. La dashboard non riproduce gli item del test.",
    expectedScore: "0-30, da modulo ufficiale",
    payload: {
      questionnaire: "moca_official_supervised",
      license_note: "MoCA richiede rispetto delle condizioni ufficiali di uso, riproduzione e distribuzione.",
      administration_mode: "clinician_supervised_official_form",
      max_score: 30,
      domains: [
        "visuospaziale/esecutivo",
        "denominazione",
        "attenzione",
        "linguaggio",
        "astrazione",
        "memoria differita",
        "orientamento",
      ],
      questions: [
        {
          id: "official_total_score",
          type: "number",
          text: "Punteggio totale riportato dal modulo ufficiale autorizzato",
          min: 0,
          max: 30,
        },
        {
          id: "clinical_domains_note",
          type: "text",
          text: "Nota sulle aree osservate, senza trascrivere domande o item del test",
        },
      ],
    },
    scoring: null,
  },
};

const patientMessageSuggestions = [
  {
    id: "gentle_activity",
    title: "Breve attivita consigliata",
    priority: "normal",
    body: "Se ti senti nelle condizioni di farlo, prova a svolgere qualche minuto di movimento leggero in casa o una breve camminata. Non forzarti e fermati se avverti disagio.",
  },
  {
    id: "long_inactivity",
    title: "Routine da riattivare",
    priority: "normal",
    body: "Abbiamo notato un periodo prolungato di inattivita. Se ti senti bene, prova ad alzarti con calma, bere un bicchiere d'acqua e muoverti per pochi minuti.",
  },
  {
    id: "wellbeing_check",
    title: "Come ti senti?",
    priority: "normal",
    body: "Vorrei sapere come ti senti in questo momento. Quando apri l'app, prenditi un attimo per aggiornarmi sul tuo stato generale.",
  },
  {
    id: "wearable_check",
    title: "Controllo dispositivo",
    priority: "high",
    body: "Per favore verifica che il dispositivo indossabile sia al polso, acceso e correttamente carico. Questo ci aiuta a mantenere il monitoraggio continuo.",
  },
  {
    id: "caregiver_support",
    title: "Contatta un familiare",
    priority: "urgent",
    body: "Ti chiedo di contattare un familiare o caregiver di riferimento appena possibile, oppure di restare vicino al telefono. Il medico desidera una verifica di supporto.",
  },
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

function AppLogoMark({ inverse = false }) {
  return (
    <div className={`brand-mark logo-mark ${inverse ? "brand-mark-inverse" : ""}`}>
      <img src="/assets/app-logo.jpg" alt="" />
    </div>
  );
}

function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
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
      <section className="login-layout" aria-labelledby="login-title">
        <div className="login-brand-panel" aria-hidden="true">
          <div className="login-brand-content">
            <div className="login-brand-lockup">
              <AppLogoMark inverse />
              <div>
                <span>Triage IoT</span>
                <strong>Clinical workspace</strong>
              </div>
            </div>
            <div className="login-brand-message">
              <span className="login-kicker">Monitoraggio clinico integrato</span>
              <h2>Segnali chiari.<br />Decisioni consapevoli.</h2>
              <p>Una vista essenziale sull'andamento del paziente, dalla routine quotidiana ai parametri fisiologici.</p>
            </div>
            <div className="login-signal-board">
              <div className="login-signal-row">
                <span className="signal-icon"><HeartPulse size={18} /></span>
                <span>Parametri fisiologici</span>
                <span className="signal-state active">Attivo</span>
              </div>
              <div className="login-signal-row">
                <span className="signal-icon"><MapPin size={18} /></span>
                <span>Routine domestica</span>
                <span className="signal-state active">Attivo</span>
              </div>
              <div className="login-signal-row">
                <span className="signal-icon"><ShieldCheck size={18} /></span>
                <span>Elaborazione protetta</span>
                <span className="signal-state">Edge</span>
              </div>
            </div>
          </div>
        </div>
        <div className="login-form-panel">
          <div className="login-mobile-brand">
            <AppLogoMark />
            <strong>Triage IoT</strong>
          </div>
          <div className="login-heading">
            <span className="secure-access"><LockKeyhole size={14} /> Accesso riservato</span>
            <h1 id="login-title">Accesso clinico</h1>
            <p>Inserisci le credenziali per entrare nell'area di monitoraggio.</p>
          </div>
          <form className="login-form" onSubmit={submit}>
            <label>
              Email
              <span className="input-shell">
                <Mail size={18} />
                <input
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  type="email"
                  autoComplete="email"
                  placeholder="nome@struttura.it"
                  required
                />
              </span>
            </label>
            <label>
              Password
              <span className="input-shell">
                <LockKeyhole size={18} />
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="Password"
                  required
                />
                <button
                  className="input-action"
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  title={showPassword ? "Nascondi password" : "Mostra password"}
                  aria-label={showPassword ? "Nascondi password" : "Mostra password"}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </span>
            </label>
            {error && <p className="error-text login-error" role="alert"><AlertTriangle size={17} />{error}</p>}
            <button className="primary-button login-submit" type="submit" disabled={loading}>
              {loading ? <LoaderCircle className="spin" size={19} /> : <ShieldCheck size={19} />}
              {loading ? "Verifica in corso" : "Entra nella dashboard"}
            </button>
          </form>
          <div className="login-footer">
            <span className="environment-dot" aria-hidden="true" />
            <span><strong>Sistema disponibile</strong> · Ambiente {config.dataSource === "real" ? "operativo" : "dimostrativo"}</span>
          </div>
        </div>
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
  const [patientSearch, setPatientSearch] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [patientIdentityOpen, setPatientIdentityOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
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
    if (background) setRefreshing(true);
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
    } finally {
      if (background) setRefreshing(false);
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
            "task_completed",
            "task_cancelled",
            "task_updated",
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
    () => {
      const normalizedSearch = patientSearch.trim().toLocaleLowerCase("it");
      const filtered = filterPatients(patients, patientFilter).filter((patient) => (
        !normalizedSearch || patient.display_name?.toLocaleLowerCase("it").includes(normalizedSearch)
      ));
      return sortPatients(filtered, patientSort);
    },
    [patients, patientFilter, patientSearch, patientSort]
  );

  const activeView = tabs.find((tab) => tab.id === activeTab) ?? tabs[0];
  const activeAlertCount = state.data?.alerts?.filter((alert) => alert.status !== "resolved").length ?? 0;
  const activeTaskCount = state.data?.tasks?.filter((task) => !["completed", "cancelled"].includes(task.status)).length ?? 0;
  const userLabel = session?.user?.display_name ?? session?.user?.email ?? "Medico";

  function selectPatient(patientId) {
    setSelectedPatientId(patientId);
    setSidebarOpen(false);
  }

  function selectTab(tabId) {
    setActiveTab(tabId);
    setSidebarOpen(false);
  }

  return (
    <main className="app-shell">
      <button
        className={`sidebar-scrim ${sidebarOpen ? "visible" : ""}`}
        type="button"
        onClick={() => setSidebarOpen(false)}
        aria-label="Chiudi navigazione"
        tabIndex={sidebarOpen ? 0 : -1}
      />
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`} aria-label="Navigazione principale">
        <div className="sidebar-header">
          <AppLogoMark />
          <div>
            <p className="eyebrow">Console clinica</p>
            <h1>Triage IoT</h1>
          </div>
          <button className="sidebar-close" type="button" onClick={() => setSidebarOpen(false)} aria-label="Chiudi menu">
            <X size={19} />
          </button>
        </div>

        <section className="sidebar-section navigation-section">
          <div className="section-title">Area di lavoro</div>
          <nav className="tab-list">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const count = tab.id === "alerts" ? activeAlertCount : tab.id === "tasks" ? activeTaskCount : 0;
              return (
                <button
                  key={tab.id}
                  className={`tab-button ${activeTab === tab.id ? "active" : ""}`}
                  type="button"
                  onClick={() => selectTab(tab.id)}
                >
                  <span className="tab-icon"><Icon size={18} /></span>
                  <span>{tab.label}</span>
                  {count > 0 && <span className="nav-count">{count}</span>}
                  <ChevronRight className="tab-chevron" size={16} />
                </button>
              );
            })}
          </nav>
        </section>

        <section className="sidebar-section patients-section">
          <div className="section-title">
            <Users size={16} />
            Pazienti assegnati
            <span className="section-count">{patients.length}</span>
          </div>
          <label className="patient-search">
            <Search size={16} />
            <input
              value={patientSearch}
              onChange={(event) => setPatientSearch(event.target.value)}
              placeholder="Cerca paziente"
              aria-label="Cerca paziente"
            />
            {patientSearch && (
              <button type="button" onClick={() => setPatientSearch("")} aria-label="Cancella ricerca"><X size={15} /></button>
            )}
          </label>
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
                onClick={() => selectPatient(patient.patient_id)}
              >
                <span className={`patient-avatar ${patient.level}`}>{patientInitials(patient.display_name)}</span>
                <span className="patient-button-copy">
                  <strong>{patient.display_name}</strong>
                  <small className="patient-meta-line">
                    <Home size={13} />
                    {roomLabel(patient.current_room)}
                  </small>
                  <small className="patient-meta-line">
                    <Watch size={13} />
                    {patient.watch_present ? "wearable presente" : "wearable non rilevato"}
                    <Server size={13} />
                    {patient.edge_online ? "Raspberry online" : "Raspberry offline"}
                  </small>
                  <small className="patient-meta-line">
                    <span className={`signal-chip ${signalKind(patient)}`}>
                      {signalLabel(patient)}
                    </span>
                    {isStale(patient.last_update) && <span className="stale-chip">obsoleto</span>}
                  </small>
                </span>
                <ChevronRight className="patient-chevron" size={16} />
              </button>
            ))}
          </div>
        </section>

        <div className="sidebar-user">
          <span className="user-avatar"><UserRound size={18} /></span>
          <span><strong>{userLabel}</strong><small>Sessione protetta</small></span>
          <button type="button" onClick={onLogout} title="Esci" aria-label="Esci"><LogOut size={17} /></button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="topbar-title-group">
            <button className="mobile-menu-button" type="button" onClick={() => setSidebarOpen(true)} aria-label="Apri menu">
              <Menu size={21} />
            </button>
            <div>
              <div className="breadcrumb"><span>{selectedPatient?.display_name ?? "Paziente"}</span><ChevronRight size={14} /><strong>{activeView.shortLabel}</strong></div>
              <h2>{activeView.label}</h2>
            </div>
          </div>
          <div className="topbar-actions">
            <StatusPill status={wsStatus} />
            <button className="patient-profile-button" type="button" onClick={() => setPatientIdentityOpen(true)}>
              <UserRound size={17} />
              Anagrafica
            </button>
            <button className="notification-button" type="button" onClick={() => selectTab("alerts")} title="Apri segnalazioni" aria-label="Apri segnalazioni">
              <Bell size={18} />
              {activeAlertCount > 0 && <span>{activeAlertCount}</span>}
            </button>
            <button className="icon-button" type="button" onClick={() => loadPatientData(selectedPatientId, { background: true })} title="Aggiorna dati" aria-label="Aggiorna dati">
              <RefreshCcw className={refreshing ? "spin" : ""} size={18} />
            </button>
          </div>
        </header>

        {state.loading && <LoadingState />}
        {!state.loading && state.error && <ErrorState message={state.error} onRetry={() => loadPatientData(selectedPatientId)} />}
        {!state.loading && !state.error && !state.data && <EmptyState />}
        {!state.loading && !state.error && state.data && (
          <div className="workspace-content">
            <OverviewStrip patients={patients} selectedPatientId={selectedPatientId} />
            <TriageNotice />
            <div className="view-stage" key={`${activeTab}-${selectedPatientId}`}>
              {activeTab === "patient" && <PatientView data={state.data} />}
              {activeTab === "alerts" && (
                <AlertsView
                  data={state.data}
                  session={session}
                  patientId={selectedPatientId}
                  onChanged={() => loadPatientData(selectedPatientId, { background: true })}
                />
              )}
              {activeTab === "tasks" && <TasksView data={state.data} session={session} patientId={selectedPatientId} onChanged={() => loadPatientData(selectedPatientId, { background: true })} />}
              {activeTab === "system" && <SystemView data={state.data} events={events} wsStatus={wsStatus} />}
            </div>
          </div>
        )}
      </section>
      <PatientIdentityDialog
        open={patientIdentityOpen}
        onClose={() => setPatientIdentityOpen(false)}
        patient={selectedPatient}
        current={state.data?.current}
      />
    </main>
  );
}

function TriageNotice() {
  return (
    <div className="notice">
      <span className="notice-icon"><ShieldCheck size={17} /></span>
      <span><strong>Supporto al triage</strong> Gli indicatori orientano la priorita di revisione; la valutazione resta al medico.</span>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="loading-layout" aria-live="polite" aria-label="Caricamento dati paziente">
      <div className="loading-topline"><LoaderCircle className="spin" size={18} /> Sincronizzazione del quadro paziente</div>
      <div className="skeleton-overview">{Array.from({ length: 5 }, (_, index) => <span key={index} />)}</div>
      <div className="skeleton-panel"><span /><span /><span /></div>
      <div className="skeleton-grid"><div /><div /><div /></div>
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="state-card error-state" role="alert">
      <span className="state-icon"><AlertTriangle size={22} /></span>
      <div><strong>Impossibile aggiornare i dati</strong><p>{message}</p></div>
      <button className="secondary-button" type="button" onClick={onRetry}><RefreshCcw size={17} /> Riprova</button>
    </div>
  );
}

function EmptyState() {
  return <div className="state-card empty-state"><span className="state-icon"><Info size={22} /></span><div><strong>Nessun dato disponibile</strong><p>Il quadro si popolera alla ricezione della prima finestra Edge.</p></div></div>;
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
      <OverviewMetric icon={<Users size={17} />} label="Monitorati" value={counts.total} />
      <OverviewMetric icon={<AlertTriangle size={17} />} label="Alta priorita" value={counts.red + counts.orange} tone={counts.red ? "red" : "orange"} />
      <OverviewMetric icon={<MonitorCog size={17} />} label="Tecnici" value={counts.technicalSignals} tone="technical" />
      <OverviewMetric icon={<Clock3 size={17} />} label="Obsoleti" value={counts.stale} tone={counts.stale ? "yellow" : "green"} />
      <div className="selected-summary">
        <span className={`selected-patient-avatar ${selected?.level ?? "green"}`}>{patientInitials(selected?.display_name)}</span>
        <div>
          <strong>{selected?.display_name ?? "Nessun paziente selezionato"}</strong>
          <small>{selected ? `${levelLabel(selected.level)} - ${signalLabel(selected)}` : "Seleziona dalla lista"}</small>
        </div>
      </div>
    </section>
  );
}

function OverviewMetric({ icon, label, value, tone }) {
  return (
    <div className={`overview-metric ${tone ?? ""}`}>
      <span className="overview-icon">{icon}</span>
      <div><span>{label}</span><strong>{value}</strong></div>
    </div>
  );
}

function SortableHeader({ label, sortKey, sort, onSort }) {
  const active = sort.key === sortKey;
  const indicator = active ? (sort.direction === "asc" ? "ASC" : "DESC") : "--";
  return (
    <th>
      <button
        className={`table-sort-button ${active ? "active" : ""}`}
        type="button"
        onClick={() => onSort(sortKey)}
        title={`Ordina per ${label}`}
      >
        <span>{label}</span>
        <span aria-hidden="true">{indicator}</span>
      </button>
    </th>
  );
}

function PatientView({ data }) {
  const { current, windows, decisions } = data;
  const stale = isStale(current.last_update);
  const latestDecision = decisions.at(-1);
  const [rangeMode, setRangeMode] = useState("day");
  const [recentWindowsHidden, setRecentWindowsHidden] = useState(false);
  const [recentSort, setRecentSort] = useState({ key: "window_end", direction: "desc" });
  const visibleWindows = useMemo(() => filterWindowsByRange(windows, rangeMode), [windows, rangeMode]);
  const chartWindows = visibleWindows.length > 0 ? visibleWindows : windows;
  const recentRows = useMemo(
    () => sortRecentWindows(windows, recentSort),
    [windows, recentSort]
  );

  function changeRecentSort(key) {
    setRecentWindowsHidden(false);
    setRecentSort((previous) => ({
      key,
      direction: previous.key === key && previous.direction === "desc" ? "asc" : "desc",
    }));
  }

  return (
    <div className="content-grid">
      <section className={`panel span-2 current-overview ${current.level ?? "green"}`}>
        <div className="panel-heading">
          <div className="section-heading-group">
            <span className="section-heading-icon"><HeartPulse size={20} /></span>
            <div>
              <h3>Stato corrente</h3>
              <p className="panel-subtitle">Ultima valutazione consolidata dai flussi disponibili.</p>
            </div>
          </div>
          {stale && <span className="badge warning">Dati obsoleti</span>}
        </div>
        <div className="metric-row">
          <Metric icon={<Gauge size={18} />} label="Priorita di revisione" value={aiScoreBand(current.anomaly_score).label} tone={aiScoreBand(current.anomaly_score).key} />
          <Metric icon={<BrainCircuit size={18} />} label="Indice AI" value={scoreBandText(current.anomaly_score)} tone={aiScoreBand(current.anomaly_score).key} />
          <Metric icon={<MapPin size={18} />} label="Posizione rilevata" value={roomLabel(current.current_room)} />
          <Metric icon={<Clock3 size={18} />} label="Ultimo aggiornamento" value={formatDateTime(current.last_update)} />
        </div>
      </section>

      <section className="panel span-2">
        <AiExplanationPanel decision={latestDecision} system={data.system} current={current} />
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

      <section className="panel acquisition-panel">
        <div className="panel-heading compact-heading">
          <div className="section-heading-group">
            <span className="section-heading-icon soft"><Watch size={19} /></span>
            <h3>Wearable</h3>
          </div>
          <span className={`technical-status-chip ${current.watch?.present ? "good" : "warning"}`}>
            {current.watch?.present ? "Rilevato" : "Non rilevato"}
          </span>
        </div>
        <dl className="detail-list">
          <Detail label="Presenza" value={current.watch?.present ? "Si" : "No"} />
          <Detail label="Batteria" value={current.watch?.battery_pct ?? "n/d"} suffix={current.watch?.battery_pct !== null && current.watch?.battery_pct !== undefined ? "%" : ""} />
          <Detail label="Dati disponibili" value={(current.watch?.available_features ?? []).map(clinicalFeatureName).join(", ") || "n/d"} />
        </dl>
      </section>

      <section className="panel acquisition-panel">
        <div className="panel-heading compact-heading">
          <div className="section-heading-group">
            <span className="section-heading-icon soft"><Server size={19} /></span>
            <h3>Continuita acquisizione</h3>
          </div>
          <span className={`technical-status-chip ${data.system?.edge?.online ? "good" : "warning"}`}>
            {data.system?.edge?.online ? "Operativa" : "Da verificare"}
          </span>
        </div>
        <dl className="detail-list">
          <Detail label="Raspberry" value={data.system?.edge?.online ? "Online" : "Offline"} />
          <Detail label="Qualita dati" value={qualityStatusLabel(data.system?.edge?.quality_status)} />
          <Detail label="Ultimo ciclo" value={formatDateTime(data.system?.edge?.last_cycle_at)} />
        </dl>
      </section>

      <section className="panel span-2">
        <div className="panel-heading">
          <div className="section-heading-group">
            <span className="section-heading-icon soft"><CalendarClock size={19} /></span>
            <div>
              <h3>Finestre recenti</h3>
              <p className="panel-subtitle">Serie temporale consolidata ogni quattro minuti.</p>
            </div>
          </div>
          <div className="panel-actions">
            <span className="badge">{recentWindowsHidden ? "vista pulita" : `${windows.length} finestre`}</span>
            <button
              className="text-button"
              type="button"
              onClick={() => setRecentWindowsHidden((previous) => !previous)}
            >
              {recentWindowsHidden ? "Mostra dati" : "Pulisci vista"}
            </button>
          </div>
        </div>
        {recentWindowsHidden ? (
          <ViewEmptyState
            icon={<CalendarClock size={24} />}
            title="Vista pulita"
            text="I dati non sono stati cancellati: sono solo nascosti in questa sessione della dashboard."
          />
        ) : (
        <div className="table-wrap recent-windows-table">
          <table className="data-table">
            <thead>
              <tr>
                <SortableHeader label="Fine finestra" sortKey="window_end" sort={recentSort} onSort={changeRecentSort} />
                <SortableHeader label="Frequenza cardiaca" sortKey="heart_rate_mean" sort={recentSort} onSort={changeRecentSort} />
                <SortableHeader label="SpO2" sortKey="spo2_mean" sort={recentSort} onSort={changeRecentSort} />
                <SortableHeader label="Cucina" sortKey="kitchen_minutes" sort={recentSort} onSort={changeRecentSort} />
                <SortableHeader label="Cambi stanza" sortKey="room_changes" sort={recentSort} onSort={changeRecentSort} />
              </tr>
            </thead>
            <tbody>
              {recentRows.map((window) => (
                <tr key={window.window_id ?? window.window_end}>
                  <td>{formatDateTime(window.window_end)}</td>
                  <td>{formatFeatureValue(window.features.heart_rate_mean, "bpm")}</td>
                  <td>{formatFeatureValue(window.features.spo2_mean, "%")}</td>
                  <td>{formatFeatureValue(window.features.kitchen_minutes, "min")}</td>
                  <td>{formatFeatureValue(window.features.room_changes, "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}
      </section>
    </div>
  );
}

function PatientIdentityDialog({ open, onClose, patient, current }) {
  const patientId = current?.patient_id ?? patient?.patient_id ?? "patient";
  const [profile, setProfile] = useState(() => loadPatientProfile(patientId, patient));
  const [savedMessage, setSavedMessage] = useState("");

  useEffect(() => {
    setProfile(loadPatientProfile(patientId, patient));
    setSavedMessage("");
  }, [patientId, patient?.display_name]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open, onClose]);

  const filledCount = countPatientProfileFields(profile);
  const displayName = patientProfileDisplayName(profile, patient, patientId);

  function updateProfile(field, value) {
    setProfile((previous) => ({ ...previous, [field]: field === "taxCode" ? value.toUpperCase() : value }));
    setSavedMessage("");
  }

  function saveProfile() {
    savePatientProfile(patientId, profile);
    setSavedMessage("Scheda anagrafica salvata su questo dispositivo.");
  }

  if (!open) return null;

  return (
    <div className="patient-identity-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="patient-identity-dialog" role="dialog" aria-modal="true" aria-labelledby="patient-identity-title">
        <div className="patient-identity-dialog-header">
          <span className="patient-identity-icon"><UserRound size={21} /></span>
          <div>
            <span className="clinical-kicker">Dati identificativi</span>
            <h3 id="patient-identity-title">Scheda anagrafica paziente</h3>
            <p>{displayName} · ID clinico: {patientId}</p>
          </div>
          <button className="dialog-close" type="button" onClick={onClose} aria-label="Chiudi">
            <X size={19} />
          </button>
        </div>

        <div className="patient-identity-dialog-body">
          <div className="patient-identity-dialog-summary">
            <strong>{filledCount}/10 dati compilati</strong>
            <span>I dati restano locali nel browser della dashboard.</span>
          </div>
          <div className="patient-identity-grid">
            <label>
              Nome
              <input value={profile.firstName} onChange={(event) => updateProfile("firstName", event.target.value)} placeholder="Mario" />
            </label>
            <label>
              Cognome
              <input value={profile.lastName} onChange={(event) => updateProfile("lastName", event.target.value)} placeholder="Rossi" />
            </label>
            <label>
              Codice fiscale
              <input value={profile.taxCode} onChange={(event) => updateProfile("taxCode", event.target.value)} placeholder="RSSMRA..." maxLength={16} />
            </label>
            <label>
              Data di nascita
              <input type="date" value={profile.birthDate} onChange={(event) => updateProfile("birthDate", event.target.value)} />
            </label>
            <label>
              Telefono
              <input value={profile.phone} onChange={(event) => updateProfile("phone", event.target.value)} placeholder="+39 ..." />
            </label>
            <label>
              Email
              <input type="email" value={profile.email} onChange={(event) => updateProfile("email", event.target.value)} placeholder="paziente@example.it" />
            </label>
            <label className="span-2">
              Indirizzo
              <input value={profile.address} onChange={(event) => updateProfile("address", event.target.value)} placeholder="Via, numero civico, citta" />
            </label>
            <label>
              Caregiver di riferimento
              <input value={profile.caregiverName} onChange={(event) => updateProfile("caregiverName", event.target.value)} placeholder="Nome familiare/caregiver" />
            </label>
            <label>
              Telefono caregiver
              <input value={profile.caregiverPhone} onChange={(event) => updateProfile("caregiverPhone", event.target.value)} placeholder="+39 ..." />
            </label>
            <label className="span-2">
              Note identificative
              <textarea value={profile.notes} onChange={(event) => updateProfile("notes", event.target.value)} placeholder="Informazioni utili al medico, senza diagnosi automatiche." />
            </label>
          </div>
        </div>

        <div className="patient-identity-dialog-footer">
          {savedMessage && <span className="inline-save-message"><CheckCircle2 size={15} />{savedMessage}</span>}
          <button className="secondary-button" type="button" onClick={onClose}>Chiudi</button>
          <button className="primary-button" type="button" onClick={saveProfile}>
            <CheckCircle2 size={17} />
            Salva scheda
          </button>
        </div>
      </section>
    </div>
  );
}

function PatientIdentityPanel({ patient, current }) {
  const patientId = current?.patient_id ?? patient?.patient_id ?? "patient";
  const [visible, setVisible] = useState(false);
  const [profile, setProfile] = useState(() => loadPatientProfile(patientId, patient));
  const [savedMessage, setSavedMessage] = useState("");

  useEffect(() => {
    setProfile(loadPatientProfile(patientId, patient));
    setSavedMessage("");
    setVisible(false);
  }, [patientId, patient?.display_name]);

  const filledCount = countPatientProfileFields(profile);
  const displayName = patientProfileDisplayName(profile, patient, patientId);
  const hasProfileData = filledCount > 0;

  function updateProfile(field, value) {
    setProfile((previous) => ({ ...previous, [field]: field === "taxCode" ? value.toUpperCase() : value }));
    setSavedMessage("");
  }

  function saveProfile() {
    savePatientProfile(patientId, profile);
    setSavedMessage("Scheda anagrafica salvata su questo dispositivo.");
  }

  return (
    <section className={`panel span-2 patient-identity-panel ${visible ? "expanded" : "collapsed"}`}>
      <div className="patient-identity-summary">
        <span className="patient-identity-icon"><UserRound size={20} /></span>
        <div className="patient-identity-copy">
          <span className="clinical-kicker">Anagrafica paziente</span>
          <h3>{visible ? displayName : "Dati paziente nascosti"}</h3>
          <p>
            {visible
              ? `ID clinico: ${patientId}`
              : hasProfileData
                ? `Scheda compilata per ${patientId}. Aprila solo quando serve identificare il paziente.`
                : `Scheda non ancora compilata per ${patientId}.`}
          </p>
        </div>
        <div className="patient-identity-actions">
          <span>{filledCount}/10 dati compilati</span>
          <button className="secondary-button" type="button" onClick={() => setVisible((previous) => !previous)}>
            {visible ? <EyeOff size={16} /> : <Eye size={16} />}
            {visible ? "Nascondi dati" : hasProfileData ? "Mostra dati" : "Compila scheda"}
          </button>
        </div>
      </div>

      {visible && (
        <div className="patient-identity-body">
          <div className="patient-identity-grid">
            <label>
              Nome
              <input value={profile.firstName} onChange={(event) => updateProfile("firstName", event.target.value)} placeholder="Mario" />
            </label>
            <label>
              Cognome
              <input value={profile.lastName} onChange={(event) => updateProfile("lastName", event.target.value)} placeholder="Rossi" />
            </label>
            <label>
              Codice fiscale
              <input value={profile.taxCode} onChange={(event) => updateProfile("taxCode", event.target.value)} placeholder="RSSMRA..." maxLength={16} />
            </label>
            <label>
              Data di nascita
              <input type="date" value={profile.birthDate} onChange={(event) => updateProfile("birthDate", event.target.value)} />
            </label>
            <label>
              Telefono
              <input value={profile.phone} onChange={(event) => updateProfile("phone", event.target.value)} placeholder="+39 ..." />
            </label>
            <label>
              Email
              <input type="email" value={profile.email} onChange={(event) => updateProfile("email", event.target.value)} placeholder="paziente@example.it" />
            </label>
            <label className="span-2">
              Indirizzo
              <input value={profile.address} onChange={(event) => updateProfile("address", event.target.value)} placeholder="Via, numero civico, città" />
            </label>
            <label>
              Caregiver di riferimento
              <input value={profile.caregiverName} onChange={(event) => updateProfile("caregiverName", event.target.value)} placeholder="Nome familiare/caregiver" />
            </label>
            <label>
              Telefono caregiver
              <input value={profile.caregiverPhone} onChange={(event) => updateProfile("caregiverPhone", event.target.value)} placeholder="+39 ..." />
            </label>
            <label className="span-2">
              Note identificative
              <textarea value={profile.notes} onChange={(event) => updateProfile("notes", event.target.value)} placeholder="Informazioni utili al medico, senza diagnosi automatiche." />
            </label>
          </div>
          <div className="patient-identity-footer">
            <p>I dati sono salvati localmente nel browser della dashboard e possono essere nascosti dalla vista principale.</p>
            {savedMessage && <span className="inline-save-message"><CheckCircle2 size={15} />{savedMessage}</span>}
            <button className="primary-button" type="button" onClick={saveProfile}>
              <CheckCircle2 size={17} />
              Salva scheda
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function AiExplanationPanel({ decision, system, current }) {
  const fusion = fusionFromDecision(decision);
  const models = modelSummaries(fusion);
  const baseline = baselineFromSystem(system);
  const finalScore = decision?.anomaly_score ?? current?.anomaly_score;
  const finalLevel = decision?.level ?? current?.level;
  const personalModel = fusion?.models?.personal;
  const personalAvailable = personalModel?.available === true || system?.ai?.personal_model_available === true;
  const activeModels = models.filter((model) => model.available).length;

  if (!decision) {
    return (
      <div>
        <div className="panel-heading">
          <h3>Valutazione comportamentale</h3>
          <span className="badge">Supporto al triage</span>
        </div>
        <p className="empty-text">La valutazione non e' ancora disponibile per questo paziente.</p>
      </div>
    );
  }

  return (
    <div className="ai-explanation">
      <div className="ai-title-row">
        <div className="ai-title-icon"><BrainCircuit size={20} /></div>
        <div className="ai-title-copy">
          <h3>Valutazione comportamentale</h3>
          <p>Una lettura sintetica dei dati disponibili a supporto del triage clinico.</p>
        </div>
        <span className={`clinical-level-badge ${finalLevel}`}>{levelLabel(finalLevel)}</span>
      </div>

      <section className={`clinical-ai-summary ${finalLevel}`}>
        <ScoreGauge score={finalScore} level={finalLevel} />
        <div className="clinical-summary-copy">
          <span className="clinical-kicker">Valutazione corrente</span>
          <h4>{decisionHeadline(finalLevel)}</h4>
          <p>{clinicalDecisionSummary(models, finalLevel)}</p>
          <AiScoreBandLegend score={finalScore} />
          <div className="clinical-summary-meta">
            <span><Clock3 size={15} /> {formatAnalysisWindow(decision.window_start, decision.window_end)}</span>
            <span><Gauge size={15} /> {activeModels} {activeModels === 1 ? "fonte attiva" : "fonti attive"}</span>
          </div>
        </div>
        <div className="clinical-safety-note">
          <ShieldCheck size={19} />
          <div>
            <strong>Supporto alla decisione</strong>
            <span>La valutazione finale resta al medico.</span>
          </div>
        </div>
      </section>

      <section className="ai-section-block">
        <div className="ai-section-heading">
          <div>
            <h4>Contributo delle fonti</h4>
            <p>Ogni indice misura quanto i dati si discostano dal proprio riferimento.</p>
          </div>
          {!personalAvailable && <span className="soft-status"><UserRoundCheck size={14} /> Profilo in preparazione</span>}
        </div>
        <div className="model-score-list">
          {models.map((model) => <ModelScoreCard key={model.key} model={model} />)}
        </div>
      </section>

      <div className="ai-support-grid">
        <section className="ai-support-section">
          <div className="ai-section-heading compact-heading">
            <div>
              <h4>Composizione dell'indice</h4>
              <p>Incidenza attuale di ciascuna fonte sul risultato complessivo.</p>
            </div>
          </div>
          <FusionWeights weights={fusion?.weights} personalAvailable={personalAvailable} />
        </section>

        <section className="ai-support-section baseline-section">
          <div className="ai-section-heading compact-heading">
            <div>
              <h4>Profilo personale</h4>
              <p>Apprendimento della routine specifica del paziente.</p>
            </div>
          </div>
          <BaselineProgress baseline={baseline} personalAvailable={personalAvailable} />
        </section>
      </div>

      <section className="ai-section-block factors-section">
        <div className="ai-section-heading">
          <div>
            <h4>Fattori che hanno inciso maggiormente</h4>
            <p>Indicatori ordinati per distanza dal riferimento utilizzato dal sistema.</p>
          </div>
          <span className="soft-status"><Info size={14} /> Dati disponibili</span>
        </div>
        <ClinicalFactors models={models} />
      </section>

      <section className="decision-rationale">
        <div className="decision-rationale-icon"><CheckCircle2 size={18} /></div>
        <div>
          <h4>Come leggere il risultato</h4>
          <ul className="reason-list clinical-reasons">
            {(decision.reasons?.length ? decision.reasons : fusion?.reasons ?? []).map((reason) => (
              <li key={reason}>{decisionReasonLabel(reason)}</li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}

function ScoreGauge({ score, level }) {
  const boundedScore = Math.min(100, Math.max(0, Number(score) || 0));
  const band = aiScoreBand(score);
  return (
    <div className={`score-gauge ${level} score-band-${band.key}`} style={{ "--score": boundedScore }} aria-label={`Indice AI ${scoreText(score)} su 100, ${band.label}`}>
      <div className="score-gauge-inner">
        <strong>{scoreText(score)}</strong>
        <span>su 100</span>
        <em>{band.label}</em>
      </div>
    </div>
  );
}

function AiScoreBandLegend({ score }) {
  const current = aiScoreBand(score);
  const bands = [
    { key: "normal", label: "Normalità", range: "0-40" },
    { key: "attention", label: "Attenzione", range: "40-60" },
    { key: "risk", label: "Rischio", range: "60-80" },
    { key: "critical", label: "Massima Allerta", range: "80-100" },
  ];
  return (
    <div className="ai-score-bands" aria-label="Legenda score AI">
      {bands.map((band) => (
        <span key={band.key} className={`ai-score-band ${band.key} ${current.key === band.key ? "active" : ""}`}>
          <strong>{band.range}</strong>
          {band.label}
        </span>
      ))}
    </div>
  );
}

function ModelScoreCard({ model }) {
  const Icon = model.icon;
  const score = Math.min(100, Math.max(0, Number(model.score) || 0));
  return (
    <article className={`model-score-card ${model.key} ${model.available ? "" : "unavailable"}`}>
      <div className="model-score-icon"><Icon size={19} /></div>
      <div className="model-score-content">
        <div className="model-score-title">
          <div>
            <strong>{model.label}</strong>
            <small>{model.description}</small>
          </div>
          <span className={`model-status ${modelStatusTone(model)}`}>{modelStatusLabel(model)}</span>
        </div>
        {model.available ? (
          <div className="model-score-value">
            <div className="model-score-track"><span style={{ width: `${score}%` }} /></div>
            <strong>{scoreText(model.score)} <small>/ 100</small></strong>
          </div>
        ) : (
          <p className="model-unavailable-copy">Sara disponibile al termine della baseline personale.</p>
        )}
      </div>
    </article>
  );
}

function FusionWeights({ weights, personalAvailable }) {
  const entries = modelOrder.map((model) => ({
    key: model.key,
    label: model.label,
    weight: normalizeWeight(weights?.[model.key]),
  }));
  const hasWeights = entries.some((entry) => entry.weight !== null);

  return (
    <div className="fusion-weight-list">
      {hasWeights ? entries.map((entry) => (
        <div key={entry.key} className={`fusion-weight-row ${entry.key}`}>
          <span>{entry.label}</span>
          <div className="weight-track">
            <span style={{ width: `${entry.weight ?? 0}%` }} />
          </div>
          <strong>{entry.weight === null ? "n/d" : `${entry.weight.toFixed(0)}%`}</strong>
        </div>
      )) : <p className="empty-text">Pesi non disponibili nel payload corrente.</p>}
      <div className="future-weight-note">
        <UserRoundCheck size={18} />
        <p>
          <strong>Dopo la baseline:</strong> routine negli ambienti 15%, parametri wearable 15%, profilo personale 70%.
          {!personalAvailable && " Fino ad allora il calcolo usa soltanto le fonti generali disponibili."}
        </p>
      </div>
    </div>
  );
}

function BaselineProgress({ baseline, personalAvailable }) {
  if (!baseline?.available) {
    return (
      <div className="baseline-empty">
        <UserRoundCheck size={22} />
        <div>
          <strong>Avanzamento non ancora ricevuto</strong>
          <p>Il profilo personale sara creato dopo almeno 1000 finestre valide.</p>
        </div>
      </div>
    );
  }

  const accepted = numberOrZero(baseline.accepted_windows);
  const minWindows = Math.max(1, numberOrZero(baseline.min_training_windows) || 1000);
  const progress = Math.min(100, (accepted / minWindows) * 100);
  const elapsedDays = elapsedDaysFromBaseline(baseline);

  return (
    <div className="baseline-progress">
      <div className="progress-header">
        <strong>{personalAvailable ? "Profilo pronto" : baselineStatusLabel(baseline.status)}</strong>
        <span>{progress.toFixed(0)}%</span>
      </div>
      <div className="progress-track" aria-label="Avanzamento baseline">
        <span style={{ width: `${progress}%` }} />
      </div>
      <p className="baseline-window-count"><strong>{accepted}</strong> di {minWindows} finestre valide raccolte</p>
      <div className="baseline-stats">
        <div><span>Tempo trascorso</span><strong>{elapsedDays === null ? "Non disponibile" : `${elapsedDays.toFixed(1)} giorni`}</strong></div>
        <div><span>Durata prevista</span><strong>{baseline.planned_days ? `${baseline.planned_days} giorni` : "Non disponibile"}</strong></div>
        <div><span>Completamento stimato</span><strong>{baseline.target_end_at ? formatDateTime(baseline.target_end_at) : "Non disponibile"}</strong></div>
        <div><span>Finestre escluse</span><strong>{baseline.rejected_windows ?? 0}</strong></div>
      </div>
    </div>
  );
}

function ClinicalFactors({ models }) {
  const rows = models.flatMap((model) =>
    (model.topFeatures ?? []).slice(0, 4).map((feature) => ({
      modelKey: model.key,
      model: model.label,
      ...feature,
    }))
  ).sort((left, right) => {
    if (left.imputed !== right.imputed) return left.imputed ? 1 : -1;
    return Math.abs(Number(right.z_score) || 0) - Math.abs(Number(left.z_score) || 0);
  }).slice(0, 7);

  if (rows.length === 0) {
    return <p className="empty-text">I fattori principali non sono disponibili per questa valutazione.</p>;
  }

  return (
    <div className="clinical-factor-wrap">
      <div className="clinical-factor-list">
        {rows.map((row, index) => {
          const metadata = clinicalFeature(row.feature);
          return (
            <article className={`clinical-factor ${row.imputed ? "imputed" : ""}`} key={`${row.model}-${row.feature}-${index}`}>
              <div className={`factor-source-dot ${row.modelKey}`} />
              <div className="factor-name">
                <strong>{metadata.label}</strong>
                <span>{row.model}</span>
              </div>
              <div className="factor-reading">
                <span>Valore rilevato</span>
                <strong>{row.imputed ? "Non acquisito" : formatFeatureValue(row.value, metadata.unit)}</strong>
              </div>
              <div className="factor-comparison">
                <span>Confronto col riferimento</span>
                <strong>{row.imputed ? "Dato stimato" : directionLabel(row.direction)}</strong>
              </div>
              <span className={`factor-quality ${row.imputed ? "imputed" : "acquired"}`}>
                {row.imputed ? "Stima tecnica" : "Misurato"}
              </span>
            </article>
          );
        })}
      </div>

      <details className="technical-details">
        <summary><Info size={16} /> Dettagli tecnici del calcolo <ChevronDown size={16} /></summary>
        <div className="technical-details-body">
          <p>
            Il valore usato nel calcolo e' il dato dopo la preparazione automatica. Se una misura manca,
            il sistema puo sostituirla con un valore coerente con i dati di addestramento: per questo puo
            essere diverso dal valore rilevato. Lo scostamento standardizzato indica la distanza dal riferimento,
            non una diagnosi.
          </p>
          <div className="table-wrap">
            <table className="feature-table">
              <thead>
                <tr>
                  <th>Indicatore</th>
                  <th>Valore rilevato</th>
                  <th>Valore usato nel calcolo</th>
                  <th>Scostamento standardizzato</th>
                  <th>Qualita del dato</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => {
                  const metadata = clinicalFeature(row.feature);
                  return (
                    <tr key={`technical-${row.model}-${row.feature}-${index}`}>
                      <td>{metadata.label}</td>
                      <td>{formatFeatureValue(row.value, metadata.unit)}</td>
                      <td>{formatFeatureValue(row.model_value, metadata.unit)}</td>
                      <td>{scoreText(row.z_score)}</td>
                      <td>{row.imputed ? "Stimato per dato mancante" : "Acquisito dal sensore"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </details>
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
const modelOrder = [
  {
    key: "generic_spatial",
    label: "Routine negli ambienti",
    description: "Permanenza nelle stanze e spostamenti",
    icon: MapPin,
  },
  {
    key: "generic_wearable",
    label: "Parametri dal wearable",
    description: "Dati fisiologici, sonno e attività",
    icon: Watch,
  },
  {
    key: "personal",
    label: "Profilo personale",
    description: "Confronto con la routine individuale",
    icon: UserRoundCheck,
  },
];

function fusionFromDecision(decision) {
  return decision?.evidence?.fusion ?? decision?.payload?.evidence?.fusion ?? null;
}

function modelSummaries(fusion) {
  const models = fusion?.models ?? {};
  return modelOrder.map((model) => {
    const payload = models[model.key] ?? {};
    return {
      key: model.key,
      label: model.label,
      description: model.description,
      icon: model.icon,
      available: payload.available === true,
      score: payload.score,
      decisionValue: payload.decision_value,
      statusLabel: payload.label ?? "disponibile",
      topFeatures: payload.feature_explanation?.top_features ?? [],
    };
  });
}

function baselineFromSystem(system) {
  const baseline = system?.ai?.baseline ?? system?.baseline ?? null;
  if (!baseline) return { available: false };
  return baseline;
}

function normalizeWeight(value) {
  if (value === null || value === undefined) return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return numeric <= 1 ? numeric * 100 : numeric;
}

function numberOrZero(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function elapsedDaysFromBaseline(baseline) {
  if (!baseline?.started_at) return null;
  const started = new Date(baseline.started_at).getTime();
  if (!Number.isFinite(started)) return null;
  return Math.max(0, (Date.now() - started) / (24 * 60 * 60 * 1000));
}

function directionLabel(direction) {
  return {
    above_training: "Piu alto del riferimento",
    below_training: "Piu basso del riferimento",
    inside_training: "In linea con il riferimento",
  }[direction] ?? "Confronto non disponibile";
}

const clinicalFeatureCatalog = {
  wearable_present: { label: "Wearable indossato", unit: "" },
  wearable_battery_pct: { label: "Batteria del wearable", unit: "%" },
  heart_rate_mean: { label: "Frequenza cardiaca media", unit: "bpm" },
  heart_rate_std: { label: "Oscillazione della frequenza cardiaca", unit: "bpm" },
  resting_heart_rate: { label: "Frequenza cardiaca a riposo", unit: "bpm" },
  hrv_rmssd: { label: "Variabilita cardiaca (HRV)", unit: "ms" },
  spo2_mean: { label: "Saturazione media (SpO2)", unit: "%" },
  sleep_minutes: { label: "Durata del sonno", unit: "min" },
  awake_minutes: { label: "Tempo di veglia", unit: "min" },
  steps: { label: "Passi", unit: "" },
  sedentary_minutes: { label: "Tempo sedentario", unit: "min" },
  room_changes: { label: "Cambi di stanza", unit: "" },
  night_room_changes: { label: "Spostamenti notturni", unit: "" },
  bedroom_minutes: { label: "Permanenza in camera da letto", unit: "min" },
  kitchen_minutes: { label: "Permanenza in cucina", unit: "min" },
  bathroom_minutes: { label: "Permanenza in bagno", unit: "min" },
  living_room_minutes: { label: "Permanenza in soggiorno", unit: "min" },
  longest_single_room_minutes: { label: "Permanenza continuativa massima", unit: "min" },
  nilm_total_wh: { label: "Consumo elettrico complessivo", unit: "Wh" },
  nilm_kitchen_events: { label: "Utilizzi rilevati in cucina", unit: "" },
  nilm_tv_minutes: { label: "Tempo di utilizzo TV", unit: "min" },
  nilm_coffee_events: { label: "Utilizzi della macchina del caffe", unit: "" },
  nilm_stove_events: { label: "Utilizzi del piano cottura", unit: "" },
  fall_events: { label: "Possibili cadute rilevate", unit: "" },
};

function clinicalFeature(feature) {
  return clinicalFeatureCatalog[feature] ?? {
    label: String(feature ?? "Indicatore").replaceAll("_", " "),
    unit: "",
  };
}

function modelStatusLabel(model) {
  if (!model.available) return "In preparazione";
  if (["outlier", "anomaly"].includes(String(model.statusLabel).toLowerCase())) return "Scostamento rilevato";
  return "Nella norma";
}

function modelStatusTone(model) {
  if (!model.available) return "preparing";
  return ["outlier", "anomaly"].includes(String(model.statusLabel).toLowerCase()) ? "attention" : "normal";
}

function modelNeedsAttention(model) {
  return model.available && ["outlier", "anomaly"].includes(String(model.statusLabel).toLowerCase());
}

function decisionHeadline(level) {
  return {
    green: "Andamento regolare",
    yellow: "Variazione da verificare",
    orange: "Variazione rilevante",
    red: "Priorita elevata",
    technical: "Verifica tecnica necessaria",
  }[level] ?? "Valutazione disponibile";
}

function clinicalDecisionSummary(models, level) {
  if (level === "technical") {
    return "Uno o piu dispositivi non stanno fornendo dati affidabili. Verificare il sistema prima di interpretare il comportamento.";
  }
  const spatial = models.find((model) => model.key === "generic_spatial");
  const wearable = models.find((model) => model.key === "generic_wearable");
  const personal = models.find((model) => model.key === "personal");
  const spatialAttention = modelNeedsAttention(spatial);
  const wearableAttention = modelNeedsAttention(wearable);
  const personalAttention = modelNeedsAttention(personal);

  if (spatialAttention && wearableAttention) {
    return "La routine negli ambienti e i parametri del wearable mostrano variazioni concordanti da approfondire.";
  }
  if (personalAttention) {
    return "I dati attuali si discostano dalla routine personale appresa dal sistema e meritano una verifica.";
  }
  if (spatialAttention) {
    return "La routine negli ambienti mostra uno scostamento; i parametri del wearable non confermano al momento la stessa variazione.";
  }
  if (wearableAttention) {
    return "I parametri del wearable mostrano uno scostamento; la routine negli ambienti non evidenzia variazioni concordanti.";
  }
  return "Le fonti disponibili descrivono un andamento compatibile con i riferimenti correnti del sistema.";
}

function formatAnalysisWindow(start, end) {
  if (!start || !end) return "Intervallo non disponibile";
  return `${formatDateTime(start)} - ${formatDateTime(end)}`;
}

function baselineStatusLabel(status) {
  return {
    collecting: "Raccolta in corso",
    active: "Raccolta in corso",
    ready: "Dati sufficienti",
    training: "Creazione del profilo",
    completed: "Profilo completato",
    failed: "Verifica necessaria",
  }[status] ?? "Raccolta in corso";
}

function decisionReasonLabel(reason) {
  const exactLabels = {
    "Current anomaly score exceeds severe threshold": "L'indice complessivo ha superato la soglia di priorita elevata.",
    "Current anomaly score exceeds important threshold": "L'indice complessivo ha superato la soglia di attenzione rilevante.",
    "Current anomaly score exceeds attention threshold": "L'indice complessivo ha superato la soglia di attenzione.",
    "Attention level is visible in dashboard but not published as an alert": "La variazione e' visibile per la valutazione clinica, ma non ha generato un allarme prioritario.",
    "Routine inside learned baseline": "L'andamento osservato e' coerente con il riferimento appreso.",
    "Wearable not detected or not worn": "Il wearable non risulta rilevato o indossato.",
    "Wearable battery below technical threshold": "La batteria del wearable e' sotto la soglia tecnica prevista.",
    "Wearable battery value is invalid": "Il valore della batteria del wearable non e' valido.",
    "Available models report routine-compatible behavior": "Le fonti disponibili indicano un andamento compatibile con i riferimenti correnti.",
    "Other available models do not confirm the anomaly at alert level": "Le altre fonti disponibili non confermano la variazione a livello di allarme.",
    "Model scores differ, but all remain below alert threshold": "Le fonti mostrano differenze, ma restano sotto la soglia di allarme.",
  };
  if (exactLabels[reason]) return exactLabels[reason];
  if (reason?.includes("generic_spatial reports an anomaly")) return "La routine negli ambienti mostra uno scostamento dal riferimento.";
  if (reason?.includes("generic_wearable reports an anomaly")) return "I parametri del wearable mostrano uno scostamento dal riferimento.";
  if (reason?.includes("personal reports an anomaly")) return "I dati si discostano dalla routine personale appresa.";
  if (reason?.startsWith("Attention signal confirmed by")) return "La variazione e' confermata da piu fonti disponibili.";
  if (reason?.startsWith("Important anomaly confirmed by")) return "Una variazione rilevante e' confermata da piu fonti disponibili.";
  if (reason?.startsWith("Severe anomaly confirmed by")) return "Una variazione di priorita elevata e' confermata da piu fonti disponibili.";
  return "Il sistema ha rilevato un elemento utile alla valutazione clinica.";
}

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
  const decimals = unit === "min" ? 1 : 2;
  const formatted = Number.isFinite(numeric) ? Number(numeric.toFixed(decimals)).toString() : String(value);
  return unit ? `${formatted} ${unit}` : formatted;
}

function emptyPatientProfile(patient) {
  const nameParts = String(patient?.display_name ?? "").trim().split(/\s+/).filter(Boolean);
  return {
    firstName: nameParts.length > 1 ? nameParts.slice(0, -1).join(" ") : "",
    lastName: nameParts.length > 1 ? nameParts.at(-1) : "",
    taxCode: "",
    birthDate: "",
    phone: "",
    email: "",
    address: "",
    caregiverName: "",
    caregiverPhone: "",
    notes: "",
  };
}

function loadPatientProfile(patientId, patient) {
  const fallback = emptyPatientProfile(patient);
  try {
    const stored = JSON.parse(localStorage.getItem(PATIENT_PROFILE_STORAGE_KEY) || "{}");
    return { ...fallback, ...(stored?.[patientId] ?? {}) };
  } catch {
    return fallback;
  }
}

function savePatientProfile(patientId, profile) {
  try {
    const stored = JSON.parse(localStorage.getItem(PATIENT_PROFILE_STORAGE_KEY) || "{}");
    localStorage.setItem(PATIENT_PROFILE_STORAGE_KEY, JSON.stringify({ ...stored, [patientId]: profile }));
  } catch {
    // Supporto locale alla dashboard: se il browser blocca il salvataggio, il sistema clinico resta operativo.
  }
}

function countPatientProfileFields(profile) {
  const fields = ["firstName", "lastName", "taxCode", "birthDate", "phone", "email", "address", "caregiverName", "caregiverPhone", "notes"];
  return fields.filter((field) => String(profile?.[field] ?? "").trim()).length;
}

function patientProfileDisplayName(profile, patient, patientId) {
  const fullName = [profile?.firstName, profile?.lastName].map((part) => String(part ?? "").trim()).filter(Boolean).join(" ");
  return fullName || patient?.display_name || patientId;
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
  const [success, setSuccess] = useState("");
  const [dialog, setDialog] = useState(null);

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
    setBusy(`${alert.alert_id}:ack`);
    setError("");
    setSuccess("");
    try {
      await api.acknowledgeAlert(alert.alert_id, session);
      setSuccess("Segnalazione presa in carico correttamente.");
      setDialog(null);
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
    setBusy(`${alert.alert_id}:resolve`);
    setError("");
    setSuccess("");
    try {
      await api.resolveAlert(alert.alert_id, note, session);
      updateNote(alert.alert_id, "");
      setSuccess("Segnalazione risolta e nota registrata.");
      setDialog(null);
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
    setSuccess("");
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
      setSuccess("Attività di follow-up creata per il paziente.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel page-panel alerts-page">
      <div className="view-heading">
        <div className="view-heading-copy">
          <span className="view-heading-icon alert"><AlertTriangle size={22} /></span>
          <div>
            <h3>Segnalazioni cliniche e tecniche</h3>
            <p>Revisione, presa in carico e chiusura documentata degli eventi.</p>
          </div>
        </div>
        <div className="view-heading-stats">
          <span><strong>{activeAlerts}</strong> attive</span>
          <span><strong>{data.alerts.filter((alert) => alert.status === "resolved").length}</strong> risolte</span>
        </div>
      </div>
      <div className="filter-toolbar alert-toolbar" aria-label="Filtri alert">
        <div className="filter-toolbar-title"><ArrowDownUp size={17} /><span>Filtra elenco</span></div>
        <label>
          Livello
          <select value={levelFilter} onChange={(event) => setLevelFilter(event.target.value)}>
            <option value="all">Tutti</option>
            <option value="yellow">Attenzione</option>
            <option value="orange">Anomalia</option>
            <option value="red">Priorita alta</option>
            <option value="technical">Problema tecnico</option>
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
        <span className="results-count"><strong>{filteredAlerts.length}</strong> risultati</span>
      </div>
      {error && <p className="inline-feedback error" role="alert"><AlertTriangle size={17} />{error}</p>}
      {success && <p className="inline-feedback success" role="status"><CheckCircle2 size={17} />{success}</p>}
      {data.alerts.length === 0 ? (
        <ViewEmptyState icon={<CheckCircle2 size={24} />} title="Nessuna segnalazione" text="Non risultano eventi che richiedono revisione." />
      ) : filteredAlerts.length === 0 ? (
        <ViewEmptyState icon={<Search size={24} />} title="Nessun risultato" text="Modifica i filtri per visualizzare altre segnalazioni." />
      ) : (
        <div className="alert-list">
          {filteredAlerts.map((alert) => {
            const resolved = alert.status === "resolved";
            const busyForAlert = busy.startsWith(`${alert.alert_id}:`);
            const reasons = alertReasonList(alert);
            const score = alertScore(alert);
            const band = aiScoreBand(score);
            return (
            <article key={alert.alert_id} className={`alert-item ${alert.level} ${resolved ? "is-resolved" : ""}`}>
              <div className="alert-content">
                <div className="alert-card-header">
                  <div className="alert-title-row">
                    <span className={`alert-level-mark ${alert.level}`}><AlertTriangle size={16} /></span>
                    <span className={`badge ${alert.level}`}>{levelLabel(alert.level)}</span>
                    <span className={`status-pill ${alert.status}`}>{alertStatusLabel(alert.status)}</span>
                  </div>
                  <time>{formatDateTime(alertTimestamp(alert))}</time>
                </div>
                <h4>{alert.title}</h4>
                <p>{alert.description}</p>
                <div className="alert-data-grid">
                  <div className={`alert-score-card ${band.key}`}>
                    <span>Indice AI</span>
                    <strong>{scoreBandText(score)}</strong>
                    <small>{band.label}</small>
                  </div>
                  <div className="alert-data-card">
                    <span>Categoria</span>
                    <strong>{categoryLabel(alert.category)}</strong>
                  </div>
                  <div className="alert-data-card">
                    <span>Stato operativo</span>
                    <strong>{alertStatusLabel(alert.status)}</strong>
                  </div>
                  <div className="alert-data-card">
                    <span>ID segnalazione</span>
                    <strong>{alert.alert_id}</strong>
                  </div>
                </div>
                {reasons.length > 0 && (
                  <ul className="reason-list" aria-label="Motivi alert">
                    {reasons.map((reason) => (
                      <li key={`${alert.alert_id}-${reason}`}>{reason}</li>
                    ))}
                  </ul>
                )}
                <div className="alert-ownership">
                  <span className={alert.acknowledged_at ? "complete" : ""}>
                    <UserRoundCheck size={15} />
                    <span><strong>Presa in carico</strong>{alert.acknowledged_by ?? "In attesa"}{alert.acknowledged_at ? `, ${formatDateTime(alert.acknowledged_at)}` : ""}</span>
                  </span>
                  <span className={alert.resolved_at ? "complete" : ""}>
                    <CheckCircle2 size={15} />
                    <span><strong>Risoluzione</strong>{alert.resolved_by ?? "Non risolta"}{alert.resolved_at ? `, ${formatDateTime(alert.resolved_at)}` : ""}</span>
                  </span>
                </div>
                <small>{formatDateTime(alert.opened_at)} · stato {alert.status}</small>
              </div>
              <div className="alert-actions">
                <div className="alert-actions-title">
                  <strong>Azioni medico</strong>
                  <span>{resolved ? "Segnalazione chiusa" : "Revisione richiesta"}</span>
                </div>
                <button className="secondary-button" type="button" disabled={resolved || busyForAlert || alert.status === "acknowledged"} onClick={() => setDialog({ type: "acknowledge", alert })}>
                  <CheckCircle2 size={16} />
                  Prendi in carico
                </button>
                <button className="primary-button" type="button" disabled={resolved || busyForAlert} onClick={() => setDialog({ type: "resolve", alert })}>
                  <CheckCircle2 size={16} />
                  Risolvi
                </button>
                <button className="text-button" type="button" disabled={busyForAlert} onClick={() => createAlertTask(alert)}>
                  <ClipboardList size={16} />
                  Crea attività di follow-up
                </button>
              </div>
            </article>
            );
          })}
        </div>
      )}
      <ActionDialog
        open={Boolean(dialog)}
        icon={dialog?.type === "resolve" ? <CheckCircle2 size={22} /> : <UserRoundCheck size={22} />}
        title={dialog?.type === "resolve" ? "Conferma risoluzione" : "Prendi in carico"}
        description={dialog?.type === "resolve"
          ? "La segnalazione verra chiusa e la nota restera nello storico clinico."
          : "La segnalazione verra assegnata alla tua sessione corrente."}
        confirmLabel={dialog?.type === "resolve" ? "Conferma risoluzione" : "Conferma presa in carico"}
        busy={Boolean(dialog && busy.startsWith(`${dialog.alert.alert_id}:`))}
        onClose={() => !busy && setDialog(null)}
        onConfirm={() => dialog?.type === "resolve" ? resolve(dialog.alert) : acknowledge(dialog.alert)}
      >
        {dialog?.type === "resolve" && (
          <label className="dialog-field">
            Nota di risoluzione
            <textarea
              value={noteFor(dialog.alert.alert_id)}
              onChange={(event) => updateNote(dialog.alert.alert_id, event.target.value)}
              placeholder="Descrivi la verifica effettuata e l'esito"
              autoFocus
            />
            <small>Obbligatoria per chiudere la segnalazione.</small>
          </label>
        )}
      </ActionDialog>
    </section>
  );
}

function TasksView({ data, session, patientId, onChanged }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [composerOpen, setComposerOpen] = useState(false);
  const [messageComposerOpen, setMessageComposerOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [hideCancelledTasks, setHideCancelledTasks] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [noteDrafts, setNoteDrafts] = useState({});
  const [cancelDialog, setCancelDialog] = useState(null);
  const [taskForm, setTaskForm] = useState({
    template: "wellbeing",
    priority: "normal",
    title: taskTemplates.wellbeing.title,
    instructions: taskTemplates.wellbeing.instructions,
    expiresAt: "",
    medicalNote: "",
  });
  const [messageForm, setMessageForm] = useState({
    title: "Messaggio dal medico",
    body: "",
    priority: "normal",
    note: "",
    suggestionId: "",
  });

  const visibleTasks = useMemo(
    () => data.tasks.filter((task) => {
      if (hideCancelledTasks && task.status === "cancelled") return false;
      return statusFilter === "all" || task.status === statusFilter;
    }),
    [data.tasks, statusFilter, hideCancelledTasks]
  );
  const openTasks = data.tasks.filter((task) => !["completed", "cancelled", "expired"].includes(task.status)).length;
  const completedTasks = data.tasks.filter((task) => task.status === "completed").length;
  const expiredTasks = data.tasks.filter((task) => task.status === "expired").length;
  const cancelledTasks = data.tasks.filter((task) => task.status === "cancelled").length;
  const selectedTask = visibleTasks.find((task) => task.task_id === selectedTaskId) ?? visibleTasks[0] ?? null;
  const selectedTemplate = taskTemplates[taskForm.template] ?? taskTemplates.wellbeing;

  useEffect(() => {
    if (!composerOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && !busy) setComposerOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [composerOpen, busy]);

  useEffect(() => {
    if (!messageComposerOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && !busy) setMessageComposerOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [messageComposerOpen, busy]);

  function updateTaskForm(field, value) {
    if (field === "template") {
      const template = taskTemplates[value] ?? taskTemplates.wellbeing;
      setTaskForm((previous) => ({
        ...previous,
        template: value,
        title: template.title,
        instructions: template.instructions,
      }));
      return;
    }
    setTaskForm((previous) => ({ ...previous, [field]: value }));
  }

  function updateNoteDraft(taskId, value) {
    setNoteDrafts((previous) => ({ ...previous, [taskId]: value }));
  }

  function updateMessageForm(field, value) {
    setMessageForm((previous) => ({ ...previous, [field]: value }));
  }

  function applyMessageSuggestion(suggestion) {
    setMessageForm((previous) => ({
      ...previous,
      title: suggestion.title,
      body: suggestion.body,
      priority: suggestion.priority,
      suggestionId: suggestion.id,
    }));
    setError("");
  }

  async function sendPatientMessage() {
    const title = messageForm.title.trim() || "Messaggio dal medico";
    const body = messageForm.body.trim();
    if (!body) {
      setError("Scrivi il testo del messaggio prima di inviarlo.");
      return;
    }
    setBusy("message");
    setError("");
    setSuccess("");
    try {
      const payload = {
        type: "custom",
        schema_version: 1,
        priority: messageForm.priority,
        assigned_to: "patient",
        title,
        instructions: body,
        payload: {
          kind: "patient_message",
          delivery: {
            push_notification: true,
            in_app_banner: true,
          },
          suggestion_id: messageForm.suggestionId || null,
          message: {
            title,
            body,
            tone: messageForm.priority,
          },
        },
        medical_note: messageForm.note.trim() || null,
      };
      const created = await api.createTask(patientId, payload, session);
      setMessageComposerOpen(false);
      setSelectedTaskId(created.task_id);
      setMessageForm({
        title: "Messaggio dal medico",
        body: "",
        priority: "normal",
        note: "",
        suggestionId: "",
      });
      setSuccess("Messaggio inviato al paziente. L'app companion potra mostrarlo come notifica o banner in-app.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function createTask() {
    if (!taskForm.title.trim()) {
      setError("Inserisci un titolo per l'attività.");
      return;
    }
    setBusy("create");
    setError("");
    setSuccess("");
    try {
      const template = taskTemplates[taskForm.template] ?? taskTemplates.wellbeing;
      const payload = {
        type: template.type,
        schema_version: 1,
        priority: taskForm.priority,
        assigned_to: "patient",
        title: taskForm.title.trim(),
        instructions: taskForm.instructions.trim() || null,
        payload: template.payload,
        scoring: template.scoring,
        medical_note: taskForm.medicalNote.trim() || null,
      };
      if (taskForm.expiresAt) payload.expires_at = new Date(taskForm.expiresAt).toISOString();
      const created = await api.createTask(patientId, payload, session);
      setComposerOpen(false);
      setSelectedTaskId(created.task_id);
      setSuccess("Attività inviata correttamente al paziente.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function saveMedicalNote(task) {
    const draft = (noteDrafts[task.task_id] ?? task.medical_note ?? "").trim();
    if (!draft) {
      setError("Inserisci una nota prima di salvarla.");
      return;
    }
    setBusy(`note:${task.task_id}`);
    setError("");
    setSuccess("");
    try {
      await api.updateTaskMedicalNote(task.task_id, draft, session);
      setSuccess("Nota medico aggiornata.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function cancelTask(task) {
    const note = (noteDrafts[`cancel:${task.task_id}`] ?? "").trim();
    setBusy(`cancel:${task.task_id}`);
    setError("");
    setSuccess("");
    try {
      await api.cancelTask(task.task_id, note, session);
      setCancelDialog(null);
      setSuccess("Task annullato.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel page-panel tasks-page">
      <div className="view-heading">
        <div className="view-heading-copy">
          <span className="view-heading-icon task"><ClipboardList size={22} /></span>
          <div>
            <h3>Attività per il paziente</h3>
            <p>Check-in e follow-up inviati all'applicazione companion.</p>
          </div>
        </div>
        <div className="view-heading-actions">
        <button className="secondary-button" type="button" onClick={() => setMessageComposerOpen(true)} disabled={Boolean(busy)}>
          <MessageSquare size={17} />
          Messaggio paziente
        </button>
        <button className="primary-button" type="button" onClick={() => setComposerOpen(true)} disabled={Boolean(busy)}>
          <Plus size={17} />
          Nuova attività
        </button>
        </div>
      </div>
      <div className="task-overview">
        <div><span>Totali</span><strong>{data.tasks.length}</strong></div>
        <div><span>Da completare</span><strong>{openTasks}</strong></div>
        <div><span>Completate</span><strong>{completedTasks}</strong></div>
        <div><span>Scadute</span><strong>{expiredTasks}</strong></div>
        <div><span>Annullate</span><strong>{cancelledTasks}</strong></div>
        <label>
          Stato
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">Tutte</option>
            <option value="created">Create</option>
            <option value="sent">Inviate</option>
            <option value="seen">Viste</option>
            <option value="completed">Completate</option>
            <option value="expired">Scadute</option>
            <option value="cancelled">Annullate</option>
          </select>
        </label>
        <button
          className="text-button task-clean-button"
          type="button"
          onClick={() => {
            const nextHideCancelledTasks = !hideCancelledTasks;
            setHideCancelledTasks(nextHideCancelledTasks);
            if (nextHideCancelledTasks && statusFilter === "cancelled") setStatusFilter("all");
          }}
          disabled={cancelledTasks === 0}
        >
          {hideCancelledTasks ? "Mostra annullate" : "Pulisci annullate"}
        </button>
      </div>
      {error && <p className="inline-feedback error" role="alert"><AlertTriangle size={17} />{error}</p>}
      {success && <p className="inline-feedback success" role="status"><CheckCircle2 size={17} />{success}</p>}
      {messageComposerOpen && (
        <div
          className="task-composer-backdrop"
          role="presentation"
          onMouseDown={(event) => event.target === event.currentTarget && !busy && setMessageComposerOpen(false)}
        >
          <section className="task-composer-panel patient-message-composer" aria-label="Messaggio paziente">
            <div className="task-composer-header">
              <span className="dialog-icon"><MessageSquare size={20} /></span>
              <div>
                <h3>Messaggio al paziente</h3>
                <p>Invia una comunicazione personalizzata che l'app companion potra mostrare come notifica o avviso in-app.</p>
              </div>
              <button className="dialog-close" type="button" onClick={() => !busy && setMessageComposerOpen(false)} disabled={Boolean(busy)} aria-label="Chiudi">
                <X size={19} />
              </button>
            </div>
            <div className="patient-message-body">
              <div className="message-suggestion-grid" aria-label="Messaggi consigliati">
                {patientMessageSuggestions.map((suggestion) => (
                  <button
                    key={suggestion.id}
                    className={messageForm.suggestionId === suggestion.id ? "active" : ""}
                    type="button"
                    onClick={() => applyMessageSuggestion(suggestion)}
                  >
                    <strong>{suggestion.title}</strong>
                    <span>{suggestion.body}</span>
                  </button>
                ))}
              </div>
              <div className="task-form-grid patient-message-form">
                <label>
                  Priorita
                  <select value={messageForm.priority} onChange={(event) => updateMessageForm("priority", event.target.value)}>
                    <option value="normal">Ordinaria</option>
                    <option value="high">Alta</option>
                    <option value="urgent">Urgente</option>
                  </select>
                </label>
                <label>
                  Titolo notifica
                  <input value={messageForm.title} onChange={(event) => updateMessageForm("title", event.target.value)} maxLength={90} />
                </label>
                <label className="span-2">
                  Testo del messaggio
                  <textarea
                    value={messageForm.body}
                    onChange={(event) => updateMessageForm("body", event.target.value)}
                    placeholder="Scrivi qui il messaggio che il paziente dovra leggere nell'app companion."
                    maxLength={600}
                  />
                </label>
                <label className="span-2">
                  Nota interna facoltativa
                  <textarea
                    value={messageForm.note}
                    onChange={(event) => updateMessageForm("note", event.target.value)}
                    placeholder="Nota visibile nello storico medico, non necessariamente mostrata al paziente."
                    maxLength={400}
                  />
                </label>
              </div>
            </div>
            <div className="task-composer-actions">
              <button className="secondary-button" type="button" onClick={() => !busy && setMessageComposerOpen(false)} disabled={Boolean(busy)}>
                Annulla
              </button>
              <button className="primary-button" type="button" onClick={sendPatientMessage} disabled={busy === "message"}>
                {busy === "message" ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
                {busy === "message" ? "Invio" : "Invia messaggio"}
              </button>
            </div>
          </section>
        </div>
      )}
      {composerOpen && (
        <div
          className="task-composer-backdrop"
          role="presentation"
          onMouseDown={(event) => event.target === event.currentTarget && !busy && setComposerOpen(false)}
        >
        <section className="task-composer-panel" aria-label="Nuova attività">
          <div className="task-composer-header">
            <span className="dialog-icon"><ClipboardList size={20} /></span>
            <div>
              <h3>Nuova attività</h3>
              <p>Prepara un contenuto da inviare al paziente tramite l'app companion.</p>
            </div>
            <button className="dialog-close" type="button" onClick={() => !busy && setComposerOpen(false)} disabled={Boolean(busy)} aria-label="Chiudi">
              <X size={19} />
            </button>
          </div>
          <div className="task-form-grid">
            <label>
              Tipo test
              <select value={taskForm.template} onChange={(event) => updateTaskForm("template", event.target.value)}>
                {Object.entries(taskTemplates).map(([key, template]) => (
                  <option key={key} value={key}>{template.label}</option>
                ))}
              </select>
            </label>
            <label>
              Priorità
              <select value={taskForm.priority} onChange={(event) => updateTaskForm("priority", event.target.value)}>
                <option value="normal">Ordinaria</option>
                <option value="high">Alta</option>
                <option value="urgent">Urgente</option>
              </select>
            </label>
            <label className="span-2">
              Titolo
              <input value={taskForm.title} onChange={(event) => updateTaskForm("title", event.target.value)} maxLength={120} />
            </label>
            <div className="span-2 task-template-preview">
              <strong>{selectedTemplate.label}</strong>
              <span>{selectedTemplate.expectedScore}</span>
            </div>
            <label className="span-2">
              Istruzioni
              <textarea value={taskForm.instructions} onChange={(event) => updateTaskForm("instructions", event.target.value)} placeholder="Indicazioni visibili al paziente" />
            </label>
            <label className="span-2">
              Scadenza facoltativa
              <input type="datetime-local" value={taskForm.expiresAt} onChange={(event) => updateTaskForm("expiresAt", event.target.value)} />
            </label>
            <label className="span-2">
              Nota medico facoltativa
              <textarea value={taskForm.medicalNote} onChange={(event) => updateTaskForm("medicalNote", event.target.value)} placeholder="Nota visibile nello storico del task" />
            </label>
          </div>
          <div className="task-composer-actions">
            <button className="secondary-button" type="button" onClick={() => !busy && setComposerOpen(false)} disabled={Boolean(busy)}>
              Annulla
            </button>
            <button className="primary-button" type="button" onClick={createTask} disabled={busy === "create"}>
              {busy === "create" ? <LoaderCircle className="spin" size={17} /> : <CheckCircle2 size={17} />}
              {busy === "create" ? "Salvataggio" : "Crea e invia"}
            </button>
          </div>
        </section>
        </div>
      )}
      {data.tasks.length === 0 ? (
        <ViewEmptyState icon={<ClipboardList size={24} />} title="Nessuna attività assegnata" text="Crea un check-in o un follow-up per iniziare." />
      ) : visibleTasks.length === 0 ? (
        <ViewEmptyState icon={<Search size={24} />} title="Nessun risultato" text="Non ci sono attività con lo stato selezionato." />
      ) : (
        <div className="task-list">
          {visibleTasks.map((task) => (
            <article
              key={task.task_id}
              className={`task-item priority-${task.priority ?? "normal"} ${selectedTask?.task_id === task.task_id ? "selected" : ""}`}
              onClick={() => setSelectedTaskId(task.task_id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") setSelectedTaskId(task.task_id);
              }}
              role="button"
              tabIndex={0}
            >
              <span className="task-type-icon">{taskIcon(task)}</span>
              <div className="task-main">
                <div className="task-title-row">
                  <span className={`priority-chip ${task.priority ?? "normal"}`}>{taskPriorityLabel(task.priority)}</span>
                  <span className={`status-pill ${task.status}`}>{taskStatusLabel(task.status)}</span>
                </div>
                <h4>{task.title}</h4>
                <p>{task.instructions ?? "Nessuna istruzione aggiuntiva."}</p>
                <div className="task-meta">
                  <span><Info size={14} /> {taskDisplayType(task)}</span>
                  <span><CalendarClock size={14} /> Creata {formatDateTime(task.created_at)}</span>
                  {task.due_at && <span><Clock3 size={14} /> Scadenza {formatDateTime(task.due_at)}</span>}
                  {task.result?.completed_at && <span><CheckCircle2 size={14} /> Completata {formatDateTime(task.result.completed_at)}</span>}
                </div>
              </div>
              <ChevronRight className="task-chevron" size={18} />
            </article>
          ))}
        </div>
      )}
      {selectedTask && (
        <TaskDetailPanel
          task={selectedTask}
          noteDraft={noteDrafts[selectedTask.task_id] ?? selectedTask.medical_note ?? ""}
          cancelNote={noteDrafts[`cancel:${selectedTask.task_id}`] ?? ""}
          busy={busy}
          onNoteChange={(value) => updateNoteDraft(selectedTask.task_id, value)}
          onCancelNoteChange={(value) => updateNoteDraft(`cancel:${selectedTask.task_id}`, value)}
          onSaveNote={() => saveMedicalNote(selectedTask)}
          onAskCancel={() => setCancelDialog(selectedTask)}
        />
      )}
      <ActionDialog
        open={Boolean(cancelDialog)}
        icon={<X size={22} />}
        title="Annulla task"
        description="Il task non sara piu completabile dall'app paziente."
        confirmLabel="Conferma annullamento"
        busy={Boolean(cancelDialog && busy === `cancel:${cancelDialog.task_id}`)}
        onClose={() => !busy && setCancelDialog(null)}
        onConfirm={() => cancelDialog && cancelTask(cancelDialog)}
      >
        {cancelDialog && (
          <label className="dialog-field">
            Nota annullamento
            <textarea
              value={noteDrafts[`cancel:${cancelDialog.task_id}`] ?? ""}
              onChange={(event) => updateNoteDraft(`cancel:${cancelDialog.task_id}`, event.target.value)}
              placeholder="Motivo dell'annullamento"
              autoFocus
            />
          </label>
        )}
      </ActionDialog>
    </section>
  );
}

function TaskDetailPanel({ task, noteDraft, cancelNote, busy, onNoteChange, onCancelNoteChange, onSaveNote, onAskCancel }) {
  const result = task.result ?? task.latest_result ?? task.task_result ?? null;
  const answers = taskResultAnswers(result);
  const canCancel = !["completed", "cancelled", "expired"].includes(task.status);
  return (
    <div className="task-detail-panel">
      <div className="task-detail-header">
        <div>
          <span className="detail-eyebrow">{taskDisplayType(task)}</span>
          <h4>{task.title}</h4>
        </div>
        <span className={`status-pill ${task.status}`}>{taskStatusLabel(task.status)}</span>
      </div>

      <div className="task-detail-grid">
        <Detail label="Priorita" value={taskPriorityLabel(task.priority)} />
        <Detail label="Destinatario" value={taskAssigneeLabel(task.assigned_to)} />
        <Detail label="Scadenza" value={task.due_at ? formatDateTime(task.due_at) : "Non impostata"} />
        <Detail label="Score previsto" value={expectedTaskScore(task)} />
        <Detail label="Completamento" value={result?.completed_at ? formatDateTime(result.completed_at) : "Non completato"} />
        <Detail label="Durata" value={formatTaskDuration(result?.duration_seconds)} />
      </div>

      <div className="task-result-card">
        <div className="task-result-title">
          <strong>Risultato ricevuto</strong>
          <span>{taskResultScoreLabel(result)}</span>
        </div>
        {result ? (
          <>
            {result.score_details?.reason && <p className="task-result-note">{result.score_details.reason}</p>}
            {answers.length > 0 ? (
              <dl className="task-answer-list">
                {answers.map((answer, index) => (
                  <React.Fragment key={`${answer.question_id ?? "answer"}-${index}`}>
                    <dt>{answer.question_text ?? answer.question_id ?? `Risposta ${index + 1}`}</dt>
                    <dd>{String(answer.value ?? answer.answer ?? "n/d")}</dd>
                  </React.Fragment>
                ))}
              </dl>
            ) : (
              <p className="empty-text compact">Il backend ha ricevuto il completamento, ma non sono presenti risposte strutturate.</p>
            )}
            {result.note && <p className="task-result-note">Nota paziente: {result.note}</p>}
          </>
        ) : (
          <p className="empty-text compact">In attesa del completamento dall'app paziente.</p>
        )}
      </div>

      <label className="task-note-box">
        Nota medico sul risultato
        <textarea value={noteDraft} onChange={(event) => onNoteChange(event.target.value)} placeholder="Aggiungi una nota clinica o operativa per lo storico" />
      </label>
      <div className="task-detail-actions">
        <button className="secondary-button" type="button" onClick={onSaveNote} disabled={Boolean(busy)}>
          <CheckCircle2 size={16} />
          Salva nota
        </button>
        {canCancel && (
          <>
            <label className="cancel-note-inline">
              Motivo annullamento
              <input value={cancelNote} onChange={(event) => onCancelNoteChange(event.target.value)} placeholder="Facoltativo" />
            </label>
            <button className="text-button danger" type="button" onClick={onAskCancel} disabled={Boolean(busy)}>
              <X size={16} />
              Annulla task
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function ActionDialog({ open, icon, title, description, confirmLabel, busy, wide = false, onClose, onConfirm, children }) {
  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    document.body.classList.add("dialog-open");
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.classList.remove("dialog-open");
    };
  }, [open, busy, onClose]);

  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
      <section className={`action-dialog ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <div className="dialog-header">
          <span className="dialog-icon">{icon}</span>
          <div><h3 id="dialog-title">{title}</h3><p>{description}</p></div>
          <button className="dialog-close" type="button" onClick={onClose} disabled={busy} aria-label="Chiudi"><X size={19} /></button>
        </div>
        {children && <div className="dialog-body">{children}</div>}
        <div className="dialog-actions">
          <button className="secondary-button" type="button" onClick={onClose} disabled={busy}>Annulla</button>
          <button className="primary-button" type="button" onClick={onConfirm} disabled={busy}>
            {busy ? <LoaderCircle className="spin" size={17} /> : <CheckCircle2 size={17} />}
            {busy ? "Salvataggio" : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}

function ViewEmptyState({ icon, title, text }) {
  return (
    <div className="view-empty-state">
      <span>{icon}</span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function SystemView({ data, events, wsStatus }) {
  const status = data.system ?? {};
  const edge = status.edge ?? {};
  const sensors = status.sensors ?? {};
  const watch = sensors.watch ?? {};
  const ble = sensors.ble ?? {};
  const googleHealth = sensors.google_health ?? {};
  const mqtt = edge.mqtt ?? {};
  const health = systemHealth(status, wsStatus);
  const issues = systemIssueGroups(status, wsStatus);
  const availableFeatures = Array.isArray(googleHealth.available_features)
    ? googleHealth.available_features
    : [];
  const mqttErrors = Array.isArray(mqtt.errors) ? mqtt.errors.filter(Boolean) : [];

  return (
    <div className="content-grid system-board">
      <section className={`panel span-2 system-overview-panel ${health.tone}`}>
        <div className="panel-heading">
          <div className="system-title-row">
            <span className="system-title-icon"><MonitorCog size={22} /></span>
            <div>
              <h3>Stato tecnico del sistema</h3>
              <p className="panel-subtitle">
                Monitoraggio operativo di Raspberry, sensori, Google Health, MQTT e qualita dati.
              </p>
            </div>
          </div>
          <span className={`system-health-badge ${health.tone}`}>{health.label}</span>
        </div>
        <div className="system-hero-grid">
          <SystemStatusCard
            icon={<Server size={20} />}
            title="Raspberry Pi 5"
            value={edge.online ? "Online" : "Offline"}
            caption={`Ultimo contatto: ${formatDateTime(edge.last_seen_at ?? status.updated_at)}`}
            tone={edge.online ? "good" : "error"}
          />
          <SystemStatusCard
            icon={<Clock3 size={20} />}
            title="Ultimo ciclo Edge"
            value={formatDateTime(edge.last_cycle_at)}
            caption={`Finestra ${formatWindowRange(edge.window_start, edge.window_end)} - ${formatDurationMinutes(edge.window_minutes)}`}
            tone={edge.last_cycle_at ? "good" : "warning"}
          />
          <SystemStatusCard
            icon={<Gauge size={20} />}
            title="Qualita dati"
            value={qualityStatusLabel(edge.quality_status)}
            caption={`${formatNumber(edge.quality_error_count, "0")} errori, ${formatNumber(edge.quality_warning_count, "0")} warning`}
            tone={statusTone(edge.quality_status)}
          />
          <SystemStatusCard
            icon={<Wifi size={20} />}
            title="Coda MQTT locale"
            value={`${formatNumber(edge.mqtt_queue_depth ?? 0, "0")} messaggi`}
            caption={mqtt.status ? `Stato pubblicazione: ${mqttStatusLabel(mqtt.status)}` : "Nessuna diagnostica MQTT ricevuta"}
            tone={Number(edge.mqtt_queue_depth ?? 0) > 0 ? "warning" : statusTone(mqtt.status)}
          />
        </div>
      </section>

      <section className="panel span-2">
        <div className="panel-heading">
          <h3>Sensori e flussi dati</h3>
          <span className="badge">E8</span>
        </div>
        <div className="sensor-status-grid">
          <SensorCard
            icon={<Watch size={19} />}
            title="Wearable"
            status={watch.present === false ? "missing" : watch.status}
            details={[
              ["Presenza", watch.present === false ? "Non rilevato" : "Rilevato"],
              ["Batteria", watch.battery_pct === null || watch.battery_pct === undefined ? "n/d" : `${watch.battery_pct}%`],
              ["Ultimo dato", formatDateTime(watch.last_seen_at)],
            ]}
          />
          <SensorCard
            icon={<MapPin size={19} />}
            title="Beacon BLE"
            status={ble.status}
            details={[
              ["Stanza", roomLabel(ble.current_room)],
              ["Campioni ciclo", formatNumber(ble.samples_collected)],
              ["Ultimo dato", formatDateTime(ble.last_seen_at)],
            ]}
          />
          <SensorCard
            icon={<Activity size={19} />}
            title="Google Health"
            status={googleHealth.status}
            details={[
              ["Feature disponibili", formatNumber(googleHealth.available_feature_count ?? availableFeatures.length, "0")],
              ["Ultima finestra", formatDateTime(googleHealth.last_window_at)],
              ["OAuth", googleHealth.oauth_error ? "Errore da verificare" : "Nessun errore segnalato"],
            ]}
          />
          <SensorCard
            icon={<Wifi size={19} />}
            title="Realtime dashboard"
            status={wsStatus === "connected" ? "active" : wsStatus}
            details={[
              ["WebSocket", websocketStatusLabel(wsStatus)],
              ["Eventi recenti", events.length],
              ["Fonte dati", config.dataSource],
            ]}
          />
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h3>Google Health e OAuth</h3>
          <span className={`feature-status compact-status ${googleHealth.oauth_error ? "imputed" : "acquired"}`}>
            {googleHealth.oauth_error ? "attenzione" : "ok"}
          </span>
        </div>
        <dl className="detail-list">
          <Detail label="Stato" value={systemStatusLabel(googleHealth.status)} />
          <Detail label="Campioni salvati" value={formatBoolean(googleHealth.samples_logged)} />
          <Detail label="Feature" value={availableFeatures.length ? availableFeatures.map(clinicalFeatureName).join(", ") : "n/d"} />
          <Detail label="Errore OAuth" value={googleHealth.oauth_error ?? "Nessun errore OAuth ricevuto dal backend"} />
        </dl>
        <p className="system-safe-note">
          La dashboard mostra solo messaggi ripuliti: token, refresh token, password e client secret non vengono esposti.
        </p>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h3>MQTT e coda locale</h3>
          <span className={`feature-status compact-status ${Number(edge.mqtt_queue_depth ?? 0) > 0 ? "imputed" : "acquired"}`}>
            {Number(edge.mqtt_queue_depth ?? 0) > 0 ? "in coda" : "allineato"}
          </span>
        </div>
        <dl className="detail-list">
          <Detail label="Stato" value={mqttStatusLabel(mqtt.status)} />
          <Detail label="Tentati" value={formatNumber(mqtt.attempted)} />
          <Detail label="Pubblicati" value={formatNumber(mqtt.published)} />
          <Detail label="In coda" value={formatNumber(mqtt.queue_depth ?? edge.mqtt_queue_depth)} />
        </dl>
        {mqttErrors.length > 0 ? (
          <ul className="system-error-list">
            {mqttErrors.map((error, index) => (
              <li key={`mqtt-error-${index}`}>{error}</li>
            ))}
          </ul>
        ) : (
          <p className="system-safe-note">Nessun errore MQTT segnalato nell'ultimo ciclo.</p>
        )}
      </section>

      <section className="panel span-2">
        <div className="panel-heading">
          <h3>Warning e guasti</h3>
          <span className="badge">{issues.warning.length + issues.persistent.length} segnalazioni</span>
        </div>
        <div className="system-issues-grid">
          <SystemIssueList
            title="Warning temporanei"
            emptyText="Nessun warning temporaneo rilevato."
            issues={issues.warning}
            tone="warning"
          />
          <SystemIssueList
            title="Guasti persistenti"
            emptyText="Nessun guasto persistente rilevato."
            issues={issues.persistent}
            tone="error"
          />
        </div>
      </section>

      <section className="panel span-2">
        <div className="panel-heading">
          <h3>Eventi realtime</h3>
          <StatusPill status={wsStatus} />
        </div>
        {events.length === 0 ? (
          <p className="empty-text">In attesa di eventi WebSocket.</p>
        ) : (
          <div className="event-list">
            {events.map((event) => (
              <div key={event.event_id} className="event-item">
                <Wifi size={16} />
                <span>{eventTypeLabel(event.event_type)}</span>
                <small>{formatDateTime(event.timestamp)}</small>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function SystemStatusCard({ icon, title, value, caption, tone }) {
  return (
    <article className={`system-status-card ${tone ?? "neutral"}`}>
      <span className="system-card-icon">{icon}</span>
      <div>
        <span>{title}</span>
        <strong>{value ?? "n/d"}</strong>
        <small>{caption}</small>
      </div>
    </article>
  );
}

function SensorCard({ icon, title, status, details }) {
  const tone = statusTone(status);
  return (
    <article className={`sensor-status-card ${tone}`}>
      <div className="sensor-status-header">
        <span className="sensor-status-icon">{icon}</span>
        <div>
          <strong>{title}</strong>
          <span className={`technical-status-chip ${tone}`}>{systemStatusLabel(status)}</span>
        </div>
      </div>
      <dl className="mini-detail-list">
        {details.map(([label, value]) => (
          <React.Fragment key={`${title}-${label}`}>
            <dt>{label}</dt>
            <dd>{value ?? "n/d"}</dd>
          </React.Fragment>
        ))}
      </dl>
    </article>
  );
}

function SystemIssueList({ title, emptyText, issues, tone }) {
  return (
    <div className={`system-issue-column ${tone}`}>
      <h4>{title}</h4>
      {issues.length === 0 ? (
        <p className="empty-text">{emptyText}</p>
      ) : (
        <div className="system-issue-list">
          {issues.map((issue) => (
            <div className={`system-issue ${issue.tone}`} key={`${title}-${issue.title}-${issue.detail}`}>
              <AlertTriangle size={17} />
              <div>
                <strong>{issue.title}</strong>
                <span>{issue.detail}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function systemHealth(status, wsStatus) {
  const edge = status?.edge ?? {};
  const sensors = status?.sensors ?? {};
  const mqtt = edge.mqtt ?? {};
  if (
    edge.online === false ||
    statusTone(edge.quality_status) === "error" ||
    statusTone(sensors.google_health?.status) === "error" ||
    statusTone(mqtt.status) === "error"
  ) {
    return { tone: "error", label: "Guasto da verificare" };
  }
  if (
    statusTone(edge.quality_status) === "warning" ||
    statusTone(sensors.ble?.status) === "warning" ||
    statusTone(sensors.watch?.status) === "warning" ||
    sensors.watch?.present === false ||
    statusTone(sensors.google_health?.status) === "warning" ||
    Number(edge.mqtt_queue_depth ?? 0) > 0 ||
    wsStatus !== "connected"
  ) {
    return { tone: "warning", label: "Attenzione tecnica" };
  }
  return { tone: "good", label: "Operativo" };
}

function systemIssueGroups(status, wsStatus) {
  const edge = status?.edge ?? {};
  const sensors = status?.sensors ?? {};
  const watch = sensors.watch ?? {};
  const ble = sensors.ble ?? {};
  const googleHealth = sensors.google_health ?? {};
  const mqtt = edge.mqtt ?? {};
  const warning = [];
  const persistent = [];

  function add(target, title, detail, tone = target === persistent ? "error" : "warning") {
    target.push({ title, detail, tone });
  }

  if (edge.online === false) {
    add(persistent, "Raspberry offline", "L'ultimo stato ricevuto indica Edge non raggiungibile.", "error");
  } else if (isStale(edge.last_seen_at ?? status?.updated_at)) {
    add(warning, "Contatto Raspberry obsoleto", "L'ultimo contatto e' piu vecchio della soglia configurata.");
  }

  if (edge.quality_status === "error") {
    add(persistent, "Qualita dati non utilizzabile", `${formatNumber(edge.quality_error_count, "0")} errori nell'ultimo ciclo.`, "error");
  } else if (edge.quality_status === "warning") {
    add(warning, "Qualita dati con warning", `${formatNumber(edge.quality_warning_count, "0")} warning nell'ultimo ciclo.`);
  }

  if (Number(edge.mqtt_queue_depth ?? 0) > 0) {
    add(warning, "Messaggi MQTT in coda", `${formatNumber(edge.mqtt_queue_depth, "0")} messaggi attendono ritrasmissione.`);
  }
  if (statusTone(mqtt.status) === "error") {
    add(persistent, "Errore MQTT", mqttStatusLabel(mqtt.status), "error");
  }

  if (watch.present === false || ["missing", "stale"].includes(String(watch.status))) {
    add(warning, "Wearable non stabile", "Watch assente o non aggiornato nell'ultima finestra.");
  }
  if (Number(watch.battery_pct) > 0 && Number(watch.battery_pct) < 20) {
    add(warning, "Batteria wearable bassa", `Batteria rilevata al ${watch.battery_pct}%.`);
  }

  if (["missing", "stale"].includes(String(ble.status))) {
    add(warning, "BLE non aggiornato", "I beacon non hanno prodotto campioni recenti per la finestra corrente.");
  }
  if (googleHealth.oauth_error) {
    add(persistent, "OAuth Google Health", googleHealth.oauth_error, "error");
  } else if (["stale", "missing"].includes(String(googleHealth.status))) {
    add(warning, "Google Health non aggiornato", "Il backend non vede feature wearable recenti.");
  }

  if (wsStatus !== "connected") {
    add(warning, "Realtime non connesso", `Stato WebSocket: ${websocketStatusLabel(wsStatus)}.`);
  }

  return { warning, persistent };
}

function statusTone(status) {
  const normalized = String(status ?? "").toLowerCase();
  if (["active", "online", "ok", "published", "connected", "cycle_completed", "completed"].includes(normalized)) {
    return "good";
  }
  if (["error", "offline", "runtime_mqtt_error", "invalid_event", "failed"].includes(normalized)) {
    return "error";
  }
  if (["warning", "stale", "missing", "reconnecting", "connecting", "queued"].includes(normalized)) {
    return "warning";
  }
  return "neutral";
}

function systemStatusLabel(status) {
  const labels = {
    active: "Attivo",
    online: "Online",
    ok: "Regolare",
    warning: "Warning",
    error: "Errore",
    stale: "Non aggiornato",
    missing: "Non rilevato",
    disabled: "Disabilitato",
    connected: "Connesso",
    reconnecting: "Riconnessione",
    connecting: "Connessione",
    published: "Pubblicato",
    queued: "In coda",
    offline: "Offline",
    cycle_completed: "Ciclo completato",
    runtime_mqtt_error: "Errore MQTT runtime",
  };
  return labels[String(status ?? "").toLowerCase()] ?? (status ? String(status) : "n/d");
}

function qualityStatusLabel(status) {
  return {
    ok: "Regolare",
    warning: "Warning",
    error: "Non utilizzabile",
    unknown: "Non disponibile",
  }[String(status ?? "").toLowerCase()] ?? systemStatusLabel(status);
}

function mqttStatusLabel(status) {
  return {
    published: "Pubblicazione completata",
    queued: "Accodato per ritrasmissione",
    runtime_mqtt_error: "Errore runtime MQTT",
    disabled: "Disabilitato",
  }[String(status ?? "").toLowerCase()] ?? systemStatusLabel(status);
}

function websocketStatusLabel(status) {
  return {
    idle: "Inattivo",
    connecting: "Connessione",
    connected: "Connesso",
    reconnecting: "Riconnessione",
    error: "Errore",
    invalid_event: "Evento non valido",
  }[status] ?? systemStatusLabel(status);
}

function eventTypeLabel(eventType) {
  return {
    system_status_updated: "Stato tecnico aggiornato",
    decision_updated: "Decisione AI aggiornata",
    alert_created: "Nuovo alert",
    alert_acknowledged: "Alert preso in carico",
    alert_resolved: "Alert risolto",
    task_created: "Task creato",
    task_completed: "Task completato",
    task_cancelled: "Task annullato",
    patient_window_updated: "Finestra dati aggiornata",
    edge_cycle_completed: "Ciclo Edge completato",
    pong: "Heartbeat realtime",
  }[eventType] ?? eventType ?? "Evento realtime";
}

function clinicalFeatureName(feature) {
  return clinicalFeature(feature).label;
}

function formatNumber(value, fallback = "n/d") {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(1);
}

function scoreBandText(value) {
  const band = aiScoreBand(value);
  if (band.key === "unknown") return "n/d";
  return `${scoreText(value)} - ${band.label}`;
}

function formatDurationMinutes(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "durata non disponibile";
  return `${Number(numeric.toFixed(1))} min`;
}

function formatWindowRange(start, end) {
  if (!start || !end) return "non disponibile";
  return `${formatShortDateTime(start)} - ${formatShortDateTime(end)}`;
}

function formatBoolean(value) {
  if (value === true) return "Si";
  if (value === false) return "No";
  return "n/d";
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

function sortRecentWindows(windows, sort) {
  const direction = sort.direction === "asc" ? 1 : -1;
  return [...windows].sort((left, right) => {
    const leftValue = recentWindowSortValue(left, sort.key);
    const rightValue = recentWindowSortValue(right, sort.key);
    const leftMissing = leftValue === null || leftValue === undefined || Number.isNaN(leftValue);
    const rightMissing = rightValue === null || rightValue === undefined || Number.isNaN(rightValue);
    if (leftMissing && rightMissing) return 0;
    if (leftMissing) return 1;
    if (rightMissing) return -1;
    if (leftValue < rightValue) return -1 * direction;
    if (leftValue > rightValue) return 1 * direction;
    return 0;
  });
}

function recentWindowSortValue(window, key) {
  if (key === "window_end") {
    const timestamp = new Date(window.window_end ?? window.window_start ?? 0).getTime();
    return Number.isFinite(timestamp) ? timestamp : null;
  }
  const value = window.features?.[key];
  if (isMissingValue(value)) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : String(value).toLowerCase();
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

function categoryLabel(category) {
  const labels = {
    behavioral: "Comportamentale",
    clinical: "Clinica",
    technical: "Tecnica",
    wandering: "Spostamenti notturni",
    inactivity: "Riduzione dell'attività",
    wearable: "Parametri wearable",
    spatial: "Routine spaziale",
  };
  if (!category) return "Non specificata";
  return labels[category] ?? String(category)
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}

function taskStatusLabel(status) {
  return {
    created: "Creata",
    sent: "Inviata",
    seen: "Vista",
    delivered: "Consegnata",
    opened: "Aperta",
    completed: "Completata",
    expired: "Scaduta",
    cancelled: "Annullata",
  }[status] ?? categoryLabel(status);
}

function taskTypeLabel(type) {
  return {
    check_in: "Check-in benessere",
    cognitive_test: "Test cognitivo",
    mobility_test: "Test motorio",
    medication_reminder: "Promemoria terapia",
    custom: "Follow-up libero",
  }[type] ?? categoryLabel(type);
}

function isPatientMessageTask(task) {
  const payload = task?.payload?.content ?? task?.payload ?? {};
  return (task?.type ?? task?.task_type) === "custom" && payload?.kind === "patient_message";
}

function taskDisplayType(task) {
  if (isPatientMessageTask(task)) return "Messaggio paziente";
  return taskTypeLabel(task?.type ?? task?.task_type);
}

function taskAssigneeLabel(value) {
  return {
    patient: "Paziente",
    caregiver: "Caregiver",
  }[value] ?? "Paziente";
}

function taskIcon(task) {
  const type = task.type ?? task.task_type;
  if (isPatientMessageTask(task)) return <MessageSquare size={19} />;
  if (type === "cognitive_test") return <BrainCircuit size={19} />;
  if (type === "check_in") return <HeartPulse size={19} />;
  return <ClipboardList size={19} />;
}

function taskPriorityLabel(priority) {
  return {
    low: "Bassa",
    normal: "Ordinaria",
    medium: "Media",
    high: "Alta",
    urgent: "Urgente",
    technical: "Tecnica",
  }[priority] ?? "Ordinaria";
}

function taskPriorityForAlert(level) {
  if (level === "red") return "high";
  if (level === "orange") return "medium";
  if (level === "technical") return "technical";
  return "normal";
}

function expectedTaskScore(task) {
  const scoring = task.scoring ?? task.payload?.scoring;
  if (scoring?.type === "exact_match") return "0-100, risposte esatte";
  const questionnaire = task.payload?.questionnaire;
  if (["mmse_official_supervised", "moca_official_supervised"].includes(questionnaire)) return "0-30, modulo ufficiale";
  if (questionnaire === "phq_2_demo") return "0-6, da validare";
  return "Non previsto";
}

function taskResultScoreLabel(result) {
  if (!result) return "Risultato assente";
  const score = result.score ?? result.score_details?.score;
  if (score === null || score === undefined) return "Score non calcolato";
  return `Score ${formatNumber(score)}`;
}

function formatTaskDuration(seconds) {
  const numeric = Number(seconds);
  if (!Number.isFinite(numeric)) return "Non disponibile";
  if (numeric < 60) return `${Math.round(numeric)} sec`;
  const minutes = Math.floor(numeric / 60);
  const rest = Math.round(numeric % 60);
  return rest ? `${minutes} min ${rest} sec` : `${minutes} min`;
}

function taskResultAnswers(result) {
  if (!result) return [];
  const answers = result.answers ?? result.content?.answers ?? [];
  return Array.isArray(answers) ? answers.filter(Boolean) : [];
}

function Metric({ icon, label, value, tone }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      {icon && <span className="metric-icon">{icon}</span>}
      <div><span>{label}</span><strong>{value}</strong></div>
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

function patientInitials(name) {
  if (!name) return "P";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "P";
}
