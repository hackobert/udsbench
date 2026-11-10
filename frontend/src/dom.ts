/** Minimale DOM-Helfer (kein Framework). */

export type Child = Node | string | number | null | undefined | false | Child[];

type Handler = (ev: Event) => void;

export interface Attrs {
  class?: string | (string | false | null | undefined)[];
  style?: string | Partial<Record<string, string>>;
  dataset?: Record<string, string>;
  [key: string]: unknown;
}

const PROP_KEYS = new Set([
  "value",
  "checked",
  "disabled",
  "selected",
  "indeterminate",
  "readOnly",
  "multiple",
]);

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs?: Attrs | null,
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (attrs) applyAttrs(el, attrs);
  append(el, ...children);
  return el;
}

export function applyAttrs(el: HTMLElement, attrs: Attrs): void {
  for (const [key, val] of Object.entries(attrs)) {
    if (val === undefined || val === null || val === false) {
      if (PROP_KEYS.has(key) && val === false) (el as unknown as Record<string, unknown>)[key] = false;
      continue;
    }
    if (key === "class") {
      const cls = Array.isArray(val) ? val.filter(Boolean).join(" ") : String(val);
      if (cls) el.className = cls;
    } else if (key === "style") {
      if (typeof val === "string") el.setAttribute("style", val);
      else Object.assign(el.style, val);
    } else if (key === "dataset") {
      Object.assign(el.dataset, val as Record<string, string>);
    } else if (key.startsWith("on") && typeof val === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), val as Handler);
    } else if (PROP_KEYS.has(key)) {
      (el as unknown as Record<string, unknown>)[key] = val;
    } else if (val === true) {
      el.setAttribute(key, "");
    } else {
      el.setAttribute(key, String(val));
    }
  }
}

export function append(parent: Node, ...children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(parent, ...c);
    else if (c instanceof Node) parent.appendChild(c);
    else parent.appendChild(document.createTextNode(String(c)));
  }
}

/** Inhalt ersetzen. */
export function replace(parent: Element, ...children: Child[]): void {
  parent.replaceChildren();
  append(parent, ...children);
}

export function clear(el: Element): void {
  el.replaceChildren();
}

export function option(value: string, label: string, selected = false): HTMLOptionElement {
  const o = h("option", { value }, label);
  if (selected) o.selected = true;
  return o;
}

export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number): (...args: A) => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (...args: A) => {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

/** Fokus liegt in einem Eingabefeld? */
export function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (target as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "submit", "reset", "range", "color", "file"].includes(type);
  }
  return false;
}

/** Datei als Text lesen. */
export function readFileText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result ?? ""));
    r.onerror = () => reject(r.error ?? new Error("Datei konnte nicht gelesen werden"));
    r.readAsText(file);
  });
}

/** Text als Datei herunterladen. */
export function saveText(text: string, filename: string, mime = "text/plain"): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function formatTime(ts: number | null | undefined): string {
  if (!ts) return "–";
  const d = new Date(ts * 1000);
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

export function formatDateTime(ts: number | null | undefined): string {
  if (!ts) return "–";
  const d = new Date(ts * 1000);
  return `${d.toLocaleDateString()} ${formatTime(ts).slice(0, 8)}`;
}

const SVG_NS = "http://www.w3.org/2000/svg";

/** SVG-Element erzeugen. */
export function svg<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number | null | undefined> = {},
  ...children: (SVGElement | string | null | undefined | false)[]
): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs))
    if (v !== null && v !== undefined) el.setAttribute(k, String(v));
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return el;
}
