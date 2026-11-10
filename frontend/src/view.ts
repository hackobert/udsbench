/** View-Schnittstelle und App-Kontext. */
import type { ApiClient } from "./api";
import type { MsgKey } from "./i18n";
import type { Store } from "./store";

export interface AppCtx {
  api: ApiClient;
  store: Store;
  navigate: (id: string) => void;
}

export interface View {
  el: HTMLElement;
  /** Beim Einblenden (z. B. Daten neu laden). */
  show?: () => void;
  hide?: () => void;
  destroy?: () => void;
  /** Strg+Enter innerhalb der View. */
  submit?: () => void;
  /** Leertaste (nur Trace). */
  togglePause?: () => void;
  /** Eigene Tastenkürzel; true = behandelt. */
  onKey?: (ev: KeyboardEvent) => boolean;
}

export interface ViewDef {
  id: string;
  title: MsgKey;
  icon: string;
  group: "observe" | "diagnose" | "automate" | "evaluate" | "system";
  create: (ctx: AppCtx) => View;
}
