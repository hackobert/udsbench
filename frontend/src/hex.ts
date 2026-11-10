/**
 * Hex-Hilfsfunktionen (reine Darstellung/Eingabe – keine Protokolllogik).
 */

export class HexError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HexError";
  }
}

/** Entfernt 0x-Präfixe, Trennzeichen (Leerzeichen, Komma, Doppelpunkt, Bindestrich) und prüft auf Hex-Ziffern. */
export function normalizeHex(input: string): string {
  const cleaned = input
    .trim()
    .replace(/0x/gi, "")
    .replace(/[\s,:;_-]+/g, "");
  if (cleaned === "") return "";
  if (!/^[0-9a-fA-F]+$/.test(cleaned)) {
    const bad = cleaned.match(/[^0-9a-fA-F]/)?.[0] ?? "?";
    throw new HexError(`Ungültiges Hex-Zeichen '${bad}'`);
  }
  if (cleaned.length % 2 !== 0) throw new HexError("Ungerade Anzahl Hex-Ziffern");
  return cleaned.toUpperCase();
}

/** "22 f1 00" | "22F100" | "0x22,0xF1,0x00" → [0x22, 0xF1, 0x00] */
export function parseHex(input: string): number[] {
  const s = normalizeHex(input);
  const out: number[] = [];
  for (let i = 0; i < s.length; i += 2) out.push(parseInt(s.slice(i, i + 2), 16));
  return out;
}

/** Prüft Hex ohne Exception; leere Eingabe gilt als gültig (wenn allowEmpty). */
export function isValidHex(input: string, allowEmpty = true): boolean {
  try {
    const s = normalizeHex(input);
    return allowEmpty || s.length > 0;
  } catch {
    return false;
  }
}

/** Formatiert Bytes als "22 F1 00". */
export function formatHex(bytes: ArrayLike<number>, sep = " "): string {
  const parts: string[] = [];
  for (let i = 0; i < bytes.length; i++) parts.push(byteHex(bytes[i] ?? 0));
  return parts.join(sep);
}

/** Normalisiert eine Hex-Eingabe in die kanonische Schreibweise "22 F1 00"; ungültig → unverändert. */
export function prettyHex(input: string): string {
  try {
    return formatHex(parseHex(input));
  } catch {
    return input;
  }
}

export function byteHex(n: number): string {
  return (n & 0xff).toString(16).toUpperCase().padStart(2, "0");
}

/** Zahl → Hex mit fester Breite (in Bytes), z. B. (0xF100, 2) → "F1 00". */
export function intToHexBytes(value: number, byteLength: number): string {
  if (!Number.isInteger(value) || value < 0) throw new HexError("Wert muss eine nichtnegative Ganzzahl sein");
  const max = 2 ** (8 * byteLength);
  if (value >= max)
    throw new HexError(`Wert 0x${value.toString(16).toUpperCase()} passt nicht in ${byteLength} Byte`);
  const out: number[] = [];
  for (let i = byteLength - 1; i >= 0; i--) out.push(Math.floor(value / 2 ** (8 * i)) & 0xff);
  return formatHex(out);
}

/**
 * Ganzzahl lesen: "0x7E0", "7E0h", "0b101", "123". Mit defaultHex=true wird eine Eingabe ohne Präfix
 * als Hex interpretiert (z. B. für CAN-IDs).
 */
export function parseIntLoose(input: string | number, defaultHex = false): number {
  if (typeof input === "number") {
    if (!Number.isFinite(input)) throw new HexError("Ungültige Zahl");
    return input;
  }
  const s = input.trim();
  if (s === "") throw new HexError("Leerer Wert");
  let v: number;
  if (/^0x[0-9a-f]+$/i.test(s)) v = parseInt(s.slice(2), 16);
  else if (/^[0-9a-f]+h$/i.test(s)) v = parseInt(s.slice(0, -1), 16);
  else if (/^0b[01]+$/i.test(s)) v = parseInt(s.slice(2), 2);
  else if (defaultHex && /^[0-9a-f]+$/i.test(s)) v = parseInt(s, 16);
  else if (/^-?\d+$/.test(s)) v = parseInt(s, 10);
  else throw new HexError(`Ungültige Zahl '${s}'`);
  return v;
}

/** Zahl → "0x7E0" (mindestens `width` Hex-Ziffern). */
export function toHexId(value: number | null | undefined, width = 3): string {
  if (value === null || value === undefined) return "";
  return "0x" + value.toString(16).toUpperCase().padStart(width, "0");
}

/** Darstellbare ASCII-Zeichen, Rest als Punkt (nur Anzeige). */
export function bytesToAscii(hex: string): string {
  try {
    return parseHex(hex)
      .map((b) => (b >= 0x20 && b < 0x7f ? String.fromCharCode(b) : "."))
      .join("");
  } catch {
    return "";
  }
}

/** Anzeige eines STmin-Rohwerts (nur Darstellung): 0x00–0x7F ms, 0xF1–0xF9 = 100–900 µs, sonst reserviert. */
export function stminText(raw: number): string {
  if (raw >= 0 && raw <= 0x7f) return `${raw} ms`;
  if (raw >= 0xf1 && raw <= 0xf9) return `${(raw - 0xf0) * 100} µs`;
  return "reserviert (→ 127 ms)";
}
