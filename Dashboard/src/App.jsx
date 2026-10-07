import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowDownUp,
  Bell,
  BrainCircuit,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  ClipboardList,
  DatabaseZap,
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
  Maximize2,
  Plus,
  RefreshCcw,
  Search,
  Send,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserRound,
  UserRoundCheck,
  Users,
  Watch,
  Wifi,
  X,
} from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, clearSession, loadSession, saveSession } from "./api/client.js";
import { readableApiError } from "./api/errors.js";
import { openPatientSocket } from "./api/realtime.js";
import { Detail, Metric, StatusPill, ViewEmptyState } from "./components/common/ClinicalPrimitives.jsx";
import { config } from "./config.js";
import { aiScoreBand, formatDateTime, isStale, levelLabel, scoreText } from "./utils/format.js";

const tabs = [
  { id: "patient", label: "Quadro clinico", shortLabel: "Paziente", icon: HeartPulse },
  { id: "timeline", label: "Timeline", shortLabel: "Timeline", icon: CalendarClock },
  { id: "evaluations", label: "Valutazioni", shortLabel: "Valutazioni", icon: BrainCircuit },
  { id: "day-profile", label: "Giornata tipo", shortLabel: "Giornata", icon: Activity },
  { id: "routine", label: "Routine ambientale", shortLabel: "Routine", icon: Home },
  { id: "alerts", label: "Segnalazioni", shortLabel: "Alert", icon: AlertTriangle },
  { id: "tasks", label: "Attivita", shortLabel: "Task", icon: ClipboardList },
  { id: "system", label: "Stato sistema", shortLabel: "Sistema", icon: MonitorCog },
  { id: "report", label: "Report", shortLabel: "Report", icon: DatabaseZap },
];

const PATIENT_PROFILE_STORAGE_KEY = "iot_dashboard_patient_profiles_v1";
const PATIENT_DATA_CACHE_KEY = "iot_dashboard_patient_data_cache_v1";

function loadPatientDataCache(patientId) {
  if (!patientId) return null;
  try {
    const store = JSON.parse(localStorage.getItem(PATIENT_DATA_CACHE_KEY) || "{}");
    return store[patientId] ?? null;
  } catch {
    return null;
  }
}

function savePatientDataCache(patientId, data) {
  if (!patientId || !data) return;
  try {
    const store = JSON.parse(localStorage.getItem(PATIENT_DATA_CACHE_KEY) || "{}");
    store[patientId] = {
      cachedAt: new Date().toISOString(),
      data: {
        ...data,
        _offline: false,
        _offlineReason: "",
      },
    };
    localStorage.setItem(PATIENT_DATA_CACHE_KEY, JSON.stringify(store));
  } catch {
    // La cache offline e' solo un aiuto per demo: se localStorage fallisce, la UI resta online.
  }
}

function removePatientDataCache(patientId) {
  if (!patientId) return;
  try {
    const store = JSON.parse(localStorage.getItem(PATIENT_DATA_CACHE_KEY) || "{}");
    delete store[patientId];
    localStorage.setItem(PATIENT_DATA_CACHE_KEY, JSON.stringify(store));
  } catch {
    localStorage.removeItem(PATIENT_DATA_CACHE_KEY);
  }
}

const priorityOptions = [
  { value: "normal", label: "Ordinaria" },
  { value: "high", label: "Alta" },
  { value: "urgent", label: "Urgente" },
];

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
    label: "Test cognitivo breve - benessere",
    type: "check_in",
    title: "Test cognitivo breve - benessere",
    instructions: "Rispondi pensando a come ti senti oggi. Non ci sono risposte giuste o sbagliate.",
    expectedScore: "Andamento del benessere percepito",
    payload: {
      questionnaire: "short_wellbeing_checkin",
      questions: [
        { id: "overall", type: "scale", text: "Come valuti il tuo benessere generale oggi?", options: ["Molto basso", "Basso", "Discreto", "Buono", "Molto buono"] },
        { id: "mood", type: "single_choice", text: "Quale descrizione rappresenta meglio il tuo umore?", options: ["Sereno", "Abbastanza sereno", "Preoccupato", "Triste", "Irritabile"] },
        { id: "contact", type: "yes_no", text: "Vorresti essere contattato dal team di cura?" },
      ],
    },
    scoring: null,
  },
  mmse: {
    label: "MMSE - check-in benessere",
    type: "check_in",
    title: "MMSE - check-in benessere",
    instructions: "Breve autovalutazione sullo stato emotivo e sulla gestione della giornata.",
    expectedScore: "Risposte descrittive, senza punteggio diagnostico",
    payload: {
      questionnaire: "mmse_wellbeing_checkin",
      questions: [
        { id: "mood", type: "scale", text: "Come descriveresti il tuo umore oggi?", options: ["Molto negativo", "Negativo", "Neutro", "Positivo", "Molto positivo"] },
        { id: "clarity", type: "scale", text: "Quanto ti senti lucido e orientato nelle attivita di oggi?", options: ["Per niente", "Poco", "Abbastanza", "Molto", "Completamente"] },
        { id: "worry", type: "yes_no", text: "Ti senti piu confuso o preoccupato del solito?" },
        { id: "note", type: "text", text: "Vuoi aggiungere qualcosa su come ti senti?", required: false },
      ],
    },
    scoring: null,
  },
  moca: {
    label: "MoCA - check-in quotidiano",
    type: "check_in",
    title: "MoCA - check-in quotidiano",
    instructions: "Racconta come stanno andando energia, autonomia e attivita quotidiane.",
    expectedScore: "Andamento riferito dal paziente",
    payload: {
      questionnaire: "moca_daily_checkin",
      questions: [
        { id: "energy", type: "scale", text: "Quanta energia senti di avere oggi?", options: ["Nessuna", "Poca", "Moderata", "Buona", "Molta"] },
        { id: "daily_tasks", type: "single_choice", text: "Come sono andate le normali attivita quotidiane?", options: ["Senza difficolta", "Con qualche difficolta", "Con molta difficolta", "Non sono riuscito a svolgerle"] },
        { id: "sleep", type: "single_choice", text: "Come hai dormito?", options: ["Molto bene", "Bene", "Cosi cosi", "Male", "Molto male"] },
        { id: "help", type: "yes_no", text: "Hai avuto bisogno di piu aiuto del solito?" },
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

const caregiverMessageSuggestions = [
  {
    id: "wearable_help",
    title: "Verifica wearable",
    priority: "high",
    body: "Puoi verificare con calma se il dispositivo indossabile e' al polso, acceso e con batteria sufficiente? In caso di difficolta, avvisa il team di cura.",
  },
  {
    id: "gentle_contact",
    title: "Contatto di supporto",
    priority: "normal",
    body: "Ti chiediamo di contattare il paziente appena possibile per una breve verifica di benessere generale. Non e' una diagnosi automatica, ma una richiesta di supporto.",
  },
  {
    id: "routine_check",
    title: "Controllo routine",
    priority: "normal",
    body: "Puoi verificare se il paziente ha svolto le normali attivita' quotidiane e se ha bisogno di aiuto pratico?",
  },
  {
    id: "urgent_presence",
    title: "Affiancamento richiesto",
    priority: "urgent",
    body: "Quando possibile, resta vicino al paziente o contattalo telefonicamente. Il team di cura desidera un riscontro familiare tempestivo.",
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
  const [clearAllOpen, setClearAllOpen] = useState(false);
  const [clearAllPassword, setClearAllPassword] = useState("");
  const [clearAllError, setClearAllError] = useState("");
  const [clearAllBusy, setClearAllBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [profileVersion, setProfileVersion] = useState(0);
  const [patientListState, setPatientListState] = useState({ loading: true, error: "" });
  const [state, setState] = useState({ loading: false, error: "", data: null });
  const [wsStatus, setWsStatus] = useState("idle");
  const [events, setEvents] = useState([]);

  async function loadPatients(options = {}) {
    const background = options.background === true || patients.length > 0;
    setPatientListState((previous) => ({
      loading: background ? previous.loading : true,
      error: "",
    }));
    try {
      const payload = await api.patients(session);
      const items = payload.items ?? [];
      setPatients(items);
      setPatientListState({ loading: false, error: "" });
    } catch (error) {
      setPatientListState({ loading: false, error: readableApiError(error) });
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
      const optional = async (loader, fallback) => {
        try {
          return await loader();
        } catch {
          return fallback;
        }
      };
      const [
        current,
        windows,
        decisions,
        alerts,
        tasks,
        system,
        summary24h,
        timeline,
        spatialSummary,
        questionnaireTemplates,
        questionnaireSchedules,
        questionnaireResults,
        reportData,
        modelMetrics,
        dayProfile,
        weeklyReports,
        morningBrief,
        operationalMetrics,
      ] = await Promise.all([
        api.current(patientId, session),
        api.windows(patientId, session),
        api.decisions(patientId, session),
        api.alerts(patientId, session),
        api.tasks(patientId, session),
        api.systemStatus(patientId, session),
        optional(() => api.summary24h(patientId, session), null),
        optional(() => api.timeline(patientId, session), { items: [] }),
        optional(() => api.spatialSummary(patientId, session), null),
        optional(() => api.questionnaireTemplates(session), { items: [] }),
        optional(() => api.questionnaireSchedules(patientId, session, { include_suspended: true }), { items: [] }),
        optional(() => api.questionnaireResults(patientId, session), { items: [] }),
        optional(() => api.reportData(patientId, session), null),
        optional(() => api.modelMetrics(patientId, session), null),
        optional(() => api.dayProfile(patientId, session), null),
        optional(() => api.weeklyReports(patientId, session), { items: [] }),
        optional(() => api.morningBrief(patientId, session), null),
        optional(() => api.metrics(session), null),
      ]);
      const nextData = {
        current,
        windows: windows.items ?? [],
        decisions: decisions.items ?? [],
        alerts: alerts.items ?? [],
        tasks: tasks.items ?? [],
        system,
        summary24h,
        timeline: timeline.items ?? [],
        spatialSummary,
        questionnaireTemplates: questionnaireTemplates.items ?? [],
        questionnaireSchedules: questionnaireSchedules.items ?? [],
        questionnaireResults: questionnaireResults.items ?? [],
        reportData,
        modelMetrics,
        dayProfile,
        weeklyReports: weeklyReports.items ?? weeklyReports.reports ?? [],
        morningBrief,
        operationalMetrics,
        _offline: false,
        _cachedAt: new Date().toISOString(),
      };
      savePatientDataCache(patientId, nextData);
      setState({
        loading: false,
        error: "",
        data: nextData,
      });
    } catch (error) {
      const cached = loadPatientDataCache(patientId);
      if (background) {
        setState((previous) => ({
          ...previous,
          loading: false,
          data: previous.data
            ? { ...previous.data, _offline: true, _offlineReason: readableApiError(error) }
            : previous.data,
        }));
      } else if (cached?.data) {
        setState({
          loading: false,
          error: "",
          data: {
            ...cached.data,
            _offline: true,
            _cachedAt: cached.cachedAt,
            _offlineReason: readableApiError(error),
          },
        });
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
            "alert_deleted",
            "task_created",
            "task_completed",
            "task_cancelled",
            "task_deleted",
            "task_updated",
            "questionnaire_completed",
            "questionnaire_schedule_updated",
            "caregiver_message_created",
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
        !normalizedSearch || patientDisplayName(patient).toLocaleLowerCase("it").includes(normalizedSearch)
      ));
      return sortPatients(filtered, patientSort);
    },
    [patients, patientFilter, patientSearch, patientSort, profileVersion]
  );

  const activeView = tabs.find((tab) => tab.id === activeTab) ?? tabs[0];
  const activeAlertCount = state.data?.alerts?.filter((alert) => alert.status !== "resolved").length ?? 0;
  const activeTaskCount = state.data?.tasks?.filter((task) => !["completed", "cancelled", "expired"].includes(task.status)).length ?? 0;
  const userLabel = session?.user?.display_name ?? session?.user?.email ?? "Medico";
  const selectedPatientName = patientDisplayName(selectedPatient, selectedPatientId);

  function selectPatient(patientId) {
    setSelectedPatientId(patientId);
    setActiveTab("patient");
    setSidebarOpen(false);
  }

  function returnToPatientDirectory() {
    setSelectedPatientId(null);
    setActiveTab("patient");
    setEvents([]);
    setWsStatus("idle");
    setState({ loading: false, error: "", data: null });
    setSidebarOpen(false);
  }

  function selectTab(tabId) {
    setActiveTab(tabId);
    setSidebarOpen(false);
  }

  function clearCurrentPatientView() {
    setState((previous) => {
      if (!previous.data) return previous;
      return {
        ...previous,
        data: {
          ...previous.data,
          windows: [],
          decisions: [],
          alerts: [],
          tasks: [],
          timeline: [],
          questionnaireResults: [],
          questionnaireSchedules: [],
          reportData: null,
          modelMetrics: null,
          dayProfile: null,
          weeklyReports: [],
          morningBrief: null,
          operationalMetrics: null,
        },
      };
    });
    removePatientDataCache(selectedPatientId);
    setEvents([]);
  }

  async function confirmClearAllDashboardData() {
    const email = session?.user?.email;
    if (!email || !clearAllPassword.trim()) {
      setClearAllError("Inserisci la password del profilo medico.");
      return;
    }
    setClearAllBusy(true);
    setClearAllError("");
    try {
      await api.login({ email, password: clearAllPassword });
      clearCurrentPatientView();
      localStorage.removeItem(PATIENT_PROFILE_STORAGE_KEY);
      localStorage.removeItem(PATIENT_DATA_CACHE_KEY);
      setClearAllPassword("");
      setClearAllOpen(false);
    } catch (error) {
      setClearAllError("Password non valida oppure backend non raggiungibile.");
    } finally {
      setClearAllBusy(false);
    }
  }

  if (!selectedPatientId) {
    return (
      <PatientDirectory
        patients={patients}
        visiblePatients={visiblePatients}
        loading={patientListState.loading}
        error={patientListState.error}
        userLabel={userLabel}
        patientSearch={patientSearch}
        patientSort={patientSort}
        patientFilter={patientFilter}
        onSearchChange={setPatientSearch}
        onSortChange={setPatientSort}
        onFilterChange={setPatientFilter}
        onSelectPatient={selectPatient}
        onRefresh={() => loadPatients({ background: true })}
        onLogout={onLogout}
      />
    );
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
          <div className="section-title">Paziente selezionato</div>
          <div className={`sidebar-selected-patient ${isStale(selectedPatient?.last_update) ? "stale" : ""}`}>
            <span className={`patient-avatar ${selectedPatient?.level ?? "green"}`}>{patientInitials(selectedPatientName)}</span>
            <span className="patient-button-copy">
              <strong>{selectedPatientName}</strong>
              <small className="patient-meta-line">
                <Home size={13} />
                {roomLabel(selectedPatient?.current_room)}
              </small>
              <small className="patient-meta-line">
                <span className={`signal-chip ${signalKind(selectedPatient)}`}>{signalLabel(selectedPatient)}</span>
                {isStale(selectedPatient?.last_update) && <span className="stale-chip">obsoleto</span>}
              </small>
            </span>
          </div>
          <button className="change-patient-button" type="button" onClick={returnToPatientDirectory}>
            <ArrowLeft size={17} />
            Cambia paziente
          </button>
        </section>

        <div className="sidebar-user">
          <span className="user-avatar"><UserRound size={18} /></span>
          <span><strong>{userLabel}</strong></span>
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
              <div className="breadcrumb"><span>{selectedPatientName}</span><ChevronRight size={14} /><strong>{activeView.shortLabel}</strong></div>
              <h2>{activeView.label}</h2>
            </div>
          </div>
          <div className="topbar-actions">
            <StatusPill status={wsStatus} />
            <button className="patient-profile-button" type="button" onClick={() => setPatientIdentityOpen(true)}>
              <UserRound size={17} />
              Anagrafica
            </button>
            <button className="icon-button" type="button" onClick={() => setClearAllOpen(true)} title="Pulisci dati app" aria-label="Pulisci dati app">
              <DatabaseZap size={18} />
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
            {state.data._offline && (
              <div className="offline-banner" role="status">
                <Info size={18} />
                <div>
                  <strong>Dati non aggiornati</strong>
                  <span>
                    Consultazione da cache locale del {formatDateTime(state.data._cachedAt)}.
                    Le azioni operative sono sospese finche' il backend torna raggiungibile.
                  </span>
                </div>
              </div>
            )}
            <div className="view-stage" key={`${activeTab}-${selectedPatientId}`}>
              {activeTab === "patient" && (
                <PatientView
                  data={state.data}
                  patient={selectedPatient}
                  session={session}
                  patientId={selectedPatientId}
                  onChanged={() => loadPatientData(selectedPatientId, { background: true })}
                  onClearPatientData={clearCurrentPatientView}
                />
              )}
              {activeTab === "timeline" && <TimelineView data={state.data} />}
              {activeTab === "evaluations" && <EvaluationsView data={state.data} session={session} patientId={selectedPatientId} onChanged={() => loadPatientData(selectedPatientId, { background: true })} />}
              {activeTab === "day-profile" && <DayProfileView data={state.data} patient={selectedPatient} />}
              {activeTab === "routine" && <RoutineView data={state.data} session={session} patientId={selectedPatientId} />}
              {activeTab === "alerts" && (
                <AlertsView
                  data={state.data}
                  session={session}
                  patientId={selectedPatientId}
                  onChanged={() => loadPatientData(selectedPatientId, { background: true })}
                  onTaskCreated={async () => {
                    await loadPatientData(selectedPatientId, { background: true });
                    setActiveTab("tasks");
                  }}
                />
              )}
              {activeTab === "tasks" && <TasksView data={state.data} session={session} patientId={selectedPatientId} onChanged={() => loadPatientData(selectedPatientId, { background: true })} />}
              {activeTab === "system" && <SystemView data={state.data} events={events} wsStatus={wsStatus} session={session} />}
              {activeTab === "report" && <ReportView data={state.data} patient={selectedPatient} />}
            </div>
          </div>
        )}
      </section>
      <PatientIdentityDialog
        open={patientIdentityOpen}
        onClose={() => setPatientIdentityOpen(false)}
        patient={selectedPatient}
        current={state.data?.current}
        onSaved={() => setProfileVersion((version) => version + 1)}
      />
      <ActionDialog
        open={clearAllOpen}
        icon={<DatabaseZap size={22} />}
        title="Pulire i dati visualizzati?"
        description="La pulizia riguarda la vista locale della dashboard: il database clinico non viene cancellato."
        confirmLabel="Pulisci dashboard"
        busy={clearAllBusy}
        onClose={() => {
          if (clearAllBusy) return;
          setClearAllOpen(false);
          setClearAllPassword("");
          setClearAllError("");
        }}
        onConfirm={confirmClearAllDashboardData}
      >
        <label className="dialog-field">
          Password medico
          <input
            value={clearAllPassword}
            onChange={(event) => setClearAllPassword(event.target.value)}
            type="password"
            autoComplete="current-password"
            placeholder="Conferma con la password del profilo"
          />
          <small>Serve solo per confermare l'operazione locale.</small>
        </label>
        {clearAllError && <p className="inline-feedback error"><AlertTriangle size={16} />{clearAllError}</p>}
      </ActionDialog>
    </main>
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

function PatientDirectory({
  patients,
  visiblePatients,
  loading,
  error,
  userLabel,
  patientSearch,
  patientSort,
  patientFilter,
  onSearchChange,
  onSortChange,
  onFilterChange,
  onSelectPatient,
  onRefresh,
  onLogout,
}) {
  const counts = patients.reduce(
    (accumulator, patient) => {
      accumulator.total += 1;
      if (["red", "orange"].includes(patient.level)) accumulator.priority += 1;
      if (signalKind(patient) === "technical") accumulator.technical += 1;
      if (isStale(patient.last_update)) accumulator.stale += 1;
      return accumulator;
    },
    { total: 0, priority: 0, technical: 0, stale: 0 }
  );

  return (
    <main className="patient-directory-shell">
      <header className="directory-topbar">
        <div className="directory-brand">
          <AppLogoMark />
          <div>
            <p className="eyebrow">Console clinica</p>
            <h1>Triage IoT</h1>
          </div>
        </div>
        <div className="directory-user">
          <span className="user-avatar"><UserRound size={18} /></span>
          <span><strong>{userLabel}</strong><small>Medico</small></span>
          <button className="icon-button" type="button" onClick={onRefresh} title="Aggiorna pazienti" aria-label="Aggiorna pazienti">
            <RefreshCcw className={loading ? "spin" : ""} size={18} />
          </button>
          <button className="secondary-button" type="button" onClick={onLogout}><LogOut size={17} /> Esci</button>
        </div>
      </header>

      <section className="patient-directory-hero">
        <div>
          <span className="directory-kicker"><Users size={17} /> Pazienti assegnati</span>
          <h2>Scegli il paziente da monitorare</h2>
          <p>Ordina per urgenza clinica o ultimo aggiornamento, poi entra nel profilo per quadro clinico, segnalazioni, attivita e stato sistema.</p>
        </div>
        <div className="directory-metrics" aria-label="Sintesi pazienti assegnati">
          <OverviewMetric icon={<Users size={17} />} label="Monitorati" value={counts.total} />
          <OverviewMetric icon={<AlertTriangle size={17} />} label="Prioritari" value={counts.priority} tone={counts.priority ? "orange" : "green"} />
          <OverviewMetric icon={<MonitorCog size={17} />} label="Tecnici" value={counts.technical} tone={counts.technical ? "technical" : "green"} />
          <OverviewMetric icon={<Clock3 size={17} />} label="Obsoleti" value={counts.stale} tone={counts.stale ? "yellow" : "green"} />
        </div>
      </section>

      <section className="patient-directory-panel">
        <div className="directory-toolbar">
          <label className="patient-search directory-search">
            <Search size={16} />
            <input
              value={patientSearch}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="Cerca per nome paziente"
              aria-label="Cerca paziente"
            />
            {patientSearch && (
              <button type="button" onClick={() => onSearchChange("")} aria-label="Cancella ricerca"><X size={15} /></button>
            )}
          </label>
          <PatientListControls
            sortMode={patientSort}
            filterMode={patientFilter}
            onSortChange={onSortChange}
            onFilterChange={onFilterChange}
          />
        </div>

        {loading && patients.length === 0 && <LoadingState />}
        {!loading && error && patients.length === 0 && <ErrorState message={error} onRetry={onRefresh} />}
        {!loading && !error && patients.length === 0 && (
          <div className="state-card empty-state"><span className="state-icon"><Info size={22} /></span><div><strong>Nessun paziente assegnato</strong><p>Quando il backend associa i pazienti al medico, compariranno in questa pagina.</p></div></div>
        )}
        {error && patients.length > 0 && (
          <div className="directory-inline-warning"><AlertTriangle size={16} /> Lista non aggiornata: {error}</div>
        )}
        {!loading && patients.length > 0 && visiblePatients.length === 0 && (
          <div className="state-card empty-state"><span className="state-icon"><Search size={22} /></span><div><strong>Nessun risultato</strong><p>Prova a cambiare ricerca o filtro.</p></div></div>
        )}
        {visiblePatients.length > 0 && (
          <div className="directory-patient-grid">
            {visiblePatients.map((patient) => {
              const displayName = patientDisplayName(patient);
              return (
                <button
                  key={patient.patient_id}
                  className={`directory-patient-card ${patient.level ?? "green"} ${isStale(patient.last_update) ? "stale" : ""}`}
                  type="button"
                  onClick={() => onSelectPatient(patient.patient_id)}
                >
                  <span className={`patient-avatar ${patient.level ?? "green"}`}>{patientInitials(displayName)}</span>
                  <span className="directory-card-main">
                    <span className="directory-card-header">
                      <strong>{displayName}</strong>
                      <span className={`signal-chip ${signalKind(patient)}`}>{signalLabel(patient)}</span>
                    </span>
                    <span className="directory-card-details">
                      <span><MapPin size={14} /> {roomLabel(patient.current_room)}</span>
                      <span><Watch size={14} /> {patient.watch_present ? "wearable presente" : "wearable n/d"}</span>
                      <span><Server size={14} /> {patient.edge_online ? "Raspberry online" : "Raspberry offline"}</span>
                    </span>
                    <span className="directory-card-footer">
                      <span>Score {scoreText(patient.anomaly_score)}</span>
                      <span>Update {formatDateTime(patient.last_update)}</span>
                      {isStale(patient.last_update) && <span className="stale-chip">obsoleto</span>}
                    </span>
                  </span>
                  <ChevronRight className="patient-chevron" size={18} />
                </button>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
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
  const selectedName = patientDisplayName(selected);

  return (
    <section className="overview-strip" aria-label="Overview pazienti">
      <OverviewMetric icon={<Users size={17} />} label="Monitorati" value={counts.total} />
      <OverviewMetric icon={<AlertTriangle size={17} />} label="Alta priorita" value={counts.red + counts.orange} tone={counts.red ? "red" : "orange"} />
      <OverviewMetric icon={<MonitorCog size={17} />} label="Tecnici" value={counts.technicalSignals} tone="technical" />
      <OverviewMetric icon={<Clock3 size={17} />} label="Obsoleti" value={counts.stale} tone={counts.stale ? "yellow" : "green"} />
      <div className="selected-summary">
        <span className={`selected-patient-avatar ${selected?.level ?? "green"}`}>{patientInitials(selectedName)}</span>
        <div>
          <strong>{selected ? selectedName : "Nessun paziente selezionato"}</strong>
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
  const indicatorLabel = active ? (sort.direction === "asc" ? "ordine crescente" : "ordine decrescente") : "ordinabile";
  return (
    <th>
      <button
        className={`table-sort-button ${active ? "active" : ""}`}
        type="button"
        onClick={() => onSort(sortKey)}
        title={`Ordina per ${label}`}
      >
        <span>{label}</span>
        <span aria-label={indicatorLabel}>{indicator}</span>
      </button>
    </th>
  );
}

function PrettySelect({ label, value, options, onChange }) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef(null);
  const selected = options.find((option) => option.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return undefined;
    const closeOnOutsideClick = (event) => {
      if (!wrapperRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  return (
    <label className="pretty-select-field" ref={wrapperRef}>
      {label}
      <button
        className={`pretty-select-button ${open ? "open" : ""}`}
        type="button"
        onClick={() => setOpen((previous) => !previous)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span>{selected?.label ?? "Seleziona"}</span>
        <ChevronDown size={17} />
      </button>
      {open && (
        <div className="pretty-select-menu" role="listbox">
          {options.map((option) => (
            <button
              key={option.value}
              className={option.value === value ? "active" : ""}
              type="button"
              role="option"
              aria-selected={option.value === value}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
    </label>
  );
}

function PatientView({ data, patient, session, patientId, onChanged }) {
  const { current, windows, decisions } = data;
  const stale = isStale(current.last_update);
  const latestDecision = decisions.at(-1);
  const [rangeMode, setRangeMode] = useState("day");
  const [recentWindowsHidden, setRecentWindowsHidden] = useState(false);
  const [chartsHidden, setChartsHidden] = useState(false);
  const [windowFiltersOpen, setWindowFiltersOpen] = useState(false);
  const [expandedChart, setExpandedChart] = useState(null);
  const [aiActionMessage, setAiActionMessage] = useState("");
  const [aiActionError, setAiActionError] = useState("");
  const [recentSort, setRecentSort] = useState({ key: "window_end", direction: "desc" });
  const [windowInterval, setWindowInterval] = useState({ date: "", from: "", to: "" });
  const decisionTrendWindows = useMemo(() => decisionScoreWindows(decisions), [decisions]);
  const visibleWindows = useMemo(() => {
    const ranged = filterWindowsByRange(windows, rangeMode);
    return filterWindowsByCustomInterval(ranged, windowInterval);
  }, [windows, rangeMode, windowInterval]);
  const chartWindows = visibleWindows.length > 0 ? visibleWindows : windows;
  const recentRows = useMemo(
    () => sortRecentWindows(visibleWindows.length || hasWindowInterval(windowInterval) ? visibleWindows : windows, recentSort),
    [windows, visibleWindows, recentSort, windowInterval]
  );

  function changeRecentSort(key) {
    setRecentWindowsHidden(false);
    setRecentSort((previous) => ({
      key,
      direction: previous.key === key && previous.direction === "desc" ? "asc" : "desc",
    }));
  }

  async function approveRetraining() {
    setAiActionMessage("");
    setAiActionError("");
    try {
      await api.approveModelRetraining(patientId, session);
      setAiActionMessage("Aggiornamento modello approvato. Attendo conferma dal backend.");
      onChanged?.();
    } catch (apiError) {
      setAiActionError(readableApiError(apiError));
    }
  }

  return (
    <div className="content-grid">
      <PatientClinicalHero current={current} patient={patient} stale={stale} system={data.system} />

      <section className="panel span-2">
        <Summary24hPanel summary={data.summary24h} current={current} windows={windows} />
      </section>

      <section className="panel span-2">
        <MorningBriefPanel brief={data.morningBrief} windows={windows} decisions={decisions} />
      </section>

      <section className="panel span-2">
        <AiExplanationPanel
          decision={latestDecision}
          system={data.system}
          current={current}
          decisions={decisions}
          modelMetrics={data.modelMetrics}
          onApproveRetraining={approveRetraining}
        />
        {aiActionMessage && <p className="inline-feedback success"><CheckCircle2 size={16} />{aiActionMessage}</p>}
        {aiActionError && <p className="inline-feedback error"><AlertTriangle size={16} />{aiActionError}</p>}
      </section>

      <section className="panel span-2">
        <DecisionScoreTrendPanel
          decisions={decisions}
          windows={decisionTrendWindows}
          onExpandChart={setExpandedChart}
        />
      </section>

      <section className="panel span-2">
        <div className="panel-heading">
          <div>
            <h3>Dati wearable e spaziali</h3>
            <p className="panel-subtitle">Finestra visualizzata: {rangeLabel(rangeMode)}. I valori mancanti restano non acquisiti.</p>
          </div>
          <div className={`segmented-control range-control ${rangeMode}`} aria-label="Intervallo dati">
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
          <button
            className="icon-button"
            type="button"
            onClick={() => setChartsHidden((previous) => !previous)}
            title={chartsHidden ? "Mostra grafici" : "Nascondi grafici"}
            aria-label={chartsHidden ? "Mostra grafici" : "Nascondi grafici"}
          >
            {chartsHidden ? <Eye size={18} /> : <EyeOff size={18} />}
          </button>
        </div>
        {chartsHidden ? (
          <ViewEmptyState
            icon={<EyeOff size={24} />}
            title="Grafici nascosti"
            text="La vista dei grafici e' nascosta in questa sessione. I dati originali restano disponibili sul backend."
          />
        ) : (
          <WearableSpatialDashboard windows={chartWindows} current={current} onExpandChart={setExpandedChart} />
        )}
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
              className="icon-button"
              type="button"
              onClick={() => setRecentWindowsHidden((previous) => !previous)}
              title={recentWindowsHidden ? "Mostra tabella" : "Nascondi tabella"}
              aria-label={recentWindowsHidden ? "Mostra tabella" : "Nascondi tabella"}
            >
              {recentWindowsHidden ? <Eye size={18} /> : <EyeOff size={18} />}
            </button>
            <button
              className={`icon-button ${windowFiltersOpen || hasWindowInterval(windowInterval) ? "active" : ""}`}
              type="button"
              onClick={() => setWindowFiltersOpen((previous) => !previous)}
              title={windowFiltersOpen ? "Nascondi filtri" : "Mostra filtri"}
              aria-label={windowFiltersOpen ? "Nascondi filtri" : "Mostra filtri"}
            >
              <SlidersHorizontal size={18} />
            </button>
          </div>
        </div>
        {windowFiltersOpen && (
          <WindowIntervalFilters
            value={windowInterval}
            onChange={setWindowInterval}
            onClear={() => setWindowInterval({ date: "", from: "", to: "" })}
          />
        )}
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
      <ChartDialog chart={expandedChart} windows={chartWindows} onClose={() => setExpandedChart(null)} />
    </div>
  );
}

function Summary24hPanel({ summary, current, windows = [] }) {
  if (!summary) {
    return (
      <div>
        <div className="panel-heading">
          <div className="section-heading-group">
            <span className="section-heading-icon soft"><Clock3 size={19} /></span>
            <div>
              <h3>Riepilogo ultime 24 ore</h3>
              <p className="panel-subtitle">Il backend non ha ancora inviato l'aggregazione dedicata.</p>
            </div>
          </div>
        </div>
        <ViewEmptyState icon={<Info size={24} />} title="Riepilogo in attesa" text="La dashboard continua a usare finestre, decisioni e stato corrente gia' disponibili." />
      </div>
    );
  }

  const ai = summary.ai ?? {};
  const spatial = summary.spatial ?? {};
  const wearable = summary.wearable ?? {};
  const baseline = summary.baseline ?? {};
  const roomMinutes = spatial.room_minutes ?? {};
  const heartRate = wearable.heart_rate?.average ?? wearable.heart_rate_mean ?? latestFeatureValue(windows, "heart_rate_mean");
  const spo2 = wearable.spo2?.average ?? wearable.spo2_mean ?? latestFeatureValue(windows, "spo2_mean");
  const baselineText = baseline.baseline_available === false
    ? "Baseline personale non ancora pronta"
    : baseline.summary ?? baseline.message ?? "Confronto baseline disponibile";

  return (
    <div className="summary24">
      <div className="panel-heading">
        <div className="section-heading-group">
          <span className="section-heading-icon soft"><Clock3 size={19} /></span>
          <div>
            <h3>Riepilogo ultime 24 ore</h3>
            <p className="panel-subtitle">Sintesi automatica per orientare la revisione, non una diagnosi.</p>
          </div>
        </div>
      </div>
      <div className="summary24-grid">
        <Metric icon={<Gauge size={18} />} label="Indice medio" value={scoreBandText(ai.mean_score ?? ai.average_score)} tone={aiScoreBand(ai.mean_score ?? ai.average_score).key} />
        <Metric icon={<AlertTriangle size={18} />} label="Picco massimo" value={scoreBandText(ai.max_score)} tone={aiScoreBand(ai.max_score).key} />
        <Metric icon={<MapPin size={18} />} label="Stanza prevalente" value={roomLabel(spatial.prevalent_room ?? current?.current_room)} />
        <Metric icon={<ArrowDownUp size={18} />} label="Cambi stanza" value={formatNumber(spatial.room_changes ?? spatial.transitions_count)} />
        {!isMissingValue(heartRate) && <Metric icon={<HeartPulse size={18} />} label="Battito medio" value={formatFeatureValue(heartRate, "bpm")} />}
        {!isMissingValue(spo2) && <Metric icon={<Watch size={18} />} label="SpO2" value={formatFeatureValue(spo2, "%")} />}
      </div>
      <div className="summary24-bottom">
        <div className="room-share-list">
          {Object.entries(roomMinutes).length > 0 ? Object.entries(roomMinutes).map(([room, minutes]) => (
            <div key={room} className="room-share-row">
              <span>{roomLabel(room)}</span>
              <div className="room-share-track"><span style={{ width: `${roomShare(minutes, roomMinutes)}%` }} /></div>
              <strong>{formatFeatureValue(minutes, "min")}</strong>
            </div>
          )) : <p className="empty-text">Permanenze stanza non disponibili nelle ultime 24 ore.</p>}
        </div>
        <div className="summary24-note">
          <strong>Confronto personale</strong>
          <p>{baselineText}</p>
          <small>{summary.range?.start ? `${formatDateTime(summary.range.start)} - ${formatDateTime(summary.range.end)}` : "Intervallo non indicato"}</small>
        </div>
      </div>
    </div>
  );
}

function MorningBriefPanel({ brief, windows, decisions }) {
  const fallback = morningBriefFallback(windows, decisions);
  const payload = brief ?? fallback;
  const metrics = [
    { label: "Sonno stimato", value: formatFeatureValue(payload.sleep_minutes, "min"), icon: <Clock3 size={18} /> },
    { label: "Movimenti notturni", value: formatNumber(payload.night_room_changes), icon: <Home size={18} /> },
    { label: "HR notturno", value: formatFeatureValue(payload.night_heart_rate_mean ?? payload.heart_rate_mean, "bpm"), icon: <HeartPulse size={18} /> },
    { label: "Indice notte", value: scoreBandText(payload.ai_score ?? payload.max_score), icon: <BrainCircuit size={18} /> },
  ];

  return (
    <div className="morning-brief">
      <div className="panel-heading">
        <div className="section-heading-group">
          <span className="section-heading-icon soft"><CalendarClock size={19} /></span>
          <div>
            <h3>Brief del mattino</h3>
            <p className="panel-subtitle">{payload.summary ?? fallback.summary}</p>
          </div>
        </div>
      </div>
      <div className="summary24-grid compact-summary-grid">
        {metrics.map((item) => (
          <Metric key={item.label} icon={item.icon} label={item.label} value={item.value} />
        ))}
      </div>
      <p className="system-safe-note">
        Lettura notturna prudente: utile per orientare il controllo del mattino, non sostituisce valutazioni cliniche.
      </p>
    </div>
  );
}

function DayProfileView({ data, patient }) {
  const [metricKey, setMetricKey] = useState("ai");
  const metric = dayProfileMetricOptions.find((item) => item.key === metricKey) ?? dayProfileMetricOptions[0];
  const profile = useMemo(() => buildDayProfileData(data, metric), [data, metric]);
  const insight = dayProfileInsight(profile, metric);
  const displayName = patientDisplayName(patient, data.current?.patient_id);

  return (
    <section className="panel page-panel day-profile-page">
      <div className="view-heading">
        <div className="view-heading-copy">
          <span className="view-heading-icon soft"><Activity size={22} /></span>
          <div>
            <h3>Giornata tipo</h3>
            <p>Confronto tra oggi, ieri e routine media del paziente.</p>
          </div>
        </div>
        <div className="view-heading-stats">
          <span><strong>{displayName}</strong></span>
          <span>{profile.baselineAvailable ? "baseline disponibile" : "baseline in preparazione"}</span>
        </div>
      </div>

      <div className="day-profile-toolbar">
        {dayProfileMetricOptions.map((option) => (
          <button
            key={option.key}
            className={metricKey === option.key ? "active" : ""}
            type="button"
            onClick={() => setMetricKey(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="day-profile-layout">
        <DayProfileOverlayChart profile={profile} metric={metric} />
        <aside className="day-profile-aside">
          <strong>Interpretazione prudente</strong>
          <p>{insight}</p>
          <dl className="mini-detail-list">
            <Detail label="Metrica" value={metric.label} />
            <Detail label="Fasce" value={profile.bands.join(", ")} />
            <Detail label="Origine" value={data.dayProfile ? "Endpoint day-profile" : "Finestre e decisioni gia' caricate"} />
          </dl>
        </aside>
      </div>
    </section>
  );
}

function DayProfileOverlayChart({ profile, metric }) {
  const width = 920;
  const height = 330;
  const padding = { top: 28, right: 28, bottom: 54, left: 62 };
  const series = profile.series.filter((item) => item.points.some((point) => Number.isFinite(point.value)));
  const allValues = series.flatMap((item) => item.points.map((point) => point.value).filter(Number.isFinite));

  if (allValues.length === 0) {
    return (
      <ViewEmptyState
        icon={<Activity size={24} />}
        title="Dati non ancora disponibili"
        text="Quando arrivano finestre sufficienti, qui comparira il confronto con la giornata tipo."
      />
    );
  }

  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const spread = max - min || 1;
  const xStep = profile.bands.length > 1 ? (width - padding.left - padding.right) / (profile.bands.length - 1) : 0;
  const yForValue = (value) => height - padding.bottom - ((value - min) / spread) * (height - padding.top - padding.bottom);
  const yTicks = [
    { value: max, label: formatFeatureValue(max, metric.unit) },
    { value: (min + max) / 2, label: formatFeatureValue((min + max) / 2, metric.unit) },
    { value: min, label: formatFeatureValue(min, metric.unit) },
  ];

  return (
    <div className="day-profile-chart-card">
      <div className="day-profile-legend">
        {series.map((item) => (
          <span key={item.key}><i style={{ background: item.color }} />{item.label}</span>
        ))}
      </div>
      <svg className="day-profile-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Giornata tipo ${metric.label}`}>
        {yTicks.map((tick) => {
          const y = yForValue(tick.value);
          return (
            <g key={`${tick.label}-${y}`}>
              <line x1={padding.left} y1={y} x2={width - padding.right} y2={y} className="chart-grid-line" />
              <text x={padding.left - 8} y={y + 4} className="chart-tick-label" textAnchor="end">{tick.label}</text>
            </g>
          );
        })}
        <line x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} className="chart-axis" />
        <line x1={padding.left} y1={padding.top} x2={padding.left} y2={height - padding.bottom} className="chart-axis" />
        {profile.bands.map((band, index) => {
          const x = padding.left + index * xStep;
          return (
            <g key={band}>
              <line x1={x} y1={height - padding.bottom} x2={x} y2={height - padding.bottom + 6} className="chart-axis" />
              <text x={x} y={height - 22} className="chart-tick-label" textAnchor="middle">{band}</text>
            </g>
          );
        })}
        {series.map((item) => {
          const points = item.points
            .map((point, index) => Number.isFinite(point.value)
              ? `${padding.left + index * xStep},${yForValue(point.value)}`
              : null)
            .filter(Boolean)
            .join(" ");
          return (
            <g key={item.key}>
              <polyline
                points={points}
                fill="none"
                stroke={item.color}
                strokeWidth={item.key === "baseline" ? 2.6 : 3.4}
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray={item.key === "baseline" ? "8 7" : undefined}
              />
              {item.points.map((point, index) => Number.isFinite(point.value) && (
                <circle
                  key={`${item.key}-${profile.bands[index]}`}
                  cx={padding.left + index * xStep}
                  cy={yForValue(point.value)}
                  r={4.2}
                  fill={item.color}
                />
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function PatientClinicalHero({ current, patient, stale, system }) {
  const band = aiScoreBand(current.anomaly_score);
  const level = current.level ?? band.key ?? "green";
  const wearablePresent = current.watch?.present ?? current.wearable_present ?? current.watch_present ?? system?.sensors?.watch?.present;
  const edgeOnline = current.edge?.online ?? current.edge_online ?? system?.edge?.online;
  const displayName = patientDisplayName(patient, current.patient_id);

  return (
    <section className={`panel span-2 patient-clinical-hero ${level}`}>
      <div className="patient-clinical-main">
        <div className="patient-clinical-title">
          <span className={`selected-patient-avatar ${level}`}>{patientInitials(displayName)}</span>
          <div>
            <span className="clinical-kicker">Profilo paziente</span>
            <h3>{displayName}</h3>
            <p>Quadro consolidato dell'ultima finestra Edge disponibile.</p>
          </div>
        </div>
        <div className="patient-clinical-score">
          <strong>{scoreBandText(current.anomaly_score)}</strong>
          <small>Indice AI</small>
        </div>
      </div>

      <div className="patient-clinical-grid" aria-label="Sintesi stato paziente">
        <Metric icon={<Gauge size={18} />} label="Priorita" value={band.label} tone={band.key} />
        <Metric icon={<MapPin size={18} />} label="Stanza" value={roomLabel(current.current_room)} />
        <Metric icon={<Clock3 size={18} />} label="Ultimo aggiornamento" value={formatDateTime(current.last_update)} tone={stale ? "yellow" : "green"} />
        <Metric icon={<Watch size={18} />} label="Wearable" value={wearablePresent === false ? "Non rilevato" : wearablePresent === true ? "Presente" : "Non disponibile"} tone={wearablePresent === false ? "technical" : "green"} />
        <Metric icon={<Server size={18} />} label="Raspberry" value={edgeOnline === false ? "Offline" : edgeOnline === true ? "Online" : "Non disponibile"} tone={edgeOnline === false ? "technical" : "green"} />
      </div>

      {stale && (
        <div className="patient-clinical-warning">
          <AlertTriangle size={17} />
          <span>Dati obsoleti: verificare l'ultimo ciclo Edge prima di prendere decisioni operative.</span>
        </div>
      )}
    </section>
  );
}

function PatientIdentityDialog({ open, onClose, patient, current, onSaved }) {
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
    onSaved?.();
  }

  if (!open) return null;

  return (
    <div className="patient-identity-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="patient-identity-dialog" role="dialog" aria-modal="true" aria-labelledby="patient-identity-title">
        <div className="patient-identity-dialog-header">
          <span className="patient-identity-icon"><UserRound size={21} /></span>
          <div>
            <span className="clinical-kicker">Dati identificativi</span>
            <h3 id="patient-identity-title">{displayName}</h3>
            <p>ID clinico: {patientId}</p>
          </div>
          <button className="dialog-close" type="button" onClick={onClose} aria-label="Chiudi">
            <X size={19} />
          </button>
        </div>

        <div className="patient-identity-dialog-body">
          <div className="patient-identity-dialog-summary">
            <span>Completamento scheda</span>
            <strong>{filledCount}/10</strong>
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
          <span>{filledCount}/10</span>
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

function WindowIntervalFilters({ value, onChange, onClear }) {
  const hasFilter = hasWindowInterval(value);
  function update(field, nextValue) {
    onChange({ ...value, [field]: nextValue });
  }
  return (
    <div className="window-interval-filter" aria-label="Filtro intervallo finestre">
      <label>
        Giorno
        <input type="date" value={value.date} onChange={(event) => update("date", event.target.value)} />
      </label>
      <label>
        Da
        <input type="time" value={value.from} onChange={(event) => update("from", event.target.value)} />
      </label>
      <label>
        A
        <input type="time" value={value.to} onChange={(event) => update("to", event.target.value)} />
      </label>
      <button className="clear-filter-button" type="button" onClick={onClear} disabled={!hasFilter}>
        <X size={16} />
        Azzera
      </button>
    </div>
  );
}

function AiExplanationPanel({ decision, system, current, decisions = [], modelMetrics, onApproveRetraining }) {
  const fusion = fusionFromDecision(decision);
  const models = modelSummaries(fusion);
  const baseline = baselineFromSystem(system);
  const finalScore = decision?.anomaly_score ?? current?.anomaly_score;
  const finalLevel = decision?.level ?? current?.level;
  const personalModel = fusion?.models?.personal;
  const personalAvailable = personalModel?.available === true || system?.ai?.personal_model_available === true;
  const activeModels = models.filter((model) => model.available).length;
  const normalizedExplanation = decision?.ai_explanation ?? current?.ai_explanation ?? null;

  if (!decision) {
    return (
      <div>
        <div className="panel-heading">
          <h3>Valutazione comportamentale</h3>
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
      </section>

      <AdvancedAiExplanation explanation={normalizedExplanation} finalScore={finalScore} />

      <ModelReliabilityPanel metrics={modelMetrics ?? decision?.model_metrics ?? system?.ai?.model_metrics} />

      <TrendDriftPanel
        decision={decision}
        decisions={decisions}
        system={system}
        onApproveRetraining={onApproveRetraining}
      />

      <section className="ai-section-block">
        <div className="ai-section-heading">
          <div>
            <h4>Contributo delle fonti</h4>
            <p>Ogni indice misura quanto i dati si discostano dal proprio riferimento.</p>
          </div>
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

      <details className="ai-section-block factors-section factors-disclosure">
        <summary className="ai-section-heading">
          <div>
            <h4>Fattori che hanno inciso maggiormente</h4>
            <p>Indicatori ordinati per distanza dal riferimento utilizzato dal sistema.</p>
          </div>
          <ChevronDown size={18} />
        </summary>
        <ClinicalFactors models={models} />
      </details>

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

function ConfidenceMiniBadge({ confidence }) {
  const score = Number(confidence?.score);
  const level = reliabilityLabel(confidence?.level ?? confidenceLevelFromScore(score));
  return (
    <span className={`confidence-mini-badge reliability-${level}`}>
      <ShieldCheck size={15} />
      Affidabilita {level}
      {Number.isFinite(score) ? ` ${Math.round(score)}%` : ""}
    </span>
  );
}

function AiScoreBandLegend({ score }) {
  const current = aiScoreBand(score);
  const bands = [
    { key: "normal", label: "Routine", range: "0-40" },
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

function AdvancedAiExplanation({ explanation, finalScore }) {
  if (!explanation) {
    return (
      <section className="ai-section-block ai-advanced-empty">
        <div className="ai-section-heading">
          <div>
            <h4>Lettura avanzata</h4>
            <p>Il backend non ha ancora inviato la spiegazione normalizzata.</p>
          </div>
        </div>
      </section>
    );
  }

  const positive = explanation.positive_factors ?? [];
  const negative = explanation.negative_factors ?? [];
  const missing = explanation.missing_or_imputed_features ?? [];
  const contributions = explanation.model_contributions ?? [];
  const delta = Number(explanation.score_delta);
  const deltaLabel = Number.isFinite(delta)
    ? `${delta > 0 ? "+" : ""}${delta.toFixed(1)} rispetto alla valutazione precedente`
    : "Confronto precedente non disponibile";

  return (
    <section className="ai-section-block ai-advanced">
      <div className="ai-section-heading">
        <div>
          <h4>Perche l'indice e' cambiato</h4>
          <p>{explanation.message ?? "Lettura normalizzata dei fattori principali."}</p>
        </div>
        <span className={`badge reliability-${String(explanation.data_reliability ?? "media").toLowerCase()}`}>
          Affidabilita {reliabilityLabel(explanation.data_reliability)}
        </span>
      </div>
      <div className="ai-advanced-grid">
        <div className="ai-delta-card">
          <span>Confronto precedente</span>
          <strong>{deltaLabel}</strong>
          <small>Indice attuale: {scoreBandText(finalScore)}</small>
        </div>
        <FactorColumn title="Elementi che aumentano l'indice" items={positive} tone="risk" />
        <FactorColumn title="Elementi che riducono l'indice" items={negative} tone="protective" />
        <FactorColumn title="Dati mancanti o stimati" items={missing} tone="missing" />
      </div>
      {contributions.length > 0 && (
        <div className="ai-contribution-strip">
          {contributions.map((item) => (
            <span key={item.model ?? item.label}>
              <strong>{modelContributionLabel(item.model ?? item.label)}</strong>
              {formatNumber(item.score ?? item.value)} / 100
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function ConfidenceQualityPanel({ confidence, system }) {
  const score = Number(confidence?.score);
  const bounded = Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : null;
  const level = confidence?.level ?? confidenceLevelFromScore(bounded);
  const reasons = Array.isArray(confidence?.reasons) ? confidence.reasons : [];
  const sensors = system?.sensors ?? {};
  const missingHints = [
    sensors.watch?.present === false ? "wearable non rilevato" : "",
    ["missing", "stale"].includes(String(sensors.ble?.status)) ? "BLE non aggiornato" : "",
    ["missing", "stale"].includes(String(sensors.google_health?.status)) ? "Google Health non aggiornato" : "",
  ].filter(Boolean);

  return (
    <section className="ai-support-section confidence-panel">
      <div className="ai-section-heading compact-heading">
        <div>
          <h4>Affidabilita' del dato</h4>
          <p>Confidenza separata dallo score AI.</p>
        </div>
        <span className={`badge reliability-${reliabilityLabel(level)}`}>{reliabilityLabel(level)}</span>
      </div>
      <div className="confidence-meter" style={{ "--confidence": bounded ?? 0 }}>
        <strong>{bounded === null ? "n/d" : `${Math.round(bounded)}%`}</strong>
        <span><i /></span>
      </div>
      <ul className="compact-reason-list">
        {(reasons.length ? reasons : missingHints.length ? missingHints : ["confidenza non ancora calcolata dal backend"]).map((reason) => (
          <li key={reason}>{decisionReasonLabel(reason)}</li>
        ))}
      </ul>
    </section>
  );
}

function ModelReliabilityPanel({ metrics }) {
  const rows = normalizeModelMetrics(metrics);
  const f1Values = rows.map((row) => Number(row.f1)).filter(Number.isFinite);
  const meanF1 = f1Values.length ? f1Values.reduce((total, value) => total + value, 0) / f1Values.length : null;
  const normalizedF1 = meanF1 !== null && meanF1 <= 1 ? meanF1 * 100 : meanF1;
  const reliability = normalizedF1 === null ? null : normalizedF1 >= 80 ? "Alta" : normalizedF1 >= 60 ? "Media" : "Bassa";

  return (
    <section className="ai-support-section model-reliability-panel">
      <div className="ai-section-heading compact-heading">
        <div>
          <h4>Affidabilita' modello</h4>
          <p>Indicatore sintetico ricavato dalla validazione dei modelli attivi.</p>
        </div>
        <span className="badge">{reliability ?? "In attesa"}</span>
      </div>
      {rows.length === 0 ? (
        <div className="baseline-empty compact-empty">
          <BrainCircuit size={20} />
          <div>
            <strong>Metriche non ancora disponibili</strong>
            <p>L'affidabilita comparira quando il backend avra prodotto le metriche di validazione.</p>
          </div>
        </div>
      ) : (
        <div className="model-reliability-value">
          <ShieldCheck size={24} />
          <div>
            <strong>{Number.isFinite(normalizedF1) ? `${Math.round(normalizedF1)}%` : "n/d"}</strong>
            <span>Affidabilita complessiva {String(reliability).toLowerCase()}</span>
          </div>
        </div>
      )}
    </section>
  );
}

function TrendDriftPanel({ decision, decisions, system, onApproveRetraining }) {
  const trend = decision?.trend ?? system?.ai?.trend ?? trendFromDecisions(decisions);
  const drift = system?.ai?.drift ?? decision?.drift ?? decision?.payload?.drift ?? {};
  const direction = trend?.direction ?? trendDirectionFromSlope(trend?.score_slope_per_day ?? trend?.slope);
  const needsApproval = ["needs_review", "possible_drift"].includes(String(drift.status ?? "").toLowerCase()) || drift.requires_approval === true;

  return (
    <section className="ai-section-block trend-drift-panel">
      <div className="ai-section-heading">
        <div>
          <h4>Andamento nel tempo</h4>
          <p>{trendText(direction, trend)}</p>
        </div>
        <span className={`badge drift-${String(drift.status ?? "stable").toLowerCase()}`}>{driftStatusLabel(drift.status)}</span>
      </div>
      <div className="trend-drift-grid">
        <Metric icon={<ArrowDownUp size={18} />} label="Direzione indice" value={trendDirectionLabel(direction)} />
        <Metric icon={<Gauge size={18} />} label="Pendenza stimata" value={trend?.score_slope_per_day === undefined ? "n/d" : `${formatNumber(trend.score_slope_per_day)} punti/giorno`} />
        <Metric icon={<CalendarClock size={18} />} label="Finestra trend" value={trend?.window_days ? `${trend.window_days} giorni` : "storico disponibile"} />
        <Metric icon={<UserRoundCheck size={18} />} label="Drift modello" value={driftStatusLabel(drift.status)} />
      </div>
      {needsApproval && (
        <button className="secondary-button" type="button" onClick={onApproveRetraining}>
          <CheckCircle2 size={17} />
          Approva aggiornamento modello
        </button>
      )}
    </section>
  );
}

function FactorColumn({ title, items, tone }) {
  return (
    <div className={`factor-column ${tone}`}>
      <strong>{title}</strong>
      {items.length === 0 ? (
        <p>Nessun elemento rilevante indicato.</p>
      ) : (
        <ul>
          {items.slice(0, 5).map((item, index) => (
            <li key={`${title}-${index}`}>
              <span>{clinicalFactorSentence(item, tone)}</span>
              <small>{factorValueText(item)}</small>
            </li>
          ))}
        </ul>
      )}
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
      {!personalAvailable && <p className="empty-text">Il calcolo usa le fonti generali finche il profilo personale non e disponibile.</p>}
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

function WearableSpatialDashboard({ windows, current, onExpandChart }) {
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
            onExpand={onExpandChart}
          />
          <FeatureTrendCard
            title="Deviazione frequenza cardiaca"
            feature="heart_rate_std"
            unit="bpm"
            windows={windows}
            color="#c05621"
            onExpand={onExpandChart}
          />
          <FeatureTrendCard title="SpO2 media" feature="spo2_mean" unit="%" windows={windows} color="#17686c" onExpand={onExpandChart} />
          <FeatureTrendCard title="Passi" feature="steps" unit="" windows={windows} color="#4452ba" onExpand={onExpandChart} />
          <FeatureTrendCard title="Sonno" feature="sleep_minutes" unit="min" windows={windows} color="#6271d9" onExpand={onExpandChart} />
          <FeatureTrendCard title="Sedentarieta" feature="sedentary_minutes" unit="min" windows={windows} color="#744d00" onExpand={onExpandChart} missingAsZero />
        </div>
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

function DecisionScoreTrendPanel({ decisions, windows, onExpandChart }) {
  const latest = latestFeatureValue(windows, "anomaly_score");

  return (
    <div className="decision-trend-panel">
      <div className="panel-heading compact-heading">
        <div>
          <h3>Andamento indice AI</h3>
          <p className="panel-subtitle">
            Ultimo valore {scoreBandText(latest)} su {decisions.length} decisioni salvate.
          </p>
        </div>
      </div>
      {windows.length === 0 ? (
        <ViewEmptyState
          icon={<BrainCircuit size={24} />}
          title="Nessuno storico AI disponibile"
          text="Quando il Raspberry pubblica le decisioni, lo score viene salvato dal backend e comparira' qui come serie temporale."
        />
      ) : (
        <FeatureTrendCard
          title="Indice AI nel tempo"
          feature="anomaly_score"
          unit=""
          windows={windows}
          color="#c83532"
          onExpand={onExpandChart}
          large
        />
      )}
    </div>
  );
}

function FeatureTrendCard({ title, feature, unit, windows, color, onExpand, large = false, minimal = false, missingAsZero = false }) {
  const displayWindows = missingAsZero ? windowsWithFeatureDefault(windows, feature, 0) : windows;
  const status = featureStatus(displayWindows, feature);
  const latest = latestFeatureValue(displayWindows, feature);
  const chartPayload = { title, feature, unit, color, windows: displayWindows, large, minimal };
  function openChart(event) {
    event.preventDefault();
    event.stopPropagation();
    onExpand?.(chartPayload);
  }

  return (
    <article
      className={`chart-card ${status.kind} ${onExpand ? "is-clickable" : ""} ${large ? "large-chart-card" : ""} ${minimal ? "chart-card-graph-only" : ""}`}
      title={onExpand ? `Apri ${title} in finestra grande` : undefined}
    >
      {!minimal && (
        <div className="chart-card-header">
          <div>
            <span>{title}</span>
            <strong>{formatFeatureValue(latest, unit)}</strong>
          </div>
          <div className="chart-card-actions">
            <FeatureStatusBadge status={status} />
            {onExpand && (
              <button
                className="chart-expand-button"
                type="button"
                onMouseDown={openChart}
                onClick={openChart}
                title="Ingrandisci grafico"
                aria-label={`Ingrandisci ${title}`}
              >
                <Maximize2 size={15} />
                <span>Apri</span>
              </button>
            )}
          </div>
        </div>
      )}
      {minimal && onExpand && (
        <button
          className="chart-expand-button floating-expand-button"
          type="button"
          onMouseDown={openChart}
          onClick={openChart}
          title="Ingrandisci grafico"
          aria-label={`Ingrandisci ${title}`}
        >
          <Maximize2 size={16} />
        </button>
      )}
      <TrendChart windows={displayWindows} feature={feature} color={color} unit={unit} title={title} large={large} minimal={minimal} />
    </article>
  );
}

function ChartDialog({ chart, windows, onClose }) {
  const dialogWindows = chart?.windows ?? windows;

  useEffect(() => {
    if (!chart) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    document.body.classList.add("dialog-open");
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.classList.remove("dialog-open");
    };
  }, [chart, onClose]);

  if (!chart) return null;
  return createPortal(
    <div className="chart-dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section
        className={`chart-dialog-panel ${chart.minimal ? "minimal-chart-dialog" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="chart-dialog-title"
      >
        <div className="chart-dialog-header">
          <span className="dialog-icon"><Maximize2 size={22} /></span>
          <div>
            <h3 id="chart-dialog-title">{chart.title}</h3>
            <p>Lettura ingrandita della serie temporale selezionata.</p>
          </div>
          <button className="dialog-close" type="button" onClick={onClose} aria-label="Chiudi grafico">
            <X size={19} />
          </button>
        </div>
        <div className="expanded-chart-panel">
          <TrendChart
            windows={dialogWindows}
            feature={chart.feature}
            color={chart.color}
            unit={chart.unit}
            title={chart.title}
            expanded
            large={false}
            minimal={chart.minimal}
          />
        </div>
      </section>
    </div>,
    document.body
  );
}

function TrendChart({ windows, feature, color, unit, title, expanded = false, large = false, minimal = false }) {
  const [hoverPoint, setHoverPoint] = useState(null);
  const [selectedIndex, setSelectedIndex] = useState(null);
  const [isPanning, setIsPanning] = useState(false);
  const scrollAreaRef = useRef(null);
  const panStateRef = useRef(null);
  const values = windows.map((window, index) => ({
    index,
    value: numericFeature(window.features, feature),
    label: formatDateTime(window.window_end),
    startLabel: formatDateTime(window.window_start),
    endLabel: formatDateTime(window.window_end),
    shortLabel: formatShortDateTime(window.window_end),
    status: featureStatusForWindow(window.features, feature),
  }));
  const numericValues = values.filter((point) => point.value !== null);
  if (numericValues.length === 0) {
    return <div className="chart-empty">Dato non acquisito</div>;
  }

  const width = expanded
    ? Math.max(minimal ? 1180 : 1040, Math.min(5000, 140 + Math.max(values.length - 1, 1) * 86))
    : large
      ? 920
      : 360;
  const height = expanded ? (minimal ? 360 : 255) : large ? 310 : 154;
  const padding = expanded
    ? { top: minimal ? 30 : 24, right: 36, bottom: minimal ? 64 : 54, left: 78 }
    : large
      ? { top: 24, right: 28, bottom: 60, left: 68 }
      : { top: 16, right: 14, bottom: 34, left: 46 };
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
  const selectedPoint = selectedIndex !== null ? points.find((point) => point.index === selectedIndex && point.value !== null) : null;
  const activePoint = hoverPoint ?? selectedPoint ?? points[numericValues.at(-1)?.index] ?? null;
  const xTickEvery = expanded ? Math.max(1, Math.ceil(values.length / 9)) : Math.max(1, values.length - 1);
  const xTicks = points.filter((point) => point.index === 0 || point.index === values.length - 1 || point.index % xTickEvery === 0);

  function yForValue(value) {
    return height - padding.bottom - ((value - min) / spread) * (height - padding.top - padding.bottom);
  }

  function nearestPointFromEvent(event) {
    const svg = event.currentTarget;
    const screenMatrix = svg.getScreenCTM?.();
    let svgX = null;
    if (screenMatrix) {
      const point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      svgX = point.matrixTransform(screenMatrix.inverse()).x;
    }
    if (svgX === null) {
      const rect = svg.getBoundingClientRect();
      svgX = ((event.clientX - rect.left) / rect.width) * width;
    }
    return numericValues
      .map((point) => points[point.index])
      .filter((point) => point?.value !== null)
      .reduce((best, point) => (Math.abs(point.x - svgX) < Math.abs(best.x - svgX) ? point : best));
  }

  function updateHover(event) {
    if (isPanning) return;
    const nearest = nearestPointFromEvent(event);
    setHoverPoint(nearest);
  }

  function selectPoint(point) {
    if (!point || point.value === null) return;
    setSelectedIndex(point.index);
    setHoverPoint(point);
  }

  function selectNearestPoint(event) {
    event.preventDefault();
    selectPoint(nearestPointFromEvent(event));
  }

  function moveSelection(direction) {
    const availableIndexes = numericValues.map((point) => point.index);
    const currentIndex = selectedIndex ?? activePoint?.index ?? availableIndexes.at(-1);
    const position = Math.max(0, availableIndexes.indexOf(currentIndex));
    const nextPosition = Math.min(availableIndexes.length - 1, Math.max(0, position + direction));
    setSelectedIndex(availableIndexes[nextPosition]);
    setHoverPoint(null);
  }

  function beginChartPan(event) {
    if (!expanded) return;
    if (event.button !== undefined && event.button !== 0) return;
    if (event.target?.closest?.("button")) return;
    const scrollArea = scrollAreaRef.current;
    if (!scrollArea || scrollArea.scrollWidth <= scrollArea.clientWidth) return;
    panStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      scrollLeft: scrollArea.scrollLeft,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setIsPanning(true);
  }

  function moveChartPan(event) {
    const panState = panStateRef.current;
    const scrollArea = scrollAreaRef.current;
    if (!panState || !scrollArea) return;
    scrollArea.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX);
    event.preventDefault();
  }

  function endChartPan(event) {
    const panState = panStateRef.current;
    if (!panState) return;
    event.currentTarget.releasePointerCapture?.(panState.pointerId);
    panStateRef.current = null;
    setIsPanning(false);
  }

  function scrollChartWithWheel(event) {
    if (!expanded) return;
    const scrollArea = scrollAreaRef.current;
    if (!scrollArea || scrollArea.scrollWidth <= scrollArea.clientWidth) return;
    const horizontalDelta = Math.abs(event.deltaX) >= Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    scrollArea.scrollLeft += horizontalDelta;
    event.preventDefault();
  }

  return (
    <div
      className={`chart-shell ${expanded ? "expanded" : ""} ${isPanning ? "is-panning" : ""}`}
      onPointerDown={beginChartPan}
      onPointerMove={moveChartPan}
      onPointerUp={endChartPan}
      onPointerCancel={endChartPan}
      onWheel={scrollChartWithWheel}
    >
      {expanded && !minimal && (
        <div className="expanded-chart-toolbar">
          <div>
            <strong>{title}</strong>
            <span>{numericValues.length} valori acquisiti su {values.length} finestre</span>
          </div>
        </div>
      )}
      <div ref={scrollAreaRef} className={`chart-scroll-area ${expanded ? "expanded-scroll" : ""}`}>
      <svg
        className="trend-chart"
        viewBox={`0 0 ${width} ${height}`}
        style={expanded ? { width: `${width}px`, minWidth: `${width}px` } : large ? { width: "100%" } : undefined}
        role="img"
        aria-label={`Andamento ${title}`}
        tabIndex={0}
        onMouseMove={updateHover}
        onMouseLeave={() => setHoverPoint(null)}
        onClick={selectNearestPoint}
        onFocus={() => setSelectedIndex((previous) => previous ?? numericValues.at(-1)?.index ?? null)}
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
        {xTicks.map((point) => (
          <g key={`${feature}-x-${point.index}`}>
            <line x1={point.x} y1={height - padding.bottom} x2={point.x} y2={height - padding.bottom + 6} className="chart-axis" />
            <text
              x={point.x}
              y={height - (expanded ? 34 : 18)}
              className="chart-tick-label"
              textAnchor={expanded ? "end" : point.index === 0 ? "start" : "end"}
              transform={expanded ? `rotate(-38 ${point.x} ${height - 34})` : undefined}
            >
              {expanded ? point.label : point.shortLabel}
            </text>
          </g>
        ))}
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
        {activePoint && (
          <line
            x1={activePoint.x}
            y1={padding.top}
            x2={activePoint.x}
            y2={height - padding.bottom}
            className="chart-hover-line"
          />
        )}
        {points.filter((point) => point.y !== null).map((point) => (
          <circle
            key={`${feature}-${point.index}`}
            cx={point.x}
            cy={point.y}
            r={activePoint?.index === point.index ? (expanded ? 7 : 6) : point.status === "imputed" ? 5 : 3.8}
            fill={point.status === "imputed" ? "#ffffff" : color}
            stroke={color}
            strokeWidth="2"
            className="chart-point"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              selectPoint(point);
            }}
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
      </div>
      {activePoint && !expanded && (
        <div
          className={`chart-tooltip ${activePoint.x > width / 2 ? "left" : "right"}`}
          style={{ left: `${(activePoint.x / width) * 100}%` }}
        >
          <strong>{formatFeatureValue(activePoint.value, unit)}</strong>
          <span>{activePoint.label}</span>
          <small>{activePoint.status === "imputed" ? "dato imputato" : "dato acquisito"}</small>
        </div>
      )}
      {activePoint && (
        <div className="expanded-chart-detail">
          <div>
            <span>{feature === "anomaly_score" ? "Score" : "Valore selezionato"}</span>
            <strong>{formatFeatureValue(activePoint.value, unit)}</strong>
          </div>
          <div>
            <span>{feature === "anomaly_score" ? "Finestra di raccolta" : "Istante temporale"}</span>
            <strong>{feature === "anomaly_score" ? `${activePoint.startLabel} - ${activePoint.endLabel}` : activePoint.label}</strong>
          </div>
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
      <Metric label="Permanenza massima" value={formatFeatureValue(latestFeatures.longest_single_room_minutes, "min")} />
    </div>
  );
}

function FeatureStatusBadge({ status, compact = false }) {
  return <span className={`feature-status ${status.kind} ${compact ? "compact-status" : ""}`}>{status.label}</span>;
}

const roomKeys = ["kitchen", "bedroom", "bathroom", "living_room"];
const defaultDayBands = [
  { label: "00-06", start: 0, end: 6 },
  { label: "06-10", start: 6, end: 10 },
  { label: "10-14", start: 10, end: 14 },
  { label: "14-18", start: 14, end: 18 },
  { label: "18-22", start: 18, end: 22 },
  { label: "22-24", start: 22, end: 24 },
];
const dayProfileMetricOptions = [
  { key: "ai", label: "Indice AI", feature: "anomaly_score", unit: "" },
  { key: "heart", label: "Battito", feature: "heart_rate_mean", unit: "bpm" },
  { key: "steps", label: "Passi", feature: "steps", unit: "" },
  { key: "sedentary", label: "Sedentarieta", feature: "sedentary_minutes", unit: "min" },
  { key: "movement", label: "Movimento indoor", feature: "room_changes", unit: "" },
];
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
    description: "Dati fisiologici, sonno e attivita",
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
    "BLE completo": "Il flusso BLE risulta completo per la finestra osservata.",
    "Google Health parziale": "Google Health ha fornito solo una parte dei dati attesi.",
    "modello personale disponibile": "Il profilo personale del paziente e' disponibile.",
    "wearable non rilevato": "Il wearable non risulta rilevato nella finestra corrente.",
    "BLE non aggiornato": "Il flusso BLE non risulta aggiornato.",
    "Google Health non aggiornato": "Google Health non risulta aggiornato.",
    "confidenza non ancora calcolata dal backend": "Il backend non ha ancora inviato un indice di confidenza dedicato.",
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

function hasWindowInterval(interval) {
  return Boolean(interval?.date || interval?.from || interval?.to);
}

function filterWindowsByCustomInterval(windows, interval) {
  if (!hasWindowInterval(interval)) return windows;
  return windows.filter((window) => {
    const timestamp = new Date(window.window_end);
    if (Number.isNaN(timestamp.getTime())) return false;
    const localDate = toLocalDateInputValue(timestamp);
    const localTime = toLocalTimeInputValue(timestamp);
    if (interval.date && localDate !== interval.date) return false;
    if (interval.from && localTime < interval.from) return false;
    if (interval.to && localTime > interval.to) return false;
    return true;
  });
}

function toLocalDateInputValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function toLocalTimeInputValue(date) {
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function rangeLabel(rangeMode) {
  return rangeMode === "week" ? "ultimi 7 giorni" : "ultimo giorno";
}

function latestFeaturesFromWindows(windows) {
  return [...windows].reverse().find((window) => window.features)?.features ?? {};
}

function decisionScoreWindows(decisions) {
  return decisions
    .map((decision, index) => {
      const score = numericFeature({ anomaly_score: decision.anomaly_score }, "anomaly_score");
      const timestamp = decision.window_end ?? decision.timestamp ?? decision.created_at;
      if (score === null || !timestamp) return null;
      return {
        window_id: decision.decision_id ?? `decision-score-${index}`,
        window_start: decision.window_start ?? timestamp,
        window_end: timestamp,
        features: {
          anomaly_score: score,
        },
      };
    })
    .filter(Boolean);
}

function morningBriefFallback(windows, decisions) {
  const nightWindows = (windows ?? []).filter((window) => {
    const timestamp = new Date(window.window_end ?? window.window_start);
    if (Number.isNaN(timestamp.getTime())) return false;
    const hour = timestamp.getHours();
    return hour >= 22 || hour < 8;
  });
  const nightDecisions = (decisions ?? []).filter((decision) => {
    const timestamp = new Date(decision.window_end ?? decision.timestamp ?? decision.created_at);
    if (Number.isNaN(timestamp.getTime())) return false;
    const hour = timestamp.getHours();
    return hour >= 22 || hour < 8;
  });
  const sleepMinutes = averageWindowFeature(nightWindows, "sleep_minutes");
  const nightRoomChanges = sumWindowFeature(nightWindows, "night_room_changes");
  const heartRate = averageWindowFeature(nightWindows, "heart_rate_mean");
  const scores = nightDecisions.map((decision) => Number(decision.anomaly_score)).filter(Number.isFinite);
  const maxScore = scores.length ? Math.max(...scores) : null;
  return {
    summary: nightWindows.length
      ? "Sintesi notturna ricavata dai dati gia' caricati in dashboard."
      : "Brief notturno in attesa: servono finestre tra le 22:00 e le 08:00.",
    sleep_minutes: sleepMinutes,
    night_room_changes: nightRoomChanges,
    heart_rate_mean: heartRate,
    max_score: maxScore,
    confidence: nightWindows.length ? "media" : "bassa",
  };
}

function buildDayProfileData(data, metric) {
  const apiProfile = data.dayProfile ?? {};
  const bands = normalizeDayBands(apiProfile.bands);
  const apiSeries = [
    {
      key: "today",
      label: "Oggi",
      color: "#147776",
      points: normalizeDayProfileSource(apiProfile.today, metric, bands),
    },
    {
      key: "yesterday",
      label: "Ieri",
      color: "#c58b13",
      points: normalizeDayProfileSource(apiProfile.yesterday, metric, bands),
    },
    {
      key: "baseline",
      label: "Giornata tipo",
      color: "#4d58a6",
      points: normalizeDayProfileSource(apiProfile.baseline_day ?? apiProfile.baseline, metric, bands),
    },
  ];
  if (apiSeries.some((series) => series.points.some((point) => Number.isFinite(point.value)))) {
    return {
      bands,
      series: apiSeries,
      baselineAvailable: apiProfile.baseline_available !== false,
    };
  }

  const rows = metric.key === "ai" ? decisionScoreWindows(data.decisions ?? []) : data.windows ?? [];
  const latestDate = latestLocalDate(rows);
  const yesterdayDate = shiftLocalDate(latestDate, -1);
  return {
    bands,
    baselineAvailable: false,
    series: [
      {
        key: "today",
        label: "Oggi",
        color: "#147776",
        points: aggregateRowsByBands(rows, metric.feature, bands, { onlyDate: latestDate }),
      },
      {
        key: "yesterday",
        label: "Ieri",
        color: "#c58b13",
        points: aggregateRowsByBands(rows, metric.feature, bands, { onlyDate: yesterdayDate }),
      },
      {
        key: "baseline",
        label: "Media storica",
        color: "#4d58a6",
        points: aggregateRowsByBands(rows, metric.feature, bands, { excludeDates: [latestDate, yesterdayDate] }),
      },
    ],
  };
}

function normalizeDayBands(bands) {
  if (Array.isArray(bands) && bands.length > 0) {
    return bands.map((band) => String(band?.label ?? band?.band ?? band?.name ?? band));
  }
  return defaultDayBands.map((band) => band.label);
}

function normalizeDayProfileSource(source, metric, bands) {
  const rows = Array.isArray(source) ? source : [];
  return bands.map((band, index) => {
    const row = rows.find((item) => String(item?.band ?? item?.label ?? item?.hour_band ?? "") === band) ?? rows[index] ?? {};
    const value = row?.[metric.key]
      ?? row?.[metric.feature]
      ?? row?.metrics?.[metric.key]
      ?? row?.metrics?.[metric.feature]
      ?? row?.value;
    const numeric = Number(value);
    return { band, value: Number.isFinite(numeric) ? numeric : null };
  });
}

function aggregateRowsByBands(rows, feature, bands, { onlyDate = "", excludeDates = [] } = {}) {
  return bands.map((band) => {
    const matching = (rows ?? []).filter((row) => {
      const timestamp = rowDate(row);
      if (!timestamp) return false;
      const localDate = toLocalDateInputValue(timestamp);
      if (onlyDate && localDate !== onlyDate) return false;
      if (excludeDates.includes(localDate)) return false;
      return dayBandLabel(timestamp) === band;
    });
    return { band, value: averageWindowFeature(matching, feature) };
  });
}

function latestLocalDate(rows) {
  const timestamps = (rows ?? [])
    .map(rowDate)
    .filter(Boolean)
    .map((date) => date.getTime())
    .filter(Number.isFinite);
  if (timestamps.length === 0) return toLocalDateInputValue(new Date());
  return toLocalDateInputValue(new Date(Math.max(...timestamps)));
}

function shiftLocalDate(dateValue, days) {
  if (!dateValue) return "";
  const date = new Date(`${dateValue}T12:00:00`);
  if (Number.isNaN(date.getTime())) return "";
  date.setDate(date.getDate() + days);
  return toLocalDateInputValue(date);
}

function rowDate(row) {
  const timestamp = row?.window_end ?? row?.timestamp ?? row?.created_at ?? row?.window_start;
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? null : date;
}

function dayBandLabel(date) {
  const hour = date.getHours();
  const band = defaultDayBands.find((item) => hour >= item.start && hour < item.end) ?? defaultDayBands.at(-1);
  return band.label;
}

function averageWindowFeature(rows, feature) {
  const values = (rows ?? [])
    .map((row) => numericFeature(row.features ?? row, feature))
    .filter((value) => value !== null);
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function sumWindowFeature(rows, feature) {
  const values = (rows ?? [])
    .map((row) => numericFeature(row.features ?? row, feature))
    .filter((value) => value !== null);
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0);
}

function dayProfileInsight(profile, metric) {
  const today = profile.series.find((series) => series.key === "today");
  const baseline = profile.series.find((series) => series.key === "baseline");
  if (!today?.points.some((point) => Number.isFinite(point.value))) {
    return "Non ci sono ancora valori sufficienti per descrivere la giornata corrente.";
  }
  if (!baseline?.points.some((point) => Number.isFinite(point.value))) {
    return "Il confronto con la routine personale sara' piu' utile quando Daniel avra' esposto la baseline circadiana.";
  }
  const deltas = today.points
    .map((point, index) => ({
      band: point.band,
      delta: Number(point.value) - Number(baseline.points[index]?.value),
    }))
    .filter((item) => Number.isFinite(item.delta));
  if (deltas.length === 0) return "Il confronto non e' ancora calcolabile per questa metrica.";
  const relevant = deltas.sort((left, right) => Math.abs(right.delta) - Math.abs(left.delta))[0];
  const direction = relevant.delta >= 0 ? "piu' alto" : "piu' basso";
  const amount = formatFeatureValue(Math.abs(relevant.delta), metric.unit);
  return `Nella fascia ${relevant.band} il valore risulta ${direction} della routine di circa ${amount}. Da leggere insieme a qualita' dati e contesto clinico.`;
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

function patientDisplayName(patient, fallbackPatientId) {
  const patientId = patient?.patient_id ?? fallbackPatientId;
  if (!patientId) return patient?.display_name ?? "Paziente";
  return patientProfileDisplayName(loadPatientProfile(patientId, patient), patient, patientId);
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
    unknown: "Stanza non rilevata",
  }[room ?? "unknown"] ?? room;
}

function TimelineView({ data }) {
  const [typeFilter, setTypeFilter] = useState("all");
  const [interval, setInterval] = useState({ date: "", from: "", to: "" });
  const events = useMemo(() => filterTimelineEvents(data.timeline ?? [], typeFilter, interval), [data.timeline, typeFilter, interval]);
  const types = useMemo(() => timelineTypeOptions(data.timeline ?? []), [data.timeline]);

  return (
    <section className="panel page-panel timeline-page">
      <div className="view-heading">
        <div className="view-heading-copy">
          <span className="view-heading-icon soft"><CalendarClock size={22} /></span>
          <div>
            <h3>Timeline del paziente</h3>
            <p>Eventi clinici, operativi e tecnici in ordine cronologico.</p>
          </div>
        </div>
        <span className="badge">{events.length} eventi</span>
      </div>
      <div className="filter-toolbar timeline-toolbar">
        <label className="timeline-type-filter">
          Tipo evento
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <option value="all">Tutti</option>
            {types.map((type) => <option key={type} value={type}>{eventTypeLabel(type)}</option>)}
          </select>
        </label>
        <WindowIntervalFilters value={interval} onChange={setInterval} onClear={() => setInterval({ date: "", from: "", to: "" })} />
      </div>
      {events.length === 0 ? (
        <ViewEmptyState icon={<CalendarClock size={24} />} title="Nessun evento nel periodo" text="Modifica filtri o intervallo temporale per ampliare la ricerca." />
      ) : (
        <div className="timeline-list">
          {events.map((event) => (
            <article key={event.event_id ?? `${event.event_type}-${event.timestamp}`} className={`timeline-item ${event.severity ?? "green"} ${timelineEventLowConfidence(event) ? "low-confidence" : ""}`}>
              <span className={`timeline-icon ${event.event_type}`}>{timelineIcon(event.event_type)}</span>
              <div>
                <div className="timeline-item-head">
                  <strong>{event.title ?? eventTypeLabel(event.event_type)}</strong>
                  <time>{formatDateTime(event.timestamp)}</time>
                </div>
                <p>{event.summary ?? "Evento registrato dal sistema."}</p>
                <div className="timeline-meta">
                  <span>{eventTypeLabel(event.event_type)}</span>
                  <span>{categoryLabel(event.source)}</span>
                  {timelineEventLowConfidence(event) && <span>Affidabilita bassa</span>}
                  {event.linked_resource?.id && <span>ID {event.linked_resource.id}</span>}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function windowsWithFeatureDefault(windows, feature, defaultValue) {
  return windows.map((window) => ({
    ...window,
    features: {
      ...(window.features ?? {}),
      [feature]: isMissingValue(window.features?.[feature]) ? defaultValue : window.features[feature],
    },
  }));
}

function EvaluationsView({ data, session, patientId, onChanged }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [scheduleForm, setScheduleForm] = useState({
    templateId: data.questionnaireTemplates?.[0]?.template_id ?? "",
    frequency: "daily",
    priority: "normal",
    nextRunAt: "",
  });
  const offline = data._offline === true;

  useEffect(() => {
    if (!scheduleForm.templateId && data.questionnaireTemplates?.[0]?.template_id) {
      setScheduleForm((previous) => ({ ...previous, templateId: data.questionnaireTemplates[0].template_id }));
    }
  }, [data.questionnaireTemplates, scheduleForm.templateId]);

  async function createSchedule() {
    if (offline) {
      setError("Dashboard offline: impossibile programmare questionari finche' il backend non torna raggiungibile.");
      return;
    }
    if (!scheduleForm.templateId) {
      setError("Seleziona un questionario da programmare.");
      return;
    }
    setBusy("schedule");
    setError("");
    setSuccess("");
    try {
      await api.createQuestionnaireSchedule(patientId, {
        template_id: scheduleForm.templateId,
        frequency: scheduleForm.frequency,
        priority: scheduleForm.priority,
        next_run_at: scheduleForm.nextRunAt ? new Date(scheduleForm.nextRunAt).toISOString() : null,
      }, session);
      setSuccess("Programmazione salvata.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function suspendSchedule(schedule) {
    if (offline) {
      setError("Dashboard offline: impossibile sospendere programmazioni finche' il backend non torna raggiungibile.");
      return;
    }
    setBusy(`suspend:${schedule.schedule_id}`);
    setError("");
    setSuccess("");
    try {
      await api.suspendQuestionnaireSchedule(schedule.schedule_id, session);
      setSuccess("Programmazione sospesa.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function generateNow(schedule) {
    if (offline) {
      setError("Dashboard offline: impossibile generare task finche' il backend non torna raggiungibile.");
      return;
    }
    setBusy(`generate:${schedule.schedule_id}`);
    setError("");
    setSuccess("");
    try {
      await api.generateQuestionnaireTask(schedule.schedule_id, session, true);
      setSuccess("Task generato e inviato al paziente.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel page-panel evaluations-page">
      <div className="view-heading">
        <div className="view-heading-copy">
          <span className="view-heading-icon task"><BrainCircuit size={22} /></span>
          <div>
            <h3>Centro valutazioni</h3>
            <p>Questionari programmabili e andamento dei risultati nel tempo.</p>
          </div>
        </div>
        <span className="badge">{data.questionnaireResults?.length ?? 0} risultati</span>
      </div>
      {error && <p className="inline-feedback error"><AlertTriangle size={17} />{error}</p>}
      {success && <p className="inline-feedback success"><CheckCircle2 size={17} />{success}</p>}
      {offline && <p className="inline-feedback error"><Info size={17} />Vista offline: programmazione e generazione questionari sono sospese.</p>}
      <div className="evaluation-grid">
        <section className="evaluation-card">
          <h4>Programma questionario</h4>
          <div className="task-form-grid">
            <label>
              Questionario
              <select value={scheduleForm.templateId} onChange={(event) => setScheduleForm((previous) => ({ ...previous, templateId: event.target.value }))}>
                <option value="" disabled>Seleziona questionario</option>
                {(data.questionnaireTemplates ?? []).map((template) => (
                  <option key={template.template_id} value={template.template_id}>{template.title ?? template.name ?? template.template_id}</option>
                ))}
              </select>
            </label>
            <label>
              Frequenza
              <select value={scheduleForm.frequency} onChange={(event) => setScheduleForm((previous) => ({ ...previous, frequency: event.target.value }))}>
                <option value="daily">Giornaliera</option>
                <option value="weekly">Settimanale</option>
              </select>
            </label>
            <label>
              Priorita
              <select value={scheduleForm.priority} onChange={(event) => setScheduleForm((previous) => ({ ...previous, priority: event.target.value }))}>
                {priorityOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label>
              Primo invio
              <input type="datetime-local" value={scheduleForm.nextRunAt} onChange={(event) => setScheduleForm((previous) => ({ ...previous, nextRunAt: event.target.value }))} />
            </label>
          </div>
          <button className="primary-button" type="button" onClick={createSchedule} disabled={offline || busy === "schedule"}>
            {busy === "schedule" ? <LoaderCircle className="spin" size={17} /> : <CalendarClock size={17} />}
            Salva programmazione
          </button>
        </section>
        <section className="evaluation-card">
          <h4>Template disponibili</h4>
          <div className="template-list">
            {(data.questionnaireTemplates ?? []).length === 0 ? <p className="empty-text">Nessun template ricevuto dal backend.</p> : data.questionnaireTemplates.map((template) => (
              <article key={template.template_id}>
                <strong>{template.title ?? template.name ?? template.template_id}</strong>
                <p>{template.description ?? "Questionario disponibile per invio o programmazione."}</p>
                {template.license_note && <small>{template.license_note}</small>}
              </article>
            ))}
          </div>
        </section>
      </div>
      <div className="evaluation-grid">
        <section className="evaluation-card">
          <h4>Programmazioni attive</h4>
          <div className="schedule-list">
            {(data.questionnaireSchedules ?? []).length === 0 ? <p className="empty-text">Nessuna programmazione salvata.</p> : data.questionnaireSchedules.map((schedule) => (
              <article key={schedule.schedule_id} className={schedule.status === "suspended" ? "is-muted" : ""}>
                <div>
                  <strong>{schedule.title ?? schedule.template?.title ?? schedule.template_id}</strong>
                  <p>{categoryLabel(schedule.frequency)} - prossimo invio {formatDateTime(schedule.next_run_at)}</p>
                </div>
                <div className="inline-actions">
                  <button className="secondary-button" type="button" onClick={() => generateNow(schedule)} disabled={offline || Boolean(busy)}>
                    Genera ora
                  </button>
                  <button className="secondary-button danger-soft" type="button" onClick={() => suspendSchedule(schedule)} disabled={offline || Boolean(busy) || schedule.status === "suspended"}>
                    Sospendi
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
        <section className="evaluation-card">
          <h4>Risultati recenti</h4>
          <div className="result-list">
            {(data.questionnaireResults ?? []).length === 0 ? <p className="empty-text">Nessun risultato completato.</p> : data.questionnaireResults.map((result) => (
              <article key={result.result_id ?? result.task_id ?? result.completed_at}>
                <strong>{result.template_title ?? result.title ?? "Valutazione completata"}</strong>
                <p>{taskResultScoreLabel(result)} - durata {formatTaskDuration(result.duration_seconds)}</p>
                <small>{formatDateTime(result.completed_at ?? result.created_at)}</small>
              </article>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

function RoutineView({ data, session, patientId }) {
  const [days, setDays] = useState("7");
  const [summary, setSummary] = useState(data.spatialSummary);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setSummary(data.spatialSummary);
  }, [data.spatialSummary, patientId]);

  useEffect(() => {
    if (!patientId || data._offline) return undefined;
    let cancelled = false;
    setLoading(true);
    setError("");
    api.spatialSummary(patientId, session, { days: Number(days) })
      .then((payload) => {
        if (!cancelled) setSummary(payload);
      })
      .catch((apiError) => {
        if (!cancelled) setError(readableApiError(apiError));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [days, patientId, session?.access_token, data._offline]);

  if (!summary) {
    return (
      <section className="panel page-panel">
        <ViewEmptyState icon={<Home size={24} />} title="Routine ambientale non disponibile" text="Il backend non ha ancora restituito l'aggregazione spaziale." />
      </section>
    );
  }

  const rooms = summary.room_minutes ?? {};
  const transitions = summary.transitions ?? summary.transition_matrix ?? [];
  const night = summary.night ?? {};
  const baseline = summary.baseline ?? {};

  return (
    <section className="panel page-panel routine-page">
      <div className="view-heading">
        <div className="view-heading-copy">
          <span className="view-heading-icon soft"><Home size={22} /></span>
          <div>
            <h3>Routine ambientale</h3>
            <p>Permanenze, transizioni e movimenti notturni rilevati dai beacon.</p>
          </div>
        </div>
        <label className="routine-period-select">
          <span>Periodo</span>
          <select value={days} onChange={(event) => setDays(event.target.value)} aria-label="Periodo routine" disabled={loading}>
            <option value="1">Oggi</option>
            <option value="2">Oggi e ieri</option>
            <option value="7">Ultimi 7 giorni</option>
          </select>
        </label>
      </div>
      {error && <p className="inline-feedback error"><AlertTriangle size={17} />{error}</p>}
      <div className="routine-summary-grid">
        <Metric icon={<MapPin size={18} />} label="Stanza prevalente" value={roomLabel(summary.prevalent_room)} />
        <Metric icon={<ArrowDownUp size={18} />} label="Transizioni" value={formatNumber(summary.room_changes ?? summary.transitions_count)} />
        <Metric icon={<Clock3 size={18} />} label="Permanenza massima" value={formatFeatureValue(summary.longest_single_room_minutes, "min")} />
        <Metric icon={<AlertTriangle size={18} />} label="Movimenti notturni" value={formatNumber(night.room_changes ?? summary.night_room_changes)} tone={(night.room_changes ?? summary.night_room_changes) > 0 ? "yellow" : "green"} />
      </div>
      <div className="routine-layout">
        <section className="routine-card">
          <h4>Minuti per stanza</h4>
          <div className="room-share-list">
            {Object.entries(rooms).map(([room, minutes]) => (
              <div key={room} className="room-share-row">
                <span>{roomLabel(room)}</span>
                <div className="room-share-track"><span style={{ width: `${roomShare(minutes, rooms)}%` }} /></div>
                <strong>{formatFeatureValue(minutes, "min")}</strong>
              </div>
            ))}
          </div>
        </section>
        <section className="routine-card">
          <h4>Transizioni principali</h4>
          <div className="transition-list">
            {normalizeTransitions(transitions).length === 0 ? <p className="empty-text">Nessuna transizione rilevante.</p> : normalizeTransitions(transitions).map((transition, index) => (
              <div key={`${transition.from}-${transition.to}-${index}`}>
                <span>{roomLabel(transition.from)} &rarr; {roomLabel(transition.to)}</span>
                <strong>{formatNumber(transition.count)} volte</strong>
              </div>
            ))}
          </div>
        </section>
        <section className="routine-card">
          <h4>Confronto con baseline</h4>
          <p>{baseline.summary ?? baseline.message ?? "Il confronto personale sara piu' affidabile quando la baseline sara completa."}</p>
          <small>Qualita BLE: {reliabilityLabel(summary.ble_quality?.status ?? summary.ble_quality)}</small>
        </section>
      </div>
    </section>
  );
}

function ReportView({ data, patient }) {
  const report = data.reportData;
  const displayName = patientDisplayName(patient, data.current?.patient_id);
  const reliabilityRows = normalizeModelMetrics(data.modelMetrics);
  const reliabilityValues = reliabilityRows.map((metric) => Number(metric.f1)).filter(Number.isFinite);
  const reliabilityMean = reliabilityValues.length ? reliabilityValues.reduce((total, value) => total + value, 0) / reliabilityValues.length : null;
  const reliabilityPercent = reliabilityMean !== null ? (reliabilityMean <= 1 ? reliabilityMean * 100 : reliabilityMean) : null;
  const printable = report ?? {
    patient: { display_name: displayName, patient_id: data.current?.patient_id },
    current: data.current,
    summary_24h: data.summary24h,
    spatial_summary: data.spatialSummary,
    recent_decisions: data.decisions?.slice(-5),
    recent_alerts: data.alerts?.slice(-5),
    recent_tasks: data.tasks?.slice(-5),
  };

  return (
    <section className="panel page-panel report-page">
      <div className="view-heading">
        <div className="view-heading-copy">
          <span className="view-heading-icon soft"><DatabaseZap size={22} /></span>
          <div>
            <h3>Report sintetico</h3>
            <p>Vista stampabile per demo, visita o discussione del caso.</p>
          </div>
        </div>
        <button className="primary-button" type="button" onClick={() => window.print()}>
          <DatabaseZap size={17} />
          Esporta PDF
        </button>
      </div>
      <article className="print-report">
        <header>
          <div>
            <span className="clinical-kicker">Report clinico sintetico</span>
            <h3>{displayName}</h3>
          </div>
          <span>Generato: {formatDateTime(new Date().toISOString())}</span>
        </header>
        <div className="report-grid">
          <Metric icon={<Gauge size={18} />} label="Indice AI corrente" value={scoreBandText(printable.current?.anomaly_score)} />
          <Metric icon={<MapPin size={18} />} label="Stanza corrente" value={roomLabel(printable.current?.current_room)} />
          <Metric icon={<Clock3 size={18} />} label="Ultimo aggiornamento" value={formatDateTime(printable.current?.last_update)} />
          <Metric icon={<AlertTriangle size={18} />} label="Segnalazioni recenti" value={formatNumber(printable.recent_alerts?.length)} />
        </div>
        <section>
          <h4>Brief del mattino</h4>
          <p>{(data.morningBrief ?? morningBriefFallback(data.windows, data.decisions)).summary}</p>
        </section>
        <section>
          <h4>Affidabilita modello</h4>
          <p>{Number.isFinite(reliabilityPercent) ? `${Math.round(reliabilityPercent)}% complessiva` : "Non ancora disponibile"}</p>
        </section>
        <DayProfileReportSection data={data} />
        <section>
          <h4>Decisioni recenti</h4>
          {(printable.recent_decisions ?? []).length === 0 ? <p>Nessuna decisione recente.</p> : (
            <ul className="report-list">
              {(printable.recent_decisions ?? []).map((decision) => (
                <li key={decision.decision_id ?? decision.window_end}>
                  {formatDateTime(decision.window_end ?? decision.created_at)} - {scoreBandText(decision.anomaly_score)}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h4>Attivita e alert</h4>
          <p>{formatNumber(printable.recent_tasks?.length)} attivita recenti, {formatNumber(printable.recent_alerts?.length)} segnalazioni recenti.</p>
          <p className="report-disclaimer">{report?.disclaimer ?? "Documento dimostrativo: supporta il triage, la decisione finale resta al personale sanitario."}</p>
        </section>
        <WeeklyReportsSection reports={data.weeklyReports ?? []} />
      </article>
    </section>
  );
}

function DayProfileReportSection({ data }) {
  const metric = dayProfileMetricOptions[0];
  const profile = buildDayProfileData(data, metric);
  return (
    <section className="day-profile-report-section">
      <h4>Giornata tipo</h4>
      <p>{dayProfileInsight(profile, metric)}</p>
    </section>
  );
}

function WeeklyReportsSection({ reports }) {
  const items = Array.isArray(reports) ? reports : [];
  const [selectedReportId, setSelectedReportId] = useState(items[0]?.report_id ?? items[0]?.week_start ?? "0");
  useEffect(() => {
    if (items.length === 0) {
      setSelectedReportId("0");
      return;
    }
    const selectionExists = items.some((report, index) => String(report.report_id ?? report.week_start ?? index) === String(selectedReportId));
    if (!selectionExists) setSelectedReportId(String(items[0].report_id ?? items[0].week_start ?? 0));
  }, [reports, selectedReportId]);
  const selected = items.find((report, index) => String(report.report_id ?? report.week_start ?? index) === String(selectedReportId)) ?? items[0] ?? null;
  return (
    <section className="weekly-report-section">
      <h4>Report settimanali</h4>
      {items.length === 0 ? (
        <p>Report settimanali non ancora generati dal backend.</p>
      ) : (
        <>
          <div className="weekly-report-toolbar">
            <label>
              Settimana
              <select value={selectedReportId} onChange={(event) => setSelectedReportId(event.target.value)}>
                {items.map((report, index) => {
                  const id = String(report.report_id ?? report.week_start ?? index);
                  return (
                    <option key={id} value={id}>
                      {report.title ?? formatWeekLabel(report)}
                    </option>
                  );
                })}
              </select>
            </label>
            <button className="secondary-button compact-action" type="button" onClick={() => window.print()}>
              <DatabaseZap size={16} />
              Esporta settimana
            </button>
          </div>
          {selected && (
            <article className="weekly-report-selected">
              <strong>{selected.title ?? formatWeekLabel(selected)}</strong>
              <span>
                Media AI {scoreBandText(selected.mean_score ?? selected.ai?.mean_score)} -
                massimo {scoreBandText(selected.max_score ?? selected.ai?.max_score)}
              </span>
              <small>{selected.summary ?? "Sintesi settimanale disponibile per export e revisione."}</small>
              <div className="report-grid compact-summary-grid">
                <Metric icon={<AlertTriangle size={17} />} label="Giorni attenzione" value={formatNumber(selected.attention_days ?? selected.ai?.attention_days, "0")} />
                <Metric icon={<ClipboardList size={17} />} label="Task completati" value={formatNumber(selected.completed_tasks ?? selected.tasks?.completed, "0")} />
                <Metric icon={<HeartPulse size={17} />} label="Sonno medio" value={formatFeatureValue(selected.sleep_mean ?? selected.sleep?.mean_minutes, "min")} />
              </div>
            </article>
          )}
        </>
      )}
    </section>
  );
}

function AlertsView({ data, session, patientId, onChanged, onTaskCreated }) {
  const [levelFilter, setLevelFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [rangeFilter, setRangeFilter] = useState("all");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [hiddenResolvedAlerts, setHiddenResolvedAlerts] = useState(() => new Set());
  const [notes, setNotes] = useState({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [dialog, setDialog] = useState(null);
  const [deleteDialog, setDeleteDialog] = useState(null);
  const [workflowDetails, setWorkflowDetails] = useState({});
  const offline = data._offline === true;

  const filteredAlerts = useMemo(
    () => filterAlerts(data.alerts, { levelFilter, statusFilter, rangeFilter })
      .filter((alert) => !hiddenResolvedAlerts.has(String(alert.alert_id))),
    [data.alerts, levelFilter, statusFilter, rangeFilter, hiddenResolvedAlerts]
  );
  const activeAlerts = data.alerts.filter((alert) => alert.status !== "resolved").length;

  function noteFor(alertId) {
    return notes[alertId] ?? "";
  }

  function updateNote(alertId, value) {
    setNotes((previous) => ({ ...previous, [alertId]: value }));
  }

  async function acknowledge(alert) {
    if (offline) {
      setError("Dashboard offline: impossibile prendere in carico finche' il backend non torna raggiungibile.");
      return;
    }
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
    if (offline) {
      setError("Dashboard offline: impossibile risolvere finche' il backend non torna raggiungibile.");
      return;
    }
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
    if (offline) {
      setError("Dashboard offline: impossibile creare attivita operative finche' il backend non torna raggiungibile.");
      return;
    }
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
      setSuccess("Attivita di follow-up creata. Apro la pagina Attivita aggiornata.");
      if (onTaskCreated) {
        await onTaskCreated();
      } else {
        await onChanged();
      }
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function sendCaregiverAlertMessage(alert) {
    if (offline) {
      setError("Dashboard offline: impossibile avvisare il caregiver finche' il backend non torna raggiungibile.");
      return;
    }
    setBusy(`${alert.alert_id}:caregiver`);
    setError("");
    setSuccess("");
    try {
      const details = absenceAlertDetails(alert, data.current, data.system);
      await api.createCaregiverMessage(alert.patient_id ?? patientId, {
        title: isAbsenceAlert(alert) ? "Verifica movimento paziente" : `Verifica segnalazione ${levelLabel(alert.level)}`,
        body: isAbsenceAlert(alert)
          ? `Per favore verifica il paziente: il sistema segnala assenza di movimento. Ultima stanza: ${details.room}. Durata stimata: ${details.duration}.`
          : `Per favore verifica il paziente e aggiorna il team di cura se noti qualcosa di insolito. Segnalazione: ${alertTitleLabel(alert)}.`,
        priority: taskPriorityForAlert(alert.level),
        source_alert_id: alert.alert_id,
      }, session);
      setSuccess("Caregiver avvisato con messaggio operativo.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function sendPatientAlertMessage(alert) {
    if (offline) {
      setError("Dashboard offline: impossibile inviare messaggi finche' il backend non torna raggiungibile.");
      return;
    }
    setBusy(`${alert.alert_id}:patient-message`);
    setError("");
    setSuccess("");
    try {
      const details = absenceAlertDetails(alert, data.current, data.system);
      const title = isAbsenceAlert(alert) ? "Ti va di confermare come stai?" : "Messaggio dal medico";
      const body = isAbsenceAlert(alert)
        ? `Il team di cura vorrebbe una conferma sul tuo stato. Se riesci, apri l'app e indica come stai. Ultima stanza rilevata: ${details.room}.`
        : `Il team di cura ti chiede un rapido controllo dopo una segnalazione. Apri l'app quando puoi.`;
      await api.createTask(alert.patient_id ?? patientId, {
        type: "custom",
        schema_version: 1,
        priority: taskPriorityForAlert(alert.level),
        assigned_to: "patient",
        title,
        instructions: body,
        payload: {
          kind: "patient_message",
          source_alert_id: alert.alert_id,
          delivery: {
            push_notification: true,
            in_app_banner: true,
          },
          message: {
            title,
            body,
            tone: taskPriorityForAlert(alert.level),
          },
        },
      }, session);
      setSuccess("Messaggio operativo inviato al paziente.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function loadAlertWorkflow(alert) {
    const alertId = alert.alert_id;
    if (workflowDetails[alertId]?.details) {
      setWorkflowDetails((previous) => ({ ...previous, [alertId]: { ...previous[alertId], open: !previous[alertId].open } }));
      return;
    }
    setWorkflowDetails((previous) => ({ ...previous, [alertId]: { loading: true, open: true } }));
    try {
      const details = await api.alertDetails(alertId, session);
      setWorkflowDetails((previous) => ({ ...previous, [alertId]: { loading: false, open: true, details } }));
    } catch (apiError) {
      setWorkflowDetails((previous) => ({
        ...previous,
        [alertId]: { loading: false, open: true, error: readableApiError(apiError) },
      }));
    }
  }

  async function deleteAlertPermanently(alert) {
    if (offline) {
      setError("Dashboard offline: impossibile eliminare definitivamente finche' il backend non torna raggiungibile.");
      return;
    }
    setBusy(`${alert.alert_id}:delete`);
    setError("");
    setSuccess("");
    try {
      await api.deleteAlert(alert.alert_id, session);
      setHiddenResolvedAlerts((previous) => new Set([...previous, String(alert.alert_id)]));
      setDeleteDialog(null);
      setSuccess("Segnalazione eliminata definitivamente dal backend.");
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
          <button
            className={`icon-button ${filtersOpen || levelFilter !== "all" || statusFilter !== "all" || rangeFilter !== "all" ? "active" : ""}`}
            type="button"
            onClick={() => setFiltersOpen((previous) => !previous)}
            title={filtersOpen ? "Nascondi filtri" : "Mostra filtri"}
            aria-label={filtersOpen ? "Nascondi filtri" : "Mostra filtri"}
          >
            <SlidersHorizontal size={18} />
          </button>
        </div>
      </div>
      {filtersOpen && (
        <div className="filter-toolbar alert-toolbar" aria-label="Filtri alert">
          <label>
            Livello
            <select value={levelFilter} onChange={(event) => setLevelFilter(event.target.value)}>
              <option value="all">Tutti</option>
              <option value="yellow">Attenzione</option>
              <option value="orange">Anomalia</option>
              <option value="red">Priorita' alta</option>
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
      )}
      {error && <p className="inline-feedback error" role="alert"><AlertTriangle size={17} />{error}</p>}
      {success && <p className="inline-feedback success" role="status"><CheckCircle2 size={17} />{success}</p>}
      {offline && <p className="inline-feedback error"><Info size={17} />Vista offline: prendi in carico, risoluzione, messaggi e cancellazioni sono sospesi.</p>}
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
            const resolutionNote = alertResolutionNote(alert);
            return (
            <article key={alert.alert_id} className={`alert-item ${alert.level} ${resolved ? "is-resolved compact-resolved" : ""}`}>
              <div className="alert-content">
                <div className="alert-card-header">
                  <div className="alert-title-row">
                    <span className={`alert-level-mark ${alert.level}`}><AlertTriangle size={16} /></span>
                    <span className={`badge ${alert.level}`}>{levelLabel(alert.level)}</span>
                    <span className={`status-pill ${alert.status}`}>{alertStatusLabel(alert.status)}</span>
                  </div>
                  <time>{formatDateTime(alertTimestamp(alert))}</time>
                </div>
                <h4>{alertTitleLabel(alert)}</h4>
                <p>{alertDescriptionLabel(alert)}</p>
                <div className="alert-data-grid">
                  <div className={`alert-score-card ${band.key}`}>
                    <span>Indice AI</span>
                    <strong>{Number.isFinite(Number(score)) ? scoreText(score) : "n/d"}</strong>
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
                {isAbsenceAlert(alert) && (
                  <AbsenceAlertContext alert={alert} current={data.current} system={data.system} />
                )}
                {reasons.length > 0 && (
                  <ul className="reason-list" aria-label="Motivi alert">
                    {reasons.map((reason) => (
                      <li key={`${alert.alert_id}-${reason}`}>{decisionReasonLabel(reason)}</li>
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
                {resolved && resolutionNote && (
                  <div className="alert-resolution-note">
                    <strong>Nota medico</strong>
                    <p>{resolutionNote}</p>
                  </div>
                )}
                <AlertWorkflowDetails
                  state={workflowDetails[alert.alert_id]}
                  onToggle={() => loadAlertWorkflow(alert)}
                />
                <small>{formatDateTime(alert.opened_at)} - stato {alert.status}</small>
              </div>
              {!resolved ? (
                <div className="alert-actions">
                <div className="alert-actions-title">
                  <strong>Azioni medico</strong>
                  <span>Revisione richiesta</span>
                </div>
                <button className="secondary-button" type="button" disabled={offline || busyForAlert || alert.status === "acknowledged"} onClick={() => setDialog({ type: "acknowledge", alert })}>
                  <CheckCircle2 size={16} />
                  Prendi in carico
                </button>
                <button className="primary-button" type="button" disabled={offline || busyForAlert} onClick={() => setDialog({ type: "resolve", alert })}>
                  <CheckCircle2 size={16} />
                  Risolvi
                </button>
                <button className="text-button" type="button" disabled={offline || busyForAlert} onClick={() => createAlertTask(alert)}>
                  <ClipboardList size={16} />
                  Crea attivita di follow-up
                </button>
                <button className="text-button" type="button" disabled={offline || busyForAlert} onClick={() => sendPatientAlertMessage(alert)}>
                  <Send size={16} />
                  Messaggio paziente
                </button>
                <button className="text-button" type="button" disabled={offline || busyForAlert} onClick={() => sendCaregiverAlertMessage(alert)}>
                  <MessageSquare size={16} />
                  Avvisa caregiver
                </button>
                </div>
              ) : (
                <div className="alert-actions resolved-actions">
                  <div className="alert-actions-title">
                    <strong>Storico</strong>
                    <span>Segnalazione chiusa</span>
                  </div>
                  <button className="secondary-button danger-soft" type="button" disabled={offline} onClick={() => setDeleteDialog(alert)}>
                    <Trash2 size={16} />
                    Elimina definitivamente
                  </button>
                </div>
              )}
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
      <ActionDialog
        open={Boolean(deleteDialog)}
        icon={<Trash2 size={22} />}
        title="Eliminare definitivamente?"
        description="La segnalazione verra cancellata dal backend e non tornera al refresh della dashboard."
        confirmLabel="Elimina definitivamente"
        busy={Boolean(deleteDialog && busy === `${deleteDialog.alert_id}:delete`)}
        onClose={() => !busy && setDeleteDialog(null)}
        onConfirm={() => deleteDialog && deleteAlertPermanently(deleteDialog)}
      >
        {deleteDialog && (
          <div className="dialog-summary-card">
            <span>{levelLabel(deleteDialog.level)}</span>
            <strong>{alertTitleLabel(deleteDialog)}</strong>
            <small>{formatDateTime(alertTimestamp(deleteDialog))}</small>
          </div>
        )}
      </ActionDialog>
    </section>
  );
}

function AbsenceAlertContext({ alert, current, system }) {
  const details = absenceAlertDetails(alert, current, system);
  return (
    <div className="absence-alert-context">
      <span className="absence-alert-icon"><Home size={18} /></span>
      <dl className="mini-detail-list">
        <Detail label="Ultima stanza" value={details.room} />
        <Detail label="Ultima transizione" value={details.transition} />
        <Detail label="Durata assenza" value={details.duration} />
        <Detail label="Qualita BLE" value={details.bleQuality} />
      </dl>
    </div>
  );
}

function AlertWorkflowDetails({ state, onToggle }) {
  const details = state?.details;
  const events = details?.workflow?.history ?? details?.related_events ?? details?.alert_events ?? [];
  return (
    <div className="alert-workflow-box">
      <button className="text-button" type="button" onClick={onToggle}>
        <CalendarClock size={16} />
        {state?.open ? "Nascondi workflow" : "Mostra workflow clinico"}
      </button>
      {state?.open && (
        <div className="workflow-detail-panel">
          {state.loading && <p className="empty-text">Caricamento contesto alert...</p>}
          {state.error && <p className="inline-feedback error"><AlertTriangle size={16} />{state.error}</p>}
          {details && (
            <>
              <div className="workflow-context-grid">
                <Metric icon={<Gauge size={17} />} label="Origine" value={categoryLabel(details.alert?.source ?? details.alert?.category)} />
                <Metric icon={<Clock3 size={17} />} label="Decisione collegata" value={details.context?.decision?.decision_id ?? details.decision?.decision_id ?? "n/d"} />
                <Metric icon={<ClipboardList size={17} />} label="Task collegati" value={formatNumber((details.tasks ?? []).length)} />
              </div>
              <div className="workflow-event-list">
                {events.length === 0 ? <p className="empty-text">Nessuna azione storica ricevuta.</p> : events.slice(0, 6).map((event, index) => (
                  <span key={event.event_id ?? index}>
                    <strong>{eventTypeLabel(event.event_type ?? event.action)}</strong>
                    {formatDateTime(event.timestamp ?? event.created_at)}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function TasksView({ data, session, patientId, onChanged }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [composerOpen, setComposerOpen] = useState(false);
  const [messageComposerOpen, setMessageComposerOpen] = useState(false);
  const [caregiverMessageComposerOpen, setCaregiverMessageComposerOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [taskFiltersOpen, setTaskFiltersOpen] = useState(false);
  const [hideCancelledTasks, setHideCancelledTasks] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [noteDrafts, setNoteDrafts] = useState({});
  const [cancelDialog, setCancelDialog] = useState(null);
  const [deleteTaskDialog, setDeleteTaskDialog] = useState(null);
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
  const [caregiverMessageForm, setCaregiverMessageForm] = useState({
    title: "Messaggio dal medico",
    body: "",
    priority: "normal",
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
  const selectedTask = selectedTaskId ? visibleTasks.find((task) => task.task_id === selectedTaskId) ?? null : null;
  const selectedTemplate = taskTemplates[taskForm.template] ?? taskTemplates.wellbeing;
  const offline = data._offline === true;

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

  useEffect(() => {
    if (!caregiverMessageComposerOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && !busy) setCaregiverMessageComposerOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [caregiverMessageComposerOpen, busy]);

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

  function updateCaregiverMessageForm(field, value) {
    setCaregiverMessageForm((previous) => ({ ...previous, [field]: value }));
  }

  function applyCaregiverMessageSuggestion(suggestion) {
    setCaregiverMessageForm((previous) => ({
      ...previous,
      title: suggestion.title,
      body: suggestion.body,
      priority: suggestion.priority,
      suggestionId: suggestion.id,
    }));
    setError("");
  }

  async function sendPatientMessage() {
    if (offline) {
      setError("Dashboard offline: impossibile inviare messaggi finche' il backend non torna raggiungibile.");
      return;
    }
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
      await api.createTask(patientId, payload, session);
      setMessageComposerOpen(false);
      setSelectedTaskId(null);
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

  async function sendCaregiverMessage() {
    if (offline) {
      setError("Dashboard offline: impossibile inviare messaggi al caregiver finche' il backend non torna raggiungibile.");
      return;
    }
    const title = caregiverMessageForm.title.trim() || "Messaggio dal medico";
    const body = caregiverMessageForm.body.trim();
    if (!body) {
      setError("Scrivi il testo del messaggio prima di inviarlo al caregiver.");
      return;
    }
    setBusy("caregiver-message");
    setError("");
    setSuccess("");
    try {
      await api.createCaregiverMessage(patientId, {
        title,
        body,
        priority: caregiverMessageForm.priority,
        suggestion_id: caregiverMessageForm.suggestionId || null,
      }, session);
      setCaregiverMessageComposerOpen(false);
      setCaregiverMessageForm({
        title: "Messaggio dal medico",
        body: "",
        priority: "normal",
        suggestionId: "",
      });
      setSuccess("Messaggio inviato al caregiver associato al profilo.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function createTask() {
    if (offline) {
      setError("Dashboard offline: impossibile creare attivita finche' il backend non torna raggiungibile.");
      return;
    }
    if (!taskForm.title.trim()) {
      setError("Inserisci un titolo per l'attivita.");
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
      if (taskForm.expiresAt.trim()) {
        const normalizedDate = taskForm.expiresAt.trim().replace(" ", "T");
        const parsedDate = new Date(normalizedDate);
        if (Number.isNaN(parsedDate.getTime())) {
          setError("Inserisci la scadenza nel formato AAAA-MM-GG HH:MM, oppure lasciala vuota.");
          setBusy("");
          return;
        }
        payload.expires_at = parsedDate.toISOString();
      }
      await api.createTask(patientId, payload, session);
      setComposerOpen(false);
      setSelectedTaskId(null);
      setSuccess("Attivita inviata correttamente al paziente.");
      onChanged();
    } catch (apiError) {
      setError(readableApiError(apiError));
    } finally {
      setBusy("");
    }
  }

  async function saveMedicalNote(task) {
    if (offline) {
      setError("Dashboard offline: impossibile salvare note finche' il backend non torna raggiungibile.");
      return;
    }
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
    if (offline) {
      setError("Dashboard offline: impossibile annullare attivita finche' il backend non torna raggiungibile.");
      return;
    }
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

  async function deleteTaskPermanently(task) {
    if (offline) {
      setError("Dashboard offline: impossibile eliminare definitivamente finche' il backend non torna raggiungibile.");
      return;
    }
    setBusy(`delete:${task.task_id}`);
    setError("");
    setSuccess("");
    try {
      await api.deleteTask(task.task_id, session);
      setDeleteTaskDialog(null);
      setSelectedTaskId(null);
      setSuccess("Attivita eliminata definitivamente dal backend.");
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
            <h3>Attivita per il paziente</h3>
            <p>Check-in e follow-up inviati all'applicazione companion.</p>
          </div>
        </div>
        <div className="view-heading-actions">
        <button className="secondary-button compact-action" type="button" onClick={() => setCaregiverMessageComposerOpen(true)} disabled={offline || Boolean(busy)}>
          <MessageSquare size={17} />
          Caregiver
        </button>
        <button className="secondary-button compact-action" type="button" onClick={() => setMessageComposerOpen(true)} disabled={offline || Boolean(busy)}>
          <MessageSquare size={17} />
          Paziente
        </button>
        <button className="primary-button compact-action" type="button" onClick={() => setComposerOpen(true)} disabled={offline || Boolean(busy)}>
          <Plus size={17} />
          Nuova
        </button>
        </div>
      </div>
      <div className="task-overview">
        <div><span>Totali</span><strong>{data.tasks.length}</strong></div>
        <div><span>Da completare</span><strong>{openTasks}</strong></div>
        <div><span>Completate</span><strong>{completedTasks}</strong></div>
        <div><span>Scadute</span><strong>{expiredTasks}</strong></div>
        <div><span>Annullate</span><strong>{cancelledTasks}</strong></div>
        <button
          className={`icon-button ${taskFiltersOpen || statusFilter !== "all" || hideCancelledTasks ? "active" : ""}`}
          type="button"
          onClick={() => setTaskFiltersOpen((previous) => !previous)}
          title={taskFiltersOpen ? "Nascondi filtri" : "Mostra filtri"}
          aria-label={taskFiltersOpen ? "Nascondi filtri" : "Mostra filtri"}
        >
          <SlidersHorizontal size={18} />
        </button>
        <button
          className={`icon-button task-clean-button ${hideCancelledTasks ? "active" : ""}`}
          type="button"
          onClick={() => {
            const nextHideCancelledTasks = !hideCancelledTasks;
            setHideCancelledTasks(nextHideCancelledTasks);
            if (nextHideCancelledTasks && statusFilter === "cancelled") setStatusFilter("all");
          }}
          title={hideCancelledTasks ? "Mostra annullate" : "Nascondi annullate"}
          aria-label={hideCancelledTasks ? "Mostra annullate" : "Nascondi annullate"}
        >
          {hideCancelledTasks ? <Eye size={17} /> : <EyeOff size={17} />}
        </button>
      </div>
      {taskFiltersOpen && (
        <div className="filter-toolbar task-filter-toolbar" aria-label="Filtri attivita">
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
          <span className="results-count"><strong>{visibleTasks.length}</strong> risultati</span>
        </div>
      )}
      {error && <p className="inline-feedback error" role="alert"><AlertTriangle size={17} />{error}</p>}
      {success && <p className="inline-feedback success" role="status"><CheckCircle2 size={17} />{success}</p>}
      {offline && <p className="inline-feedback error"><Info size={17} />Vista offline: creazione, invio, note, annullamento e cancellazione sono sospesi.</p>}
      {messageComposerOpen && createPortal(
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
                <PrettySelect
                  label="Priorita"
                  value={messageForm.priority}
                  options={priorityOptions}
                  onChange={(value) => updateMessageForm("priority", value)}
                />
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
              <button className="primary-button" type="button" onClick={sendPatientMessage} disabled={offline || busy === "message"}>
                {busy === "message" ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
                {busy === "message" ? "Invio" : "Invia messaggio"}
              </button>
            </div>
          </section>
        </div>,
        document.body
      )}
      {caregiverMessageComposerOpen && createPortal(
        <div
          className="task-composer-backdrop"
          role="presentation"
          onMouseDown={(event) => event.target === event.currentTarget && !busy && setCaregiverMessageComposerOpen(false)}
        >
          <section className="task-composer-panel patient-message-composer" aria-label="Caregiver">
            <div className="task-composer-header">
              <span className="dialog-icon"><MessageSquare size={20} /></span>
              <div>
                <h3>Messaggio al caregiver</h3>
                <p>Invia una richiesta operativa al familiare associato, senza mostrare dati clinici grezzi.</p>
              </div>
              <button className="dialog-close" type="button" onClick={() => !busy && setCaregiverMessageComposerOpen(false)} disabled={Boolean(busy)} aria-label="Chiudi">
                <X size={19} />
              </button>
            </div>
            <div className="patient-message-body">
              <div className="message-suggestion-grid" aria-label="Messaggi consigliati per caregiver">
                {caregiverMessageSuggestions.map((suggestion) => (
                  <button
                    key={suggestion.id}
                    className={caregiverMessageForm.suggestionId === suggestion.id ? "active" : ""}
                    type="button"
                    onClick={() => applyCaregiverMessageSuggestion(suggestion)}
                  >
                    <strong>{suggestion.title}</strong>
                    <span>{suggestion.body}</span>
                  </button>
                ))}
              </div>
              <div className="task-form-grid patient-message-form">
                <PrettySelect
                  label="Priorita"
                  value={caregiverMessageForm.priority}
                  options={priorityOptions}
                  onChange={(value) => updateCaregiverMessageForm("priority", value)}
                />
                <label>
                  Titolo notifica
                  <input value={caregiverMessageForm.title} onChange={(event) => updateCaregiverMessageForm("title", event.target.value)} maxLength={90} />
                </label>
                <label className="span-2">
                  Testo per il caregiver
                  <textarea
                    value={caregiverMessageForm.body}
                    onChange={(event) => updateCaregiverMessageForm("body", event.target.value)}
                    placeholder="Scrivi una richiesta chiara e pratica per il caregiver."
                    maxLength={1000}
                  />
                </label>
              </div>
            </div>
            <div className="task-composer-actions">
              <button className="secondary-button" type="button" onClick={() => !busy && setCaregiverMessageComposerOpen(false)} disabled={Boolean(busy)}>
                Annulla
              </button>
              <button className="primary-button" type="button" onClick={sendCaregiverMessage} disabled={offline || busy === "caregiver-message"}>
                {busy === "caregiver-message" ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
                {busy === "caregiver-message" ? "Invio" : "Invia al caregiver"}
              </button>
            </div>
          </section>
        </div>,
        document.body
      )}
      {composerOpen && createPortal(
        <div
          className="task-composer-backdrop"
          role="presentation"
          onMouseDown={(event) => event.target === event.currentTarget && !busy && setComposerOpen(false)}
        >
        <section className="task-composer-panel" aria-label="Nuova">
          <div className="task-composer-header">
            <span className="dialog-icon"><ClipboardList size={20} /></span>
            <div>
              <h3>Nuova</h3>
              <p>Prepara un contenuto da inviare al paziente tramite l'app companion.</p>
            </div>
            <button className="dialog-close" type="button" onClick={() => !busy && setComposerOpen(false)} disabled={Boolean(busy)} aria-label="Chiudi">
              <X size={19} />
            </button>
          </div>
          <div className="task-form-grid">
            <PrettySelect
              label="Tipo test"
              value={taskForm.template}
              options={Object.entries(taskTemplates).map(([key, template]) => ({ value: key, label: template.label }))}
              onChange={(value) => updateTaskForm("template", value)}
            />
            <PrettySelect
              label="Priorita"
              value={taskForm.priority}
              options={priorityOptions}
              onChange={(value) => updateTaskForm("priority", value)}
            />
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
              <span className="date-input-shell">
                <CalendarClock size={17} />
                <input
                  type="datetime-local"
                  value={taskForm.expiresAt}
                  onChange={(event) => updateTaskForm("expiresAt", event.target.value)}
                />
              </span>
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
            <button className="primary-button" type="button" onClick={createTask} disabled={offline || busy === "create"}>
              {busy === "create" ? <LoaderCircle className="spin" size={17} /> : <CheckCircle2 size={17} />}
              {busy === "create" ? "Salvataggio" : "Crea e invia"}
            </button>
          </div>
        </section>
        </div>,
        document.body
      )}
      {data.tasks.length === 0 ? (
        <ViewEmptyState icon={<ClipboardList size={24} />} title="Nessuna attivita assegnata" text="Crea un check-in o un follow-up per iniziare." />
      ) : visibleTasks.length === 0 ? (
        <ViewEmptyState icon={<Search size={24} />} title="Nessun risultato" text="Non ci sono attivita con lo stato selezionato." />
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
              <div className="task-card-actions" aria-label="Azioni rapide attivita">
                {!["completed", "cancelled", "expired"].includes(task.status) && (
                  <button
                    className="task-card-action danger"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setCancelDialog(task);
                    }}
                    disabled={offline || Boolean(busy)}
                  >
                    <X size={14} />
                    Annulla
                  </button>
                )}
                <button
                  className="task-card-action danger"
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    setDeleteTaskDialog(task);
                  }}
                  disabled={offline || Boolean(busy)}
                >
                  <Trash2 size={14} />
                  Elimina
                </button>
              </div>
              <ChevronRight className="task-chevron" size={18} />
            </article>
          ))}
        </div>
      )}
      {selectedTask && createPortal(
        <div
          className="task-detail-backdrop"
          role="presentation"
          onMouseDown={(event) => event.target === event.currentTarget && !busy && setSelectedTaskId(null)}
        >
          <section className="task-detail-dialog" role="dialog" aria-modal="true" aria-label={`Dettaglio attivita ${selectedTask.title}`}>
            <TaskDetailPanel
              task={selectedTask}
              noteDraft={noteDrafts[selectedTask.task_id] ?? selectedTask.medical_note ?? ""}
              busy={busy}
              offline={offline}
              onClose={() => setSelectedTaskId(null)}
              onNoteChange={(value) => updateNoteDraft(selectedTask.task_id, value)}
              onSaveNote={() => saveMedicalNote(selectedTask)}
            />
          </section>
        </div>,
        document.body
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
      <ActionDialog
        open={Boolean(deleteTaskDialog)}
        icon={<Trash2 size={22} />}
        title="Eliminare definitivamente?"
        description="L'attivita, gli eventuali risultati collegati e le notifiche associate verranno rimossi dal backend."
        confirmLabel="Elimina definitivamente"
        busy={Boolean(deleteTaskDialog && busy === `delete:${deleteTaskDialog.task_id}`)}
        onClose={() => !busy && setDeleteTaskDialog(null)}
        onConfirm={() => deleteTaskDialog && deleteTaskPermanently(deleteTaskDialog)}
      >
        {deleteTaskDialog && (
          <div className="dialog-summary-card">
            <span>{taskStatusLabel(deleteTaskDialog.status)}</span>
            <strong>{deleteTaskDialog.title}</strong>
            <small>Creata {formatDateTime(deleteTaskDialog.created_at)}</small>
          </div>
        )}
      </ActionDialog>
    </section>
  );
}

function TaskDetailPanel({ task, noteDraft, busy, offline = false, onClose, onNoteChange, onSaveNote }) {
  const result = task.result ?? task.latest_result ?? task.task_result ?? null;
  const answers = taskResultAnswers(result);
  return (
    <div className="task-detail-panel">
      <div className="task-detail-header">
        <div>
          <span className="detail-eyebrow">{taskDisplayType(task)}</span>
          <h4>{task.title}</h4>
        </div>
        <div className="task-detail-header-actions">
          <span className={`status-pill ${task.status}`}>{taskStatusLabel(task.status)}</span>
          {onClose && (
            <button className="dialog-close inline-close" type="button" onClick={onClose} disabled={Boolean(busy)} aria-label="Chiudi dettaglio attivita">
              <X size={19} />
            </button>
          )}
        </div>
      </div>

      <div className="task-detail-grid">
        <TaskDetailCard label="Priorita" value={taskPriorityLabel(task.priority)} />
        <TaskDetailCard label="Destinatario" value={taskAssigneeLabel(task.assigned_to)} />
        <TaskDetailCard label="Scadenza" value={task.due_at ? formatDateTime(task.due_at) : "Non impostata"} />
        <TaskDetailCard label="Score previsto" value={expectedTaskScore(task)} />
        <TaskDetailCard label="Completamento" value={result?.completed_at ? formatDateTime(result.completed_at) : "Non completato"} />
        <TaskDetailCard label="Durata" value={formatTaskDuration(result?.duration_seconds)} />
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
                    <dd>{String(answer.display_value ?? answer.value ?? answer.answer ?? "n/d")}</dd>
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
        <textarea value={noteDraft} onChange={(event) => onNoteChange(event.target.value)} placeholder="Aggiungi una nota clinica o operativa per lo storico" disabled={offline} />
      </label>
      <div className="task-detail-actions">
        <button className="secondary-button" type="button" onClick={onSaveNote} disabled={offline || Boolean(busy)}>
          <CheckCircle2 size={16} />
          Salva nota
        </button>
      </div>
    </div>
  );
}

function TaskDetailCard({ label, value }) {
  return (
    <div className="task-detail-card">
      <span>{label}</span>
      <strong>{value ?? "n/d"}</strong>
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
  return createPortal(
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
    </div>,
    document.body
  );
}

function SystemView({ data, events, wsStatus, session }) {
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
  const [diagnosticsState, setDiagnosticsState] = useState({
    loading: false,
    error: "",
    payload: data.operationalMetrics,
  });

  async function runQuickDiagnostics() {
    setDiagnosticsState((previous) => ({ ...previous, loading: true, error: "" }));
    try {
      const payload = await api.metrics(session);
      setDiagnosticsState({ loading: false, error: "", payload });
    } catch (apiError) {
      setDiagnosticsState((previous) => ({
        ...previous,
        loading: false,
        error: readableApiError(apiError),
      }));
    }
  }

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
          <div className="panel-actions">
            <button className="secondary-button compact-action" type="button" onClick={runQuickDiagnostics} disabled={diagnosticsState.loading}>
              {diagnosticsState.loading ? <LoaderCircle className="spin" size={16} /> : <MonitorCog size={16} />}
              Diagnostica rapida
            </button>
            <span className={`system-health-badge ${health.tone}`}>{health.label}</span>
          </div>
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
        <OperationalDiagnosticsPanel
          metrics={diagnosticsState.payload ?? data.operationalMetrics}
          error={diagnosticsState.error}
          status={status}
          wsStatus={wsStatus}
        />
      </section>

      <section className="panel span-2">
        <div className="panel-heading">
          <h3>Sensori e flussi dati</h3>
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
        <PrivacySafetyPanel />
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

function OperationalDiagnosticsPanel({ metrics, error, status, wsStatus }) {
  const counters = metrics?.counters ?? {};
  const suggestions = operationalSuggestions(status, wsStatus, metrics);
  return (
    <div className="operational-diagnostics">
      <div className="panel-heading compact-heading">
        <div>
          <h3>Diagnostica operativa</h3>
          <p className="panel-subtitle">Controllo rapido di backend, database, MQTT, Firebase, Edge e realtime.</p>
        </div>
        <span className={`badge ${metrics?.status === "ok" ? "green" : "technical"}`}>
          {metrics ? "metriche ricevute" : "in attesa"}
        </span>
      </div>
      {error && <p className="inline-feedback error"><AlertTriangle size={16} />{error}</p>}
      <div className="diagnostic-grid">
        <Metric icon={<Server size={18} />} label="Backend" value={metrics?.status === "ok" ? "Operativo" : "Da verificare"} tone={metrics?.status === "ok" ? "green" : "technical"} />
        <Metric icon={<DatabaseZap size={18} />} label="Database" value={`${formatNumber(counters.feature_windows_received, "0")} finestre`} />
        <Metric icon={<Wifi size={18} />} label="MQTT ricevuti" value={`${formatNumber(counters.edge_cycles_received, "0")} cicli Edge`} />
        <Metric icon={<Bell size={18} />} label="Notifiche" value={formatNumber(counters.notifications_total, "0")} />
        <Metric icon={<Users size={18} />} label="Device app" value={formatNumber(counters.patient_app_devices, "0")} />
        <Metric icon={<Activity size={18} />} label="WebSocket" value={`${formatNumber(counters.websocket_clients_connected, "0")} attivi`} tone={wsStatus === "connected" ? "green" : "yellow"} />
      </div>
      <div className="diagnostic-suggestions">
        {suggestions.map((suggestion) => (
          <span key={suggestion}><Info size={15} />{suggestion}</span>
        ))}
      </div>
    </div>
  );
}

function PrivacySafetyPanel() {
  return (
    <div className="privacy-safety-panel">
      <div className="panel-heading compact-heading">
        <div>
          <h3>Privacy interfaccia</h3>
          <p className="panel-subtitle">Messaggi brevi per mantenere la demo adatta al contesto sanitario.</p>
        </div>
        <ShieldCheck size={20} />
      </div>
      <ul className="compact-reason-list">
        <li>La dashboard non mostra token, password, certificati o refresh token.</li>
        <li>L'app caregiver deve ricevere solo messaggi operativi, senza feature AI grezze.</li>
        <li>I report esportati includono solo dati utili al triage e note cliniche essenziali.</li>
      </ul>
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

function operationalSuggestions(status, wsStatus, metrics) {
  const edge = status?.edge ?? {};
  const sensors = status?.sensors ?? {};
  const mqtt = edge.mqtt ?? {};
  const suggestions = [];
  if (edge.online === false) {
    suggestions.push("Raspberry offline: controllare receiver Edge, rete locale e avvio del servizio.");
  }
  if (Number(edge.mqtt_queue_depth ?? mqtt.queue_depth ?? 0) > 0 || statusTone(mqtt.status) === "error") {
    suggestions.push("MQTT non pubblica correttamente: controllare broker, credenziali Edge e certificato CA.");
  }
  if (sensors.watch?.present === false) {
    suggestions.push("Wearable assente: verificare che sia indossato e sincronizzato con Google Health.");
  }
  if (["missing", "stale"].includes(String(sensors.ble?.status))) {
    suggestions.push("BLE non aggiornato: verificare beacon, permessi Android e receiver locale.");
  }
  if (wsStatus !== "connected") {
    suggestions.push("Realtime non connesso: aggiornare token o riavviare backend/dashboard.");
  }
  if (!metrics) {
    suggestions.push("Metriche operative non ancora lette: usa Diagnostica rapida.");
  }
  return suggestions.length ? suggestions : ["Nessun intervento tecnico immediato suggerito dai dati disponibili."];
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
    caregiver_message_created: "Caregiver inviato",
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
  const reasons = Array.isArray(rawReasons)
    ? rawReasons.filter(Boolean)
    : typeof rawReasons === "string" && rawReasons.trim()
      ? [rawReasons.trim()]
      : alert.description
        ? [alert.description]
        : [];
  return [...new Set(reasons.map((reason) => decisionReasonLabel(reason)))];
}

function alertResolutionNote(alert) {
  const note = alert.resolution_note ?? alert.resolved_note ?? alert.payload?.resolution_note ?? alert.payload?.resolved_note;
  return typeof note === "string" && note.trim() ? note.trim() : "";
}

function alertTitleLabel(alert) {
  const score = alertScore(alert);
  const band = aiScoreBand(score);
  if (isAbsenceAlert(alert)) {
    return "Assenza di movimento da verificare";
  }
  if (String(alert.title ?? "").toLowerCase().startsWith("decision ai")) {
    return `Segnalazione ${band.label.toLowerCase()} - indice ${scoreText(score)}`;
  }
  return alert.title ?? "Segnalazione";
}

function alertDescriptionLabel(alert) {
  const description = String(alert.description ?? "").trim();
  if (isAbsenceAlert(alert)) {
    return "Il sistema segnala una permanenza o assenza di transizioni superiore all'atteso. Verificare con paziente o caregiver.";
  }
  if (!description) return "Evento da revisionare nel contesto clinico del paziente.";
  if (description.toLowerCase().startsWith("decision ai")) {
    return decisionReasonLabel(description.split(" - ").at(-1));
  }
  return decisionReasonLabel(description);
}

function isAbsenceAlert(alert) {
  const text = [
    alert?.title,
    alert?.description,
    alert?.category,
    alert?.type,
    alert?.payload?.kind,
    alert?.payload?.reason,
  ].filter(Boolean).join(" ").toLowerCase();
  return [
    "absence",
    "assenza",
    "no_movement",
    "no movement",
    "nessun movimento",
    "permanenza",
    "inactivity",
    "inattivita",
  ].some((token) => text.includes(token));
}

function absenceAlertDetails(alert, current, system) {
  const payload = alert?.payload?.content ?? alert?.payload ?? {};
  const ble = system?.sensors?.ble ?? {};
  const durationMinutes = payload.duration_minutes ?? payload.no_movement_minutes ?? payload.still_minutes;
  const transitionAt = payload.last_transition_at ?? payload.last_room_change_at ?? ble.last_transition_at ?? ble.last_seen_at;
  return {
    room: roomLabel(payload.last_room ?? payload.current_room ?? current?.current_room ?? ble.current_room),
    transition: transitionAt ? formatDateTime(transitionAt) : "non disponibile",
    duration: durationMinutes === null || durationMinutes === undefined ? "non disponibile" : formatDurationMinutes(Number(durationMinutes) * 60),
    bleQuality: qualityStatusLabel(payload.ble_quality ?? payload.quality_status ?? ble.status ?? system?.edge?.quality_status),
  };
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
    inactivity: "Riduzione dell'attivita",
    absence: "Assenza insolita",
    no_movement: "Assenza di movimento",
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
  if (isPatientMessageTask(task)) return "Paziente";
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

function formatWeekLabel(report) {
  const start = report?.week_start ?? report?.range?.start ?? report?.generated_at;
  const end = report?.week_end ?? report?.range?.end;
  if (!start) return "Settimana disponibile";
  return end ? `${formatShortDateTime(start)} - ${formatShortDateTime(end)}` : `Settimana ${formatDateTime(start)}`;
}

function reliabilityFromCompleteness(completeness) {
  const values = Object.values(completeness ?? {})
    .map((value) => Number(typeof value === "object" ? value?.ratio ?? value?.percentage : value))
    .filter(Number.isFinite)
    .map((value) => (value > 1 ? value / 100 : value));
  if (values.length === 0) return { key: "media", label: "media" };
  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  if (average >= 0.8) return { key: "alta", label: "alta" };
  if (average >= 0.5) return { key: "media", label: "media" };
  return { key: "bassa", label: "bassa" };
}

function confidenceFromPayload(decision, current, system) {
  const payload = decision?.confidence
    ?? decision?.payload?.confidence
    ?? current?.confidence
    ?? current?.ai_confidence
    ?? system?.ai?.confidence
    ?? null;
  if (payload && typeof payload === "object") return payload;
  const completeness = system?.data_completeness ?? system?.edge?.data_completeness ?? {};
  const reliability = reliabilityFromCompleteness(completeness);
  return {
    score: reliability.key === "alta" ? 82 : reliability.key === "media" ? 58 : 34,
    level: reliability.label,
    reasons: [],
  };
}

function confidenceLevelFromScore(score) {
  if (!Number.isFinite(score)) return "media";
  if (score >= 75) return "alta";
  if (score >= 45) return "media";
  return "bassa";
}

function normalizeModelMetrics(metrics) {
  if (!metrics || typeof metrics !== "object") return [];
  const source = metrics.models ?? metrics.items ?? metrics;
  if (Array.isArray(source)) {
    return source.map((item, index) => ({
      key: item.model ?? item.key ?? item.name ?? `model-${index}`,
      ...item,
    }));
  }
  return Object.entries(source)
    .filter(([, value]) => value && typeof value === "object")
    .map(([key, value]) => ({ key, ...value }));
}

function formatModelMetric(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "n/d";
  return numeric <= 1 ? numeric.toFixed(2) : `${numeric.toFixed(1)}%`;
}

function trendFromDecisions(decisions) {
  const rows = (decisions ?? [])
    .map((decision) => ({
      score: Number(decision.anomaly_score),
      time: new Date(decision.window_end ?? decision.timestamp ?? decision.created_at).getTime(),
    }))
    .filter((row) => Number.isFinite(row.score) && Number.isFinite(row.time))
    .slice(-40);
  if (rows.length < 2) {
    return { direction: "unknown", score_slope_per_day: null, window_days: null };
  }
  const first = rows[0];
  const last = rows.at(-1);
  const days = Math.max(1 / 24, (last.time - first.time) / (24 * 60 * 60 * 1000));
  const slope = (last.score - first.score) / days;
  return {
    direction: trendDirectionFromSlope(slope),
    score_slope_per_day: slope,
    window_days: Number(days.toFixed(1)),
  };
}

function trendDirectionFromSlope(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "unknown";
  if (numeric > 2) return "in_aumento";
  if (numeric < -2) return "in_diminuzione";
  return "stabile";
}

function trendDirectionLabel(direction) {
  return {
    in_aumento: "In aumento",
    increasing: "In aumento",
    in_diminuzione: "In diminuzione",
    decreasing: "In diminuzione",
    stabile: "Stabile",
    stable: "Stabile",
    unknown: "Non calcolabile",
  }[direction] ?? categoryLabel(direction);
}

function trendText(direction, trend) {
  if (!trend || direction === "unknown") return "Servono piu decisioni storiche per stimare una direzione affidabile.";
  if (["in_aumento", "increasing"].includes(direction)) {
    return "L'indice mostra una crescita progressiva: da leggere insieme a qualita' dei dati, alert e andamento funzionale.";
  }
  if (["in_diminuzione", "decreasing"].includes(direction)) {
    return "L'indice appare in riduzione nel periodo osservato, pur mantenendo la necessita' di controllo clinico.";
  }
  return "L'indice appare stabile nel periodo osservato.";
}

function driftStatusLabel(status) {
  return {
    stable: "Stabile",
    possible_drift: "Possibile drift",
    needs_review: "Richiede revisione",
    retrained: "Aggiornato",
    blocked: "Bloccato",
  }[String(status ?? "stable").toLowerCase()] ?? "Stabile";
}

function reliabilityLabel(value) {
  const normalized = String(value ?? "").toLowerCase();
  if (["high", "alta", "ok", "good"].includes(normalized)) return "alta";
  if (["low", "bassa", "poor", "critical"].includes(normalized)) return "bassa";
  if (["medium", "media", "warning"].includes(normalized)) return "media";
  return value ? categoryLabel(value) : "media";
}

function roomShare(value, rooms) {
  const total = Object.values(rooms ?? {}).reduce((sum, item) => sum + (Number(item) || 0), 0);
  if (!total) return 0;
  return Math.max(3, Math.min(100, ((Number(value) || 0) / total) * 100));
}

function filterTimelineEvents(events, typeFilter, interval) {
  return (events ?? []).filter((event) => {
    if (typeFilter !== "all" && event.event_type !== typeFilter) return false;
    if (!hasWindowInterval(interval)) return true;
    const timestamp = new Date(event.timestamp).getTime();
    if (!Number.isFinite(timestamp)) return false;
    const date = interval.date || new Date(event.timestamp).toISOString().slice(0, 10);
    const from = interval.from ? new Date(`${date}T${interval.from}`).getTime() : -Infinity;
    const to = interval.to ? new Date(`${date}T${interval.to}`).getTime() : Infinity;
    return timestamp >= from && timestamp <= to;
  });
}

function timelineTypeOptions(events) {
  return [...new Set((events ?? []).map((event) => event.event_type).filter(Boolean))].sort();
}

function timelineIcon(eventType) {
  if (String(eventType).includes("alert")) return <AlertTriangle size={18} />;
  if (String(eventType).includes("task") || String(eventType).includes("questionnaire")) return <ClipboardList size={18} />;
  if (String(eventType).includes("message")) return <MessageSquare size={18} />;
  if (String(eventType).includes("system") || String(eventType).includes("edge")) return <MonitorCog size={18} />;
  if (String(eventType).includes("decision")) return <BrainCircuit size={18} />;
  return <Clock3 size={18} />;
}

function timelineEventLowConfidence(event) {
  const confidence = event?.confidence ?? event?.details?.confidence ?? event?.payload?.confidence;
  if (!confidence) return false;
  const level = String(confidence.level ?? confidence.label ?? "").toLowerCase();
  const score = Number(confidence.score ?? confidence.value);
  return ["bassa", "low", "poor", "critical"].includes(level) || (Number.isFinite(score) && score < 45);
}

function normalizeTransitions(transitions) {
  if (Array.isArray(transitions)) {
    return transitions.map((transition) => ({
      from: transition.from ?? transition.source ?? transition.room_from,
      to: transition.to ?? transition.target ?? transition.room_to,
      count: transition.count ?? transition.value ?? transition.transitions,
    })).filter((transition) => transition.from || transition.to);
  }
  return Object.entries(transitions ?? {}).map(([key, count]) => {
    const [from, to] = key.split(/->|_/);
    return { from, to, count };
  });
}

function factorValueText(item) {
  const parts = [];
  if (item.value !== undefined && item.value !== null) parts.push(`valore ${formatNumber(item.value)}`);
  if (item.z_score !== undefined && item.z_score !== null) parts.push(`z-score ${formatNumber(item.z_score)}`);
  if (item.direction) parts.push(categoryLabel(item.direction));
  return parts.join(" - ") || "Dettaglio non disponibile";
}

function clinicalFactorSentence(item, tone) {
  const feature = item.feature ?? item.name;
  const label = item.label ?? clinicalFeatureName(feature);
  const direction = String(item.impact ?? item.direction ?? "").toLowerCase();
  if (tone === "missing" || item.imputed === true) {
    return `${label}: dato mancante o stimato dal sistema.`;
  }
  if (direction.includes("below") || direction.includes("sotto") || direction.includes("low")) {
    return `${label}: valore sotto il riferimento atteso.`;
  }
  if (direction.includes("above") || direction.includes("sopra") || direction.includes("high")) {
    return `${label}: valore sopra il riferimento atteso.`;
  }
  if (tone === "risk") return `${label}: contribuisce ad aumentare l'indice.`;
  if (tone === "protective") return `${label}: contribuisce a ridurre l'indice.`;
  return `${label}: elemento rilevante per la valutazione.`;
}

function modelContributionLabel(value) {
  return {
    generic_spatial: "Routine ambientale",
    generic_wearable: "Parametri wearable",
    personal: "Profilo personale",
  }[value] ?? categoryLabel(value);
}

function taskResultAnswers(result) {
  if (!result) return [];
  const answers = result.answers ?? result.content?.answers ?? [];
  return Array.isArray(answers) ? answers.filter(Boolean) : [];
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
  if (!patient) return "routine";
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




