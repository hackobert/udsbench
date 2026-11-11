/** DBC-Bereich: Typen und Hilfsfunktionen ohne DOM (testbar). */

export interface DbcSignal {
  name: string;
  start: number;
  length: number;
  byte_order: "little_endian" | "big_endian";
  signed: boolean;
  float: boolean;
  scale: number;
  offset: number;
  minimum: number | null;
  maximum: number | null;
  unit: string;
  choices: Record<string, string> | null;
  comment: string | null;
  multiplexer: boolean;
  multiplexer_ids: number[] | null;
}

export interface DbcMessage {
  dbc?: string;
  name: string;
  id: number;
  id_hex: string;
  extended: boolean;
  fd: boolean;
  length: number;
  cycle_time?: number | null;
  senders?: string[];
  comment?: string | null;
  signals: DbcSignal[];
}

export interface DbcFileSummary {
  id: string;
  name: string;
  messages: number;
  signals: number;
  added: number;
  size: number;
  channels: string[];
}

export interface DbcOverview {
  files: DbcFileSummary[];
  assignments: Record<string, string[]>;
  channels: { name: string; connected: boolean }[];
  conflicts: Record<string, string[]>;
}

export interface LiveMessage {
  message: string;
  dbc: string;
  id: number;
  id_hex: string;
  extended: boolean;
  signals: Record<string, number | string | null>;
  units: Record<string, string>;
  data: string;
  ts: number;
  age_s: number;
  count: number;
  dir: string;
  period_ms: number | null;
}

/**
 * DBC-Bytes in Text wandeln: UTF-8, falls gültig, sonst Windows-1252 (Standard vieler DBC-Werkzeuge),
 * damit Umlaute in Kommentaren und Werte-Tabellen erhalten bleiben.
 */
export function decodeDbcBytes(bytes: Uint8Array): string {
  const start = bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf ? 3 : 0;
  const body = bytes.subarray(start);
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(body);
  } catch {
    return new TextDecoder("windows-1252").decode(body);
  }
}

/** Anzeige eines Signalwerts mit Einheit (Gleitkomma ohne Rauschen). */
export function formatSignal(value: number | string | null | undefined, unit?: string): string {
  if (value === null || value === undefined) return "–";
  const v =
    typeof value === "number" && !Number.isInteger(value)
      ? String(Number(value.toPrecision(10)))
      : String(value);
  return unit ? `${v} ${unit}` : v;
}

/** CAN-ID-Anzeige: 3 Stellen (11 Bit) bzw. 8 Stellen (29 Bit). */
export function formatCanId(id: number, extended: boolean): string {
  return `0x${id
    .toString(16)
    .toUpperCase()
    .padStart(extended ? 8 : 3, "0")}`;
}

/** Kurzbeschreibung der Bitlage: „Bit 0–15, Intel, unsigned“. */
export function signalLayout(s: DbcSignal): string {
  const order = s.byte_order === "little_endian" ? "Intel" : "Motorola";
  const kind = s.float ? "float" : s.signed ? "signed" : "unsigned";
  return `Start ${s.start}, ${s.length} Bit, ${order}, ${kind}`;
}

/** Gilt das Signal beim gegebenen Multiplexer-Wert? (Signale ohne Bindung immer.) */
export function signalActive(s: DbcSignal, muxValue: number | null): boolean {
  if (!s.multiplexer_ids || s.multiplexer_ids.length === 0) return true;
  return muxValue !== null && s.multiplexer_ids.includes(muxValue);
}

/**
 * Formularwert → Signalwert für /dbc/encode: Choice-Name bleibt Text, sonst Zahl.
 * Gibt null für leere Eingaben zurück (Signal bekommt dann seinen Startwert).
 */
export function parseSignalInput(raw: string, s: DbcSignal): number | string | null {
  const v = raw.trim();
  if (!v) return null;
  if (s.choices && Object.values(s.choices).includes(v)) return v;
  const n = Number(v.replace(",", "."));
  if (Number.isNaN(n)) throw new Error(`${s.name}: „${v}“ ist keine Zahl`);
  return n;
}

/** Live-Botschaften nach Text filtern (Name, ID, Signalnamen). */
export function filterLive(items: LiveMessage[], needle: string): LiveMessage[] {
  const n = needle.trim().toLowerCase();
  if (!n) return items;
  return items.filter(
    (m) =>
      m.message.toLowerCase().includes(n) ||
      m.id_hex.toLowerCase().includes(n.replace(/^0x/, "")) ||
      Object.keys(m.signals).some((k) => k.toLowerCase().includes(n)),
  );
}
