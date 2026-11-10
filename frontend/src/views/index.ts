import type { ViewDef } from "../view";
import { createConnectionView } from "./connection";
import { createConsoleView } from "./console";
import { createDashboardsView } from "./dashboards";
import { createDidsView } from "./dids";
import { createDtcsView } from "./dtcs";
import { createIsoTpView } from "./isotp";
import { createLogsView } from "./logs";
import { createMessagesView } from "./messages";
import { createPackagesView } from "./packages";
import { createRecordingsView } from "./recordings";
import { createReportsView } from "./reports";
import { createRoutinesView } from "./routines";
import { createSecurityView } from "./security";
import { createSequencesView } from "./sequences";
import { createTestsView } from "./tests";
import { createTimechartView } from "./timechart";
import { createTraceView } from "./trace";
import { createUdsView } from "./uds";

/**
 * Ansichten in Navigationsreihenfolge (Alt+1 … Alt+0 folgen dieser Reihenfolge).
 * Die IDs entsprechen den Kontext-Namen der Hilfe-API (/help/context/{id}).
 */
export const VIEWS: ViewDef[] = [
  { id: "trace", title: "nav.trace", icon: "trace", group: "observe", create: createTraceView },
  { id: "timechart", title: "nav.timechart", icon: "chart", group: "observe", create: createTimechartView },
  { id: "uds", title: "nav.uds", icon: "send", group: "diagnose", create: createUdsView },
  { id: "dids", title: "nav.dids", icon: "did", group: "diagnose", create: createDidsView },
  { id: "dtcs", title: "nav.dtcs", icon: "dtc", group: "diagnose", create: createDtcsView },
  { id: "routines", title: "nav.routines", icon: "routine", group: "diagnose", create: createRoutinesView },
  { id: "security", title: "nav.security", icon: "lock", group: "diagnose", create: createSecurityView },
  { id: "messages", title: "nav.messages", icon: "message", group: "automate", create: createMessagesView },
  {
    id: "sequences",
    title: "nav.sequences",
    icon: "sequence",
    group: "automate",
    create: createSequencesView,
  },
  { id: "tests", title: "nav.tests", icon: "test", group: "automate", create: createTestsView },
  {
    id: "dashboards",
    title: "nav.dashboard",
    icon: "dashboard",
    group: "automate",
    create: createDashboardsView,
  },
  { id: "reports", title: "nav.reports", icon: "report", group: "evaluate", create: createReportsView },
  {
    id: "recordings",
    title: "nav.recordings",
    icon: "record",
    group: "evaluate",
    create: createRecordingsView,
  },
  { id: "logs", title: "nav.logs", icon: "logs", group: "evaluate", create: createLogsView },
  { id: "connection", title: "nav.connection", icon: "plug", group: "system", create: createConnectionView },
  { id: "isotp", title: "nav.isotp", icon: "layers", group: "system", create: createIsoTpView },
  { id: "packages", title: "nav.packages", icon: "package", group: "system", create: createPackagesView },
  { id: "console", title: "nav.console", icon: "terminal", group: "system", create: createConsoleView },
];

export const NAV_GROUPS = ["observe", "diagnose", "automate", "evaluate", "system"] as const;
export type NavGroup = (typeof NAV_GROUPS)[number];

/** Startansicht beim ersten Öffnen. */
export const START_VIEW = "dashboards";
