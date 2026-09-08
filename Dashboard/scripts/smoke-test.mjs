import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cwd } from "node:process";

const root = cwd();
const app = readFileSync(join(root, "src", "App.jsx"), "utf8");
const client = readFileSync(join(root, "src", "api", "client.js"), "utf8");
const main = readFileSync(join(root, "src", "main.jsx"), "utf8");

const checks = [
  ["ErrorBoundary attivo", main.includes("ErrorBoundary")],
  ["offline cache paziente", app.includes("savePatientDataCache") && app.includes("_offline")],
  ["metriche modello AI", app.includes("ModelReliabilityPanel") && client.includes("modelMetrics")],
  ["confidenza decisione", app.includes("ConfidenceQualityPanel")],
  ["giornata tipo", app.includes("DayProfileView") && client.includes("dayProfile")],
  ["brief mattino", app.includes("MorningBriefPanel") && client.includes("morningBrief")],
  ["report settimanali", app.includes("WeeklyReportsSection") && client.includes("weeklyReports")],
  ["diagnostica rapida", app.includes("OperationalDiagnosticsPanel") && client.includes("metrics")],
];

const failed = checks.filter(([, ok]) => !ok);

for (const [name, ok] of checks) {
  console.log(`${ok ? "OK" : "FAIL"} - ${name}`);
}

if (failed.length > 0) {
  process.exitCode = 1;
}
