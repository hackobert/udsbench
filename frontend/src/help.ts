/** Hilfe-Registry: Tooltips, Öffnen-Anfragen (Bus) und das ⓘ-Symbol für Feldhilfe. */
import { Emitter } from "./emitter";
import { t } from "./i18n";

export type HelpRequest =
  | { kind: "topic"; topic: string; anchor?: string | null }
  | { kind: "context"; view: string; field?: string | null }
  | { kind: "search"; query?: string }
  | { kind: "toggle" };

export interface Tooltip {
  text: string;
  topic: string; // "<id>#<anchor>"
}

export const helpBus = new Emitter<HelpRequest>();
const tooltipsLoaded = new Emitter<void>();
let tooltips: Record<string, Tooltip> = {};
let idSeq = 0;

export function setTooltips(map: Record<string, Tooltip>): void {
  tooltips = map;
  tooltipsLoaded.emit();
}

export function getTooltip(key: string): Tooltip | undefined {
  return tooltips[key];
}

export function tooltipKeys(): string[] {
  return Object.keys(tooltips);
}

/** "topic#anchor" aufteilen. */
export function splitTopicRef(ref: string): { topic: string; anchor: string | null } {
  const [topic = "", anchor] = ref.split("#");
  return { topic, anchor: anchor || null };
}

export function openHelpTopic(topic: string, anchor?: string | null): void {
  helpBus.emit({ kind: "topic", topic, anchor: anchor ?? null });
}

export function openContextHelp(view: string, field?: string | null): void {
  helpBus.emit({ kind: "context", view, field: field ?? null });
}

export function openHelpSearch(query?: string): void {
  helpBus.emit({ kind: "search", query });
}

/** Alle per infoIcon() verwendeten Schlüssel (für Prüfungen/Tests). */
export const usedHelpKeys = new Set<string>();

/**
 * Dezentes ⓘ neben einem Bedienelement: Hover/Fokus zeigt den Tooltip-Text
 * (aria-describedby), Klick öffnet die Hilfe am verlinkten Abschnitt.
 */
export function infoIcon(key: string): HTMLElement {
  usedHelpKeys.add(key);
  const id = `tip-${++idSeq}`;
  const tip = document.createElement("span");
  tip.id = id;
  tip.className = "tip";
  tip.setAttribute("role", "tooltip");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "info";
  btn.textContent = "i";
  btn.dataset["help"] = key;
  btn.setAttribute("aria-describedby", id);
  const fill = () => {
    const tt = tooltips[key];
    tip.textContent = tt ? `${tt.text} ${t("help.clickMore")}` : "";
    btn.setAttribute("aria-label", tt ? `${t("help.fieldHelp")}: ${tt.text}` : t("help.fieldHelp"));
    wrap.hidden = !tt && Object.keys(tooltips).length > 0;
  };
  btn.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const tt = tooltips[key];
    if (tt) {
      const r = splitTopicRef(tt.topic);
      openHelpTopic(r.topic, r.anchor);
    } else {
      const [view = "", field] = key.split(".");
      openContextHelp(view, field);
    }
  });
  const wrap = document.createElement("span");
  wrap.className = "info-wrap";
  wrap.append(btn, tip);
  fill();
  if (!Object.keys(tooltips).length) {
    const off = tooltipsLoaded.on(() => {
      fill();
      off();
    });
  }
  return wrap;
}
