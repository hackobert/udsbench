/** Dashboard-Aktionen: Formular ↔ Action-JSON und Tastenkürzel (rein, testbar). */

export const ACTION_TYPES = [
  "message",
  "sequence",
  "test",
  "suite",
  "uds",
  "unlock",
  "session",
  "step",
  "raw",
  "marker",
  "record_start",
  "record_stop",
  "report",
] as const;
export type ActionType = (typeof ACTION_TYPES)[number];

export interface Action {
  type: ActionType;
  ref?: string | number | null;
  ecu?: string | null;
  payload?: string | null;
  functional?: boolean;
  vars?: Record<string, unknown>;
  step?: Record<string, unknown> | null;
  can_id?: string | number | null;
  channel?: string;
  confirm?: boolean;
  report?: Record<string, unknown> | null;
}

export interface ButtonDef {
  label: string;
  action: Action;
  color?: string | null;
  icon?: string | null;
  shortcut?: string | null;
  description?: string;
}

/** Welche Formularfelder ein Aktionstyp nutzt. */
export const ACTION_FIELDS: Record<
  ActionType,
  ("ref" | "ecu" | "payload" | "functional" | "vars" | "step" | "can_id" | "channel" | "report")[]
> = {
  message: ["ref", "ecu", "vars", "functional"],
  sequence: ["ref", "ecu", "vars"],
  test: ["ref", "ecu", "vars"],
  suite: ["ref", "ecu", "vars"],
  uds: ["ecu", "payload", "functional", "vars"],
  unlock: ["ref", "ecu"],
  session: ["ref", "ecu"],
  step: ["ecu", "step", "vars"],
  raw: ["can_id", "payload", "channel"],
  marker: ["ref"],
  record_start: ["ref"],
  record_stop: [],
  report: ["report"],
};

/** Typen, die 'ref' zwingend brauchen (wie im Backend-Modell). */
export const REF_REQUIRED: ActionType[] = ["message", "sequence", "test", "suite", "unlock", "session"];

export interface ActionForm {
  type: ActionType;
  ref: string;
  ecu: string;
  payload: string;
  functional: boolean;
  vars: string;
  step: string;
  can_id: string;
  channel: string;
  confirm: boolean;
  report: string;
}

export function emptyForm(type: ActionType = "message"): ActionForm {
  return {
    type,
    ref: "",
    ecu: "",
    payload: "",
    functional: false,
    vars: "",
    step: "",
    can_id: "",
    channel: "default",
    confirm: false,
    report: "",
  };
}

function parseObj(text: string, name: string): Record<string, unknown> | null {
  if (!text.trim()) return null;
  let v: unknown;
  try {
    v = JSON.parse(text);
  } catch (exc) {
    throw new Error(`${name}: ${(exc as Error).message}`);
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error(`${name}: JSON-Objekt erwartet`);
  return v as Record<string, unknown>;
}

/** Formular → Action-Objekt (nur die für den Typ relevanten Felder). Wirft bei fehlenden Pflichtfeldern. */
export function buildAction(f: ActionForm): Action {
  const fields = ACTION_FIELDS[f.type];
  const a: Action = { type: f.type };
  if (fields.includes("ref") && f.ref.trim()) {
    const r = f.ref.trim();
    a.ref = (f.type === "unlock" || f.type === "session") && /^\d+$/.test(r) ? Number(r) : r;
  }
  if (REF_REQUIRED.includes(f.type) && (a.ref === undefined || a.ref === ""))
    throw new Error(`Aktion '${f.type}' benötigt eine Auswahl (ref)`);
  if (fields.includes("ecu") && f.ecu.trim()) a.ecu = f.ecu.trim();
  if (fields.includes("payload")) {
    if (!f.payload.trim()) throw new Error(`Aktion '${f.type}' benötigt eine Nutzlast (Hex)`);
    a.payload = f.payload.trim();
  }
  if (fields.includes("functional") && f.functional) a.functional = true;
  if (fields.includes("vars")) {
    const v = parseObj(f.vars, "vars");
    if (v && Object.keys(v).length) a.vars = v;
  }
  if (fields.includes("step")) {
    const s = parseObj(f.step, "step");
    if (!s) throw new Error("Aktion 'step' benötigt einen Schritt (JSON)");
    a.step = s;
  }
  if (fields.includes("can_id")) {
    if (!f.can_id.trim()) throw new Error("Aktion 'raw' benötigt eine CAN-ID");
    const id = f.can_id.trim();
    a.can_id = /^0x/i.test(id) ? id : `0x${id}`;
  }
  if (fields.includes("channel") && f.channel.trim() && f.channel.trim() !== "default")
    a.channel = f.channel.trim();
  if (fields.includes("report")) {
    const r = parseObj(f.report, "report");
    if (r) a.report = r;
  }
  if (f.confirm) a.confirm = true;
  return a;
}

/** Action-Objekt → Formular. */
export function actionToForm(a: Action | null | undefined): ActionForm {
  const f = emptyForm(a?.type ?? "message");
  if (!a) return f;
  f.ref = a.ref === null || a.ref === undefined ? "" : String(a.ref);
  f.ecu = a.ecu ?? "";
  f.payload = a.payload ?? "";
  f.functional = Boolean(a.functional);
  f.vars = a.vars && Object.keys(a.vars).length ? JSON.stringify(a.vars) : "";
  f.step = a.step ? JSON.stringify(a.step, null, 2) : "";
  f.can_id = a.can_id === null || a.can_id === undefined ? "" : String(a.can_id);
  f.channel = a.channel ?? "default";
  f.confirm = Boolean(a.confirm);
  f.report = a.report ? JSON.stringify(a.report, null, 2) : "";
  return f;
}

export interface Shortcut {
  ctrl: boolean;
  alt: boolean;
  shift: boolean;
  meta: boolean;
  key: string;
}

/** "ctrl+shift+1" → Shortcut; null bei leerer/ungültiger Angabe. */
export function parseShortcut(s: string | null | undefined): Shortcut | null {
  if (!s || !s.trim()) return null;
  const parts = s
    .toLowerCase()
    .split("+")
    .map((p) => p.trim())
    .filter(Boolean);
  const key = parts.pop();
  if (!key) return null;
  const mods = new Set(parts);
  return {
    ctrl: mods.has("ctrl") || mods.has("strg") || mods.has("control"),
    alt: mods.has("alt"),
    shift: mods.has("shift"),
    meta: mods.has("meta") || mods.has("cmd"),
    key,
  };
}

export function matchShortcut(
  ev: { key: string; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; metaKey: boolean; code?: string },
  sc: Shortcut,
): boolean {
  const key = ev.key.toLowerCase();
  const codeKey = (ev.code ?? "").replace(/^Digit|^Key/, "").toLowerCase();
  return (
    (key === sc.key || codeKey === sc.key) &&
    ev.ctrlKey === sc.ctrl &&
    ev.altKey === sc.alt &&
    ev.shiftKey === sc.shift &&
    ev.metaKey === sc.meta
  );
}
