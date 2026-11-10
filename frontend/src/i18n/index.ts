import * as storage from "../storage";
import { de } from "./de";
import { en } from "./en";

export type MsgKey = keyof typeof de;
export type Dict = Record<MsgKey, string>;
export type Lang = "de" | "en";

const DICTS: Record<Lang, Partial<Dict>> = { de, en };

export const LANGUAGES: { id: Lang; label: string }[] = [
  { id: "de", label: "Deutsch" },
  { id: "en", label: "English" },
];

let current: Lang = (() => {
  const l = storage.load<string>("lang", "de");
  return l === "en" ? "en" : "de";
})();

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang): void {
  current = lang;
  storage.save("lang", lang);
  if (typeof document !== "undefined") document.documentElement.lang = lang;
}

/** Übersetzen mit {platzhalter}-Ersetzung. */
export function t(key: MsgKey, vars?: Record<string, string | number>): string {
  const s = DICTS[current][key] ?? de[key] ?? key;
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, name: string) => (name in vars ? String(vars[name]) : m));
}
