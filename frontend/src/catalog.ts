/** Katalog-Hilfen für Dropdowns und die Parameter-Eingabe (Eingabehilfe – Validierung macht das Backend). */
import { h } from "./dom";
import { byteHex, formatHex, HexError, intToHexBytes, parseHex, parseIntLoose } from "./hex";
import type { DidDef, RoutineDef, ServiceParam, UdsService } from "./types";

export interface Opt {
  value: string;
  label: string;
}

export function serviceOptions(services: UdsService[]): Opt[] {
  return services.map((s) => ({ value: String(s.sid), label: `${s.sid_hex.replace("0x", "")} ${s.name}` }));
}

export function subfunctionOptions(service: UdsService | null | undefined): Opt[] {
  if (!service || !service.has_subfunction) return [];
  return service.subfunctions.map((sf) => ({
    value: String(sf.value),
    label: `${sf.hex.replace("0x", "")} ${sf.name}`,
  }));
}

export interface DidFilter {
  access?: "read" | "write";
  ioControl?: boolean;
}

export function didOptions(dids: DidDef[], filter: DidFilter = {}): Opt[] {
  return dids
    .filter((d) => {
      if (filter.access === "read" && !d.access.includes("read")) return false;
      if (filter.access === "write" && !d.access.includes("write")) return false;
      if (filter.ioControl && !d.io_control) return false;
      return true;
    })
    .map((d) => ({
      value: d.id_hex,
      label: `${d.id_hex.replace("0x", "")} ${d.name}${d.unit ? ` [${d.unit}]` : ""}`,
    }));
}

export function routineOptions(routines: RoutineDef[]): Opt[] {
  return routines.map((r) => ({ value: r.id_hex, label: `${r.id_hex.replace("0x", "")} ${r.name}` }));
}

/** <select> mit Optionen füllen; liefert das Element zurück. */
export function fillSelect(
  sel: HTMLSelectElement,
  opts: Opt[],
  selected?: string | null,
  placeholder?: string,
): HTMLSelectElement {
  sel.replaceChildren();
  if (placeholder !== undefined) sel.appendChild(h("option", { value: "" }, placeholder));
  for (const o of opts) {
    const el = h("option", { value: o.value }, o.label);
    if (selected !== undefined && selected !== null && o.value === selected) el.selected = true;
    sel.appendChild(el);
  }
  return sel;
}

/** Parameterliste eines Service; Subfunktions-spezifische Parameter (sub_params["0x02"]) haben Vorrang. */
export function paramsFor(service: UdsService | null | undefined, sub?: number | null): ServiceParam[] {
  if (!service) return [];
  if (sub !== undefined && sub !== null) {
    const key = `0x${byteHex(sub & 0x7f)}`;
    const sp = service.sub_params[key];
    if (sp) return sp;
  }
  return service.params;
}

/** Feste Bytelänge eines Parametertyps (null = variabel/hex). */
export function paramByteLength(kind: string): number | null {
  switch (kind) {
    case "byte":
    case "mask":
    case "alfid":
      return 1;
    case "did":
    case "rid":
    case "u16":
      return 2;
    case "u24":
    case "dtc":
      return 3;
    case "u32":
      return 4;
    default:
      return null;
  }
}

/** Ein Parameterwert → Hex-Bytes. Zahlenparameter als Hex (mit/ohne 0x) oder Dezimal mit "d"-Suffix. */
export function encodeParam(kind: string, raw: string): string {
  const v = raw.trim();
  if (v === "") return "";
  const len = paramByteLength(kind);
  if (len === null) return formatHex(parseHex(v));
  // Bereits als Bytefolge passender Länge geschrieben ("F1 00")?
  if (/\s/.test(v)) {
    const bytes = parseHex(v);
    if (bytes.length !== len) throw new HexError(`Parameter erwartet ${len} Byte`);
    return formatHex(bytes);
  }
  const num = /^\d+d$/i.test(v) ? parseInt(v.slice(0, -1), 10) : parseIntLoose(v, true);
  return intToHexBytes(num, len);
}

export interface PayloadSpec {
  service: UdsService;
  sub?: number | null;
  sprm?: boolean;
  params: Record<string, string>;
}

/** Nutzlast aus Service, Subfunktion und Parametern zusammensetzen (Eingabehilfe). */
export function buildPayload(spec: PayloadSpec): string {
  const parts: string[] = [byteHex(spec.service.sid)];
  if (spec.service.has_subfunction && spec.sub !== undefined && spec.sub !== null) {
    const sprm = spec.sprm && spec.service.sprm_allowed ? 0x80 : 0;
    parts.push(byteHex((spec.sub & 0x7f) | sprm));
  }
  for (const p of paramsFor(spec.service, spec.sub)) {
    const raw = spec.params[p.name] ?? "";
    if (raw.trim() === "") {
      if (!p.optional && p.default) parts.push(encodeParam(p.kind, p.default));
      continue;
    }
    parts.push(encodeParam(p.kind, raw));
  }
  return parts.filter(Boolean).join(" ");
}

/** Statusbyte → Liste gesetzter Bits (Namen aus /uds/services dtc_status_bits). */
export function statusBitsFromMask(mask: number, bitNames: string[]): string[] {
  return bitNames.filter((_, i) => (mask >> i) & 1);
}
