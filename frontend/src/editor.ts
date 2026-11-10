/** JSON-Editor-Helfer für Botschaften, Sequenzen und Tests (Parsen, Positionsangabe, Fehleranzeige). */
import { ApiError, formatErrorDetails } from "./api";
import { h } from "./dom";

export type ParseResult<T = unknown> =
  { ok: true; value: T } | { ok: false; message: string; line: number | null; column: number | null };

/** Offset im Text → Zeile/Spalte (1-basiert). */
export function offsetToLineCol(text: string, offset: number): { line: number; column: number } {
  const before = text.slice(0, Math.max(0, Math.min(offset, text.length)));
  const lines = before.split("\n");
  return { line: lines.length, column: (lines[lines.length - 1]?.length ?? 0) + 1 };
}

/**
 * Fehlerposition aus neueren V8-Meldungen ableiten, die nur einen Textausschnitt enthalten
 * (z. B. `Unexpected token ',', ..."ps": [,]\n}" is not valid JSON`).
 */
export function guessErrorOffset(text: string, msg: string): number | null {
  if (/end of JSON input/i.test(msg)) return text.length;
  const m = /Unexpected token '(.)', (\.\.\.)?"([\s\S]*?)"(\.\.\.)? is not valid JSON/.exec(msg);
  if (!m) return null;
  const token = m[1] ?? "";
  const snippet = m[3] ?? "";
  const at = text.indexOf(snippet);
  if (at < 0) return null;
  // V8 zeigt bei gekürztem Anfang ca. 10 Zeichen Kontext vor dem Fehler
  const center = m[2] ? 10 : 0;
  let best = -1;
  for (let i = snippet.indexOf(token); i >= 0; i = snippet.indexOf(token, i + 1)) {
    if (best < 0 || Math.abs(i - center) < Math.abs(best - center)) best = i;
  }
  return best < 0 ? at : at + best;
}

/** JSON parsen; bei Fehlern Zeile/Spalte aus der Engine-Meldung ermitteln. */
export function parseJson<T = unknown>(text: string): ParseResult<T> {
  if (!text.trim()) return { ok: false, message: "Leere Eingabe", line: 1, column: 1 };
  try {
    return { ok: true, value: JSON.parse(text) as T };
  } catch (exc) {
    const msg = (exc as Error).message;
    let line: number | null = null;
    let column: number | null = null;
    const lc = /line (\d+) column (\d+)/i.exec(msg);
    const pos = /position (\d+)/i.exec(msg);
    if (lc) {
      line = Number(lc[1]);
      column = Number(lc[2]);
    } else if (pos) {
      const r = offsetToLineCol(text, Number(pos[1]));
      line = r.line;
      column = r.column;
    } else {
      const off = guessErrorOffset(text, msg);
      if (off !== null) {
        const r = offsetToLineCol(text, off);
        line = r.line;
        column = r.column;
      }
    }
    return { ok: false, message: msg, line, column };
  }
}

/** Objekt muss ein JSON-Objekt mit "id" sein (Botschaft/Sequenz/Test). */
export function parseLibraryItem(text: string): ParseResult<Record<string, unknown>> {
  const r = parseJson<unknown>(text);
  if (!r.ok) return r;
  const v = r.value;
  if (v === null || typeof v !== "object" || Array.isArray(v)) {
    return { ok: false, message: "Erwartet wird ein JSON-Objekt { … }", line: 1, column: 1 };
  }
  const obj = v as Record<string, unknown>;
  if (typeof obj["id"] !== "string" || !obj["id"]) {
    return { ok: false, message: 'Feld "id" (Text) fehlt', line: null, column: null };
  }
  return { ok: true, value: obj };
}

/** Objekt für den Editor aufbereiten: Felder, die die API nur liefert (package), entfernen. */
export function toEditorText(item: Record<string, unknown>): string {
  const copy: Record<string, unknown> = { ...item };
  delete copy["package"];
  return JSON.stringify(copy, null, 2);
}

/** Fehlerliste für Editor-Fehler (lokales Parsen oder API-Validierung). */
export function editorErrorLines(err: ParseResult | ApiError | Error | null): string[] {
  if (!err) return [];
  if (err instanceof ApiError) return [err.message, ...formatErrorDetails(err.details)];
  if (err instanceof Error) return [err.message];
  if (err.ok) return [];
  const pos =
    err.line !== null ? ` (Zeile ${err.line}${err.column !== null ? `, Spalte ${err.column}` : ""})` : "";
  return [`${err.message}${pos}`];
}

export function renderEditorErrors(err: ParseResult | ApiError | Error | null): HTMLElement | null {
  const lines = editorErrorLines(err);
  if (!lines.length) return null;
  return h(
    "ul",
    { class: "editor-errors" },
    lines.map((l) => h("li", null, l)),
  );
}
