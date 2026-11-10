/** Zustandslogik des 3-Schritt-Ablaufs „Konfiguration aus Spezifikation (KI)“ – ohne DOM, testbar. */

export const AI_SECTIONS = [
  "isotp",
  "ecus",
  "security",
  "dids",
  "dtcs",
  "routines",
  "messages",
  "sequences",
  "tests",
  "simulation",
] as const;
export type AiSection = (typeof AI_SECTIONS)[number];

export interface AiPromptForm {
  packageId: string;
  packageName: string;
  sections: AiSection[];
  simulation: boolean;
  tests: boolean;
  notes: string;
  jsonSchema: boolean;
}

export function defaultPromptForm(): AiPromptForm {
  return {
    packageId: "",
    packageName: "",
    sections: AI_SECTIONS.filter((s) => s !== "simulation"),
    simulation: false,
    tests: true,
    notes: "",
    jsonSchema: false,
  };
}

/** Formular → Query für GET /config/ai-prompt. „Testdouble“/„Tests“ steuern auch die Abschnitte. */
export function promptQuery(f: AiPromptForm): Record<string, string> {
  const sections = new Set<AiSection>(f.sections);
  if (f.simulation) sections.add("simulation");
  else sections.delete("simulation");
  if (f.tests) sections.add("tests");
  else sections.delete("tests");
  const q: Record<string, string> = {
    sections: AI_SECTIONS.filter((s) => sections.has(s)).join(","),
    simulation: String(f.simulation),
    tests: String(f.tests),
    json_schema: String(f.jsonSchema),
  };
  if (f.packageId.trim()) q["package_id"] = f.packageId.trim();
  if (f.packageName.trim()) q["package_name"] = f.packageName.trim();
  if (f.notes.trim()) q["notes"] = f.notes.trim();
  return q;
}

export interface AiCheckError {
  loc?: string;
  msg?: string;
  type?: string;
}

export interface AiCheckResult {
  ok: boolean;
  message?: string;
  package?: {
    id: string;
    name: string;
    version: string;
    hash?: string;
    counts: Record<string, number>;
    active?: boolean;
  };
  /** Validierungsfehler als Objekte; bei Kollisionen liefert das Backend reine Texte. */
  errors?: (AiCheckError | string)[];
  todos?: string[];
  fix_prompt?: string;
  imported?: boolean;
}

export interface AiFlowState {
  prompt: string | null;
  answer: string;
  /** Ergebnis der letzten Prüfung und die geprüfte Antwort (Änderungen machen die Prüfung ungültig). */
  check: AiCheckResult | null;
  checkedAnswer: string | null;
  imported: AiCheckResult | null;
}

export function initialFlow(): AiFlowState {
  return { prompt: null, answer: "", check: null, checkedAnswer: null, imported: null };
}

export function withPrompt(s: AiFlowState, prompt: string): AiFlowState {
  return { ...s, prompt };
}

/** Antwort geändert: Prüfung verfällt, wenn sich der Text unterscheidet. */
export function withAnswer(s: AiFlowState, answer: string): AiFlowState {
  const stale = s.checkedAnswer !== null && s.checkedAnswer !== answer;
  return {
    ...s,
    answer,
    check: stale ? null : s.check,
    checkedAnswer: stale ? null : s.checkedAnswer,
    imported: stale ? null : s.imported,
  };
}

export function withCheck(s: AiFlowState, checkedAnswer: string, result: AiCheckResult): AiFlowState {
  return { ...s, check: result, checkedAnswer, imported: null };
}

export function withImport(s: AiFlowState, result: AiCheckResult): AiFlowState {
  return result.ok ? { ...s, imported: result } : { ...s, check: result, imported: null };
}

export function canCheck(s: AiFlowState): boolean {
  return s.answer.trim().length > 0;
}

/** Import nur nach erfolgreicher Prüfung genau dieser Antwort. */
export function canImport(s: AiFlowState): boolean {
  return Boolean(s.check?.ok) && s.checkedAnswer === s.answer && s.answer.trim().length > 0 && !s.imported;
}

/** Aktueller Schritt (1 = Prompt, 2 = Antwort/Prüfung, 3 = Import, 4 = fertig). */
export function currentStep(s: AiFlowState): 1 | 2 | 3 | 4 {
  if (s.imported?.ok) return 4;
  if (canImport(s)) return 3;
  if (s.prompt !== null || s.answer.trim()) return 2;
  return 1;
}

/** Pydantic-Pfad lesbar: "ecus.0.isotp" → "ecus › Eintrag 1 › isotp". */
export function formatLoc(loc: string | undefined): string {
  if (!loc) return "Paket";
  return loc
    .split(".")
    .map((p) => (/^\d+$/.test(p) ? `Eintrag ${Number(p) + 1}` : p))
    .join(" › ");
}

/** Häufige Validator-Meldungen verständlich formulieren. */
export function explainMsg(msg: string | undefined): string {
  const m = msg ?? "";
  if (/Extra inputs are not permitted/i.test(m))
    return "Feld ist im Schema nicht vorgesehen (Tippfehler oder unbekanntes Feld).";
  if (/Field required/i.test(m)) return "Pflichtfeld fehlt.";
  if (/valid list/i.test(m)) return "Hier wird eine Liste erwartet (YAML: Einträge mit „- “).";
  if (/valid dictionary|valid object/i.test(m)) return "Hier wird ein Objekt (Schlüssel: Wert) erwartet.";
  if (/valid integer/i.test(m)) return "Hier wird eine ganze Zahl erwartet (z. B. 0x7E0 oder 2016).";
  return m;
}

export interface CheckView {
  tone: "ok" | "fail" | "none";
  tiles: { key: string; count: number }[];
  todos: string[];
  errors: { path: string; message: string; raw: string }[];
  fixPrompt: string | null;
}

const TILE_ORDER = [
  "ecus",
  "isotp_profiles",
  "dids",
  "dtcs",
  "routines",
  "security_providers",
  "messages",
  "sequences",
  "tests",
  "testsuites",
  "simulated_ecus",
];

export function checkView(r: AiCheckResult | null): CheckView {
  if (!r) return { tone: "none", tiles: [], todos: [], errors: [], fixPrompt: null };
  const counts = r.package?.counts ?? {};
  return {
    tone: r.ok ? "ok" : "fail",
    tiles: TILE_ORDER.filter((k) => k in counts).map((k) => ({ key: k, count: counts[k] ?? 0 })),
    todos: r.todos ?? [],
    errors: (r.errors ?? []).map((e) =>
      typeof e === "string"
        ? { path: formatLoc(undefined), message: e, raw: e }
        : { path: formatLoc(e.loc), message: explainMsg(e.msg), raw: e.msg ?? "" },
    ),
    fixPrompt: r.ok ? null : (r.fix_prompt ?? null),
  };
}
