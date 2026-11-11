/** Trace-Zeilen: Einfärbung und Formatierung (Klassifizierung liefert das Backend). */
import { asciiOf } from "./hex";
import type { TraceItem } from "./types";

export type TraceView = "frames" | "messages";

/** Semantische CSS-Klasse einer Trace-Zeile. */
export function traceRowClass(item: TraceItem): string {
  const classes: string[] = [`dir-${item.dir}`];
  if (item.kind === "frame") {
    if (item.err) return [...classes, "t-err"].join(" ");
    const pci = (item.pci ?? "").toUpperCase();
    if (pci === "FC") classes.push("t-fc");
    else if (pci === "FF") classes.push("t-ff");
    else if (pci === "CF") classes.push("t-cf");
    const u = udsClass(item.uds);
    if (u) classes.push(u);
    if (!pci && !u) classes.push("t-other");
  } else {
    const u = udsClass(item.uds);
    classes.push(u ?? "t-other");
    if (item.frames > 1) classes.push("t-multi");
  }
  return classes.join(" ");
}

function udsClass(uds: string | null | undefined): string | null {
  switch (uds) {
    case "request":
      return "t-req";
    case "positive":
      return "t-pos";
    case "negative":
      return "t-neg";
    case "segmented":
      return "t-seg";
    default:
      return null;
  }
}

/** Relative Zeit in Sekunden mit 3 Nachkommastellen. */
export function relTime(ts: number, t0: number): string {
  const d = ts - t0;
  return (d < 0 ? 0 : d).toFixed(3);
}

export interface TraceRowCells {
  time: string;
  channel: string;
  dir: string;
  id: string;
  dlc: string;
  data: string;
  ascii: string;
  text: string;
}

export const TRACE_COLUMNS: (keyof TraceRowCells)[] = [
  "time",
  "channel",
  "dir",
  "id",
  "dlc",
  "data",
  "ascii",
  "text",
];

export function traceCells(item: TraceItem, t0: number): TraceRowCells {
  if (item.kind === "frame") {
    return {
      time: relTime(item.ts, t0),
      channel: item.channel,
      dir: item.dir.toUpperCase(),
      id: item.id_hex + (item.ext ? "x" : ""),
      dlc: String(item.dlc),
      data: item.data,
      ascii: asciiOf(item.data),
      text: [item.pci, item.text].filter(Boolean).join("  "),
    };
  }
  const id = item.can_id ?? item.id;
  return {
    time: relTime(item.ts, t0),
    channel: item.channel,
    dir: item.dir.toUpperCase(),
    id: id !== undefined ? id.toString(16).toUpperCase() : "",
    dlc: String(item.len),
    data: item.payload,
    ascii: asciiOf(item.payload),
    text: (item.text ?? "") + (item.frames > 1 ? `  (${item.frames} Frames)` : ""),
  };
}

/** Lokale Volltextsuche über die angezeigten Zellen. */
export function matchesSearch(item: TraceItem, needle: string): boolean {
  if (!needle) return true;
  const n = needle.toLowerCase();
  const c = traceCells(item, item.ts);
  return [c.id, c.data, c.text, c.ascii, item.ecu ?? ""].some((s) => s.toLowerCase().includes(n));
}

export interface TraceFilterState {
  ids: string;
  data_contains: string;
  direction: "" | "tx" | "rx";
  services: string;
  only_uds: boolean;
}

/** Filterzustand → WS-Filterobjekt; IDs ohne Präfix gelten als Hex. */
export function toWsFilter(f: TraceFilterState): Record<string, unknown> {
  const hexList = (s: string) =>
    s
      .split(/[\s,;]+/)
      .map((x) => x.trim())
      .filter(Boolean)
      .map((x) => (/^0x/i.test(x) ? x : `0x${x}`));
  const out: Record<string, unknown> = {};
  const ids = hexList(f.ids);
  if (ids.length) out["ids"] = ids;
  const sv = hexList(f.services);
  if (sv.length) out["services"] = sv;
  if (f.direction) out["direction"] = f.direction;
  if (f.data_contains.trim()) out["data_contains"] = f.data_contains.trim();
  if (f.only_uds) out["only_uds"] = true;
  return out;
}
