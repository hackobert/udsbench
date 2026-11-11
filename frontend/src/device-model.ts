/**
 * Gerätemodell für Einrichtungsassistent und Geräteverwaltung (ohne DOM, testbar).
 *
 * Ein „Gerät“ ist eine ECU-Definition mit eingebettetem ISO-TP-Profil im Arbeitsbereich-Paket.
 */
import type { UdsResult } from "./types";

export type Addressing = "normal" | "extended" | "mixed";
export type PresetId = "std11" | "fixed29" | "custom";

export interface DeviceForm {
  id: string;
  name: string;
  description: string;
  preset: PresetId;
  channel: string;
  tx_id: string;
  rx_id: string;
  functional_id: string;
  extended_id: boolean;
  /** Nur Vorlage „29-Bit normal fixed“: Zieladresse des Geräts und Tester-Adresse. */
  target_address: string;
  tester_address: string;
  addressing: Addressing;
  tx_ae: string;
  rx_ae: string;
  padding: boolean;
  padding_byte: string;
  dlc_mode: "fixed" | "minimal";
  can_fd: boolean;
  p2_ms: string;
  p2_star_ms: string;
}

export const DEFAULT_DEVICE: DeviceForm = {
  id: "",
  name: "",
  description: "",
  preset: "std11",
  channel: "default",
  tx_id: "7E0",
  rx_id: "7E8",
  functional_id: "7DF",
  extended_id: false,
  target_address: "10",
  tester_address: "F1",
  addressing: "normal",
  tx_ae: "",
  rx_ae: "",
  padding: true,
  padding_byte: "CC",
  dlc_mode: "fixed",
  can_fd: false,
  p2_ms: "",
  p2_star_ms: "",
};

/** Hex-Eingabe („7E0“, „0x7E0“, „18 DA 10 F1“) → Zahl; null bei ungültiger Eingabe. */
export function parseId(input: string): number | null {
  const s = input.trim().replace(/^0x/i, "").replace(/[\s_]/g, "");
  if (!s || !/^[0-9a-f]+$/i.test(s) || s.length > 8) return null;
  return parseInt(s, 16);
}

export function hex(n: number, width = 3): string {
  return n.toString(16).toUpperCase().padStart(width, "0");
}

/** Name → gültige Geräte-ID (Kleinbuchstaben, Ziffern, Unterstrich). */
export function slugify(name: string): string {
  const map: Record<string, string> = { ä: "ae", ö: "oe", ü: "ue", ß: "ss" };
  const s = name
    .toLowerCase()
    .replace(/[äöüß]/g, (c) => map[c] ?? c)
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return s.slice(0, 40);
}

/** 29-Bit „normal fixed“ (ISO 15765-2): 0x18DA<TA><SA> physikalisch, 0x18DB33<SA> funktional. */
export function normalFixedIds(target: number, tester: number): { tx: number; rx: number; func: number } {
  return {
    tx: (0x18da0000 | (target << 8) | tester) >>> 0,
    rx: (0x18da0000 | (tester << 8) | target) >>> 0,
    func: (0x18db3300 | tester) >>> 0,
  };
}

/** Vorlage anwenden; liefert die geänderten Felder. */
export function applyPreset(form: DeviceForm, preset: PresetId): DeviceForm {
  const f = { ...form, preset };
  if (preset === "std11") {
    Object.assign(f, {
      extended_id: false,
      addressing: "normal",
      tx_id: "7E0",
      rx_id: "7E8",
      functional_id: "7DF",
    });
  } else if (preset === "fixed29") {
    Object.assign(f, { extended_id: true, addressing: "normal" });
    syncFixed29(f);
  }
  return f;
}

/** Bei Vorlage „29-Bit normal fixed“ die IDs aus den Adressen ableiten. */
export function syncFixed29(f: DeviceForm): void {
  const ta = parseId(f.target_address);
  const sa = parseId(f.tester_address);
  if (ta === null || sa === null || ta > 0xff || sa > 0xff) return;
  const ids = normalFixedIds(ta, sa);
  f.tx_id = hex(ids.tx, 8);
  f.rx_id = hex(ids.rx, 8);
  f.functional_id = hex(ids.func, 8);
}

export interface Problem {
  field: keyof DeviceForm;
  msg: string;
}

/** Eingaben prüfen (Meldungen auf Deutsch; die Oberfläche zeigt sie am Feld). */
export function validateDevice(f: DeviceForm, takenIds: string[] = []): Problem[] {
  const out: Problem[] = [];
  if (!f.name.trim()) out.push({ field: "name", msg: "Bitte einen Namen eingeben." });
  if (!/^[A-Za-z0-9_.-]+$/.test(f.id))
    out.push({ field: "id", msg: "Nur Buchstaben, Ziffern, Punkt, Binde- und Unterstrich." });
  else if (takenIds.includes(f.id)) out.push({ field: "id", msg: `Die ID „${f.id}“ ist schon vergeben.` });
  const limit = f.extended_id ? 0x1fffffff : 0x7ff;
  const bits = f.extended_id ? "29" : "11";
  const checkId = (key: "tx_id" | "rx_id" | "functional_id", optional: boolean) => {
    const raw = f[key].trim();
    if (!raw && optional) return;
    const v = parseId(raw);
    if (v === null) out.push({ field: key, msg: "Bitte eine Hex-Zahl eingeben, z. B. 7E0." });
    else if (v > limit)
      out.push({ field: key, msg: `0x${hex(v)} ist zu groß für ${bits}-Bit-IDs (max. 0x${hex(limit)}).` });
  };
  checkId("tx_id", false);
  checkId("rx_id", false);
  checkId("functional_id", true);
  if (!out.some((p) => p.field === "tx_id" || p.field === "rx_id") && parseId(f.tx_id) === parseId(f.rx_id))
    out.push({ field: "rx_id", msg: "Anfrage- und Antwort-ID müssen sich unterscheiden." });
  const byte = (key: "tx_ae" | "rx_ae" | "padding_byte", required: boolean) => {
    const raw = f[key].trim();
    if (!raw && !required) return;
    const v = parseId(raw);
    if (v === null || v > 0xff) out.push({ field: key, msg: "Ein Byte als Hex, z. B. F1." });
  };
  if (f.addressing !== "normal") {
    byte("tx_ae", true);
    byte("rx_ae", false);
  }
  if (f.padding) byte("padding_byte", true);
  for (const key of ["p2_ms", "p2_star_ms"] as const) {
    const raw = f[key].trim();
    if (raw && !(Number(raw) > 0)) out.push({ field: key, msg: "Bitte eine Zahl in Millisekunden." });
  }
  return out;
}

/** Formular → Gerätedefinition für POST/PUT /devices. */
export function formToDevice(f: DeviceForm): Record<string, unknown> {
  const num = (s: string) => parseId(s);
  const isotp: Record<string, unknown> = {
    channel: f.channel || "default",
    tx_id: num(f.tx_id),
    rx_id: num(f.rx_id),
    extended_id: f.extended_id,
    addressing: f.addressing,
    padding: f.padding ? { enabled: true, byte: num(f.padding_byte) ?? 0xcc } : { enabled: false },
    dlc_mode: f.dlc_mode,
    can_fd: f.can_fd,
  };
  if (f.functional_id.trim()) isotp["functional_id"] = num(f.functional_id);
  if (f.addressing !== "normal") {
    isotp["tx_address_extension"] = num(f.tx_ae);
    if (f.rx_ae.trim()) isotp["rx_address_extension"] = num(f.rx_ae);
  }
  const dev: Record<string, unknown> = {
    id: f.id,
    name: f.name.trim(),
    description: f.description.trim(),
    isotp,
  };
  const timing: Record<string, number> = {};
  if (f.p2_ms.trim()) timing["p2_ms"] = Number(f.p2_ms);
  if (f.p2_star_ms.trim()) timing["p2_star_ms"] = Number(f.p2_star_ms);
  if (Object.keys(timing).length) dev["timing"] = timing;
  return dev;
}

interface ProfileLike {
  channel?: string;
  tx_id: number;
  rx_id: number;
  functional_id?: number | null;
  extended_id?: boolean;
  addressing?: Addressing;
  tx_address_extension?: number | null;
  rx_address_extension?: number | null;
  padding?: { enabled: boolean; byte?: number };
  dlc_mode?: "fixed" | "minimal";
  can_fd?: boolean;
}

export interface DeviceInfo {
  id: string;
  name: string;
  description: string;
  package: string;
  editable: boolean;
  demo: boolean;
  connected: boolean;
  profile: ProfileLike;
  definition: { timing?: { p2_ms?: number; p2_star_ms?: number } } & Record<string, unknown>;
}

/** Gespeichertes Gerät → Formular (zum Bearbeiten). */
export function deviceToForm(d: DeviceInfo): DeviceForm {
  const p = d.profile;
  const w = p.extended_id ? 8 : 3;
  const f: DeviceForm = {
    ...DEFAULT_DEVICE,
    id: d.id,
    name: d.name || d.id,
    description: d.description ?? "",
    preset: "custom",
    channel: p.channel ?? "default",
    tx_id: hex(p.tx_id, w),
    rx_id: hex(p.rx_id, w),
    functional_id: p.functional_id == null ? "" : hex(p.functional_id, w),
    extended_id: !!p.extended_id,
    addressing: p.addressing ?? "normal",
    tx_ae: p.tx_address_extension == null ? "" : hex(p.tx_address_extension, 2),
    rx_ae: p.rx_address_extension == null ? "" : hex(p.rx_address_extension, 2),
    padding: p.padding?.enabled ?? true,
    padding_byte: hex(p.padding?.byte ?? 0xcc, 2),
    dlc_mode: p.dlc_mode ?? "fixed",
    can_fd: !!p.can_fd,
    p2_ms: d.definition.timing?.p2_ms != null ? String(d.definition.timing.p2_ms) : "",
    p2_star_ms: d.definition.timing?.p2_star_ms != null ? String(d.definition.timing.p2_star_ms) : "",
  };
  if (!f.extended_id && f.tx_id === "7E0" && f.rx_id === "7E8") f.preset = "std11";
  return f;
}

/** Kurzbeschreibung der Adressierung für Tabellen. */
export function describeIds(p: ProfileLike): string {
  const w = p.extended_id ? 8 : 3;
  let s = `0x${hex(p.tx_id, w)} → 0x${hex(p.rx_id, w)}`;
  if (p.addressing && p.addressing !== "normal" && p.tx_address_extension != null)
    s += ` · ${p.addressing} 0x${hex(p.tx_address_extension, 2)}`;
  return s;
}

// --- Diagnose des Kommunikationstests ---------------------------------------------------------

export interface BusActivity {
  frames: number;
  error_frames: number;
  ids: { id: number; id_hex: string; ext: boolean; count: number; data?: string }[];
}

export interface Diagnosis {
  level: "ok" | "warn" | "fail";
  title: string;
  text: string[];
  /** Auf dem Bus gesehene IDs, die als Antwort-ID in Frage kommen. */
  candidates: { id: number; ext: boolean; count: number }[];
}

/** Ergebnis von „3E 00“ plus mitgehörter Busverkehr → verständliche Einschätzung. */
export function diagnose(
  res: UdsResult | null,
  activity: BusActivity | null,
  dev: { tx_id: number; rx_id: number; extended_id: boolean },
): Diagnosis {
  const w = dev.extended_id ? 8 : 3;
  const others = (activity?.ids ?? []).filter((i) => !(i.id === dev.tx_id && i.ext === dev.extended_id));
  const candidates = others
    .filter((i) => !(i.id === dev.rx_id && i.ext === dev.extended_id))
    .map((i) => ({ id: i.id, ext: i.ext, count: i.count }));
  if (res?.positive) {
    return {
      level: "ok",
      title: "Das Gerät antwortet – die Kommunikation funktioniert.",
      text: [`Antwort in ${res.elapsed_ms?.toFixed(1) ?? "?"} ms auf 0x${hex(dev.rx_id, w)}.`],
      candidates: [],
    };
  }
  if (res?.negative) {
    return {
      level: "ok",
      title: "Das Gerät antwortet – die Kommunikation funktioniert.",
      text: [
        `Es lehnt die Testanfrage ab (${res.nrc_name ?? "NRC"} 0x${hex(res.nrc ?? 0, 2)}). ` +
          "Das ist für den Verbindungstest in Ordnung: IDs, Bitrate und Adressierung stimmen.",
      ],
      candidates: [],
    };
  }
  if (res && res.error_kind && res.error_kind !== "timeout") {
    return {
      level: "fail",
      title: "Die Anfrage konnte nicht gesendet werden.",
      text: [res.error ?? ""],
      candidates,
    };
  }
  // Timeout
  const text: string[] = [];
  let title = "Keine Antwort vom Gerät.";
  if (!activity) {
    text.push("Der Busverkehr konnte nicht ausgewertet werden.");
  } else if (activity.error_frames > 0 && activity.frames === 0) {
    title = "Keine Antwort – der Adapter meldet Fehlerframes.";
    text.push(
      "Fehlerframes deuten fast immer auf eine falsche Bitrate hin. Prüfen Sie die Bitrate im Schritt " +
        "„CAN-Adapter“ (häufig 500 000 oder 250 000 Bit/s) und den Abschlusswiderstand (120 Ω).",
    );
  } else if (activity.frames === 0) {
    title = "Keine Antwort – auf dem Bus ist nichts zu hören.";
    text.push(
      "Der Adapter hat während des Tests keinen einzigen Frame empfangen. Prüfen Sie: Ist das Gerät " +
        "eingeschaltet (Zündung/Klemme 15)? Sind CAN-High und CAN-Low richtig angeschlossen? Ist der Bus " +
        "mit 120 Ω abgeschlossen? Stimmt die Bitrate?",
    );
  } else if (others.some((i) => i.id === dev.rx_id && i.ext === dev.extended_id)) {
    title = "Auf der Antwort-ID kommen Daten, aber keine gültige Antwort.";
    text.push(
      `Auf 0x${hex(dev.rx_id, w)} sind Frames zu sehen. Vermutlich passt die Adressierung (normal / ` +
        "extended mit Adressbyte) oder das Padding nicht. Vergleichen Sie im Trace die Frames mit der " +
        "Gerätedokumentation.",
    );
  } else {
    title = "Keine Antwort – der Bus ist aktiv, aber nicht auf der erwarteten Antwort-ID.";
    text.push(
      `Erwartet wurde eine Antwort auf 0x${hex(dev.rx_id, w)}. Prüfen Sie Anfrage- und Antwort-ID und ` +
        "11/29-Bit. Falls eine der unten gezeigten IDs die Antwort ist, können Sie sie direkt übernehmen.",
    );
  }
  text.push(
    "Manche Geräte antworten nur in bestimmten Betriebszuständen oder erst nach einem Weck-Signal – " +
      "die Gerätedokumentation hilft hier weiter.",
  );
  return { level: activity && activity.frames > 0 ? "warn" : "fail", title, text, candidates };
}
