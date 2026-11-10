/** App-Shell: Kopfzeile, gruppierte Navigation, Hilfe-Seitenleiste, Tastaturkürzel, Event-Socket. */
import { ApiClient } from "./api";
import { ecuSelect } from "./components/ecu-select";
import { createHelpPanel, type HelpPanel, type HelpTopic } from "./components/help-panel";
import { toast, toastError } from "./components/toast";
import { button, field, modal, textInput } from "./components/ui";
import { debounce, h, isEditable, replace } from "./dom";
import { openContextHelp, openHelpSearch, openHelpTopic } from "./help";
import { getLang, LANGUAGES, setLang, t, type MsgKey, type Lang } from "./i18n";
import { icon } from "./icons";
import { extractSteps } from "./markdown";
import * as storage from "./storage";
import { Store } from "./store";
import type { EventMsg } from "./types";
import type { AppCtx, View, ViewDef } from "./view";
import { NAV_GROUPS, START_VIEW, VIEWS } from "./views";
import { ReconnectingSocket, WS_UNAUTHORIZED } from "./ws";

export type Theme = "light" | "dark";

/** Gespeicherte Theme-Wahl (null = Systemeinstellung). */
export function storedTheme(): Theme | null {
  const saved = storage.load<string | null>("theme", null);
  return saved === "light" || saved === "dark" ? saved : null;
}

export function systemTheme(): Theme {
  try {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function applyTheme(theme: Theme | null): void {
  if (theme) document.documentElement.dataset["theme"] = theme;
  else delete document.documentElement.dataset["theme"];
  storage.save("theme", theme);
}

/** Alt+Ziffer → View-Index (1…9, 0 = 10). */
export function viewIndexForKey(key: string): number | null {
  if (!/^[0-9]$/.test(key)) return null;
  const n = Number(key);
  return n === 0 ? 9 : n - 1;
}

/** Onboarding-Schritt → Ziel-Ansicht (aus dem Schritt-Titel). */
export function stepTarget(title: string): string | null {
  const s = title.toLowerCase();
  if (s.includes("verbind")) return "connection";
  if (s.includes("trace")) return "trace";
  if (s.includes("test")) return "tests";
  if (s.includes("anfrage") || s.includes("antwort") || s.includes("senden")) return "uds";
  if (s.includes("dashboard")) return "dashboards";
  if (s.includes("report")) return "reports";
  return null;
}

export class App {
  readonly api: ApiClient;
  readonly store: Store;
  private root: HTMLElement;
  private views = new Map<string, View>();
  private current: string;
  private main!: HTMLElement;
  private nav!: HTMLElement;
  private banner!: HTMLElement;
  private headerStatus!: HTMLElement;
  private headerEcuState!: HTMLElement;
  private help: HelpPanel | null = null;
  private disposers: (() => void)[] = [];
  private events: ReconnectingSocket;
  private tokenDialogOpen = false;
  private theme: Theme | null = storedTheme();
  private connectionKnown = false;

  constructor(root: HTMLElement, api?: ApiClient) {
    this.root = root;
    this.api = api ?? new ApiClient();
    this.store = new Store(this.api);
    const saved = storage.load<string>("view", START_VIEW);
    const fromHash = window.location.hash.replace(/^#\/?/, "");
    this.current = VIEWS.some((v) => v.id === fromHash)
      ? fromHash
      : VIEWS.some((v) => v.id === saved)
        ? saved
        : START_VIEW;
    this.api.onUnauthorized = () => this.showTokenDialog();
    this.events = new ReconnectingSocket(() => this.api.wsUrl("/ws/events"), {
      onMessage: (d) => this.onEvent(d as EventMsg),
      onClose: (code) => {
        if (code === WS_UNAUTHORIZED) this.showTokenDialog();
      },
      onStateChange: (s) => {
        this.store.eventsState = s;
        this.store.changed.emit("eventsState");
      },
    });
  }

  get ctx(): AppCtx {
    return { api: this.api, store: this.store, navigate: (id) => this.navigate(id) };
  }

  async start(): Promise<void> {
    this.api.adoptTokenFromUrl();
    applyTheme(this.theme);
    setLang(getLang());
    this.render();
    document.addEventListener("keydown", (ev) => this.onKey(ev));
    window.addEventListener("hashchange", () => {
      const id = window.location.hash.replace(/^#\/?/, "");
      if (VIEWS.some((v) => v.id === id) && id !== this.current) this.navigate(id);
    });
    try {
      const health = await this.api.health();
      if (health.auth_required && !this.api.token) {
        this.showTokenDialog();
        return;
      }
    } catch (exc) {
      toastError(exc, t("app.backendDown"));
    }
    await this.boot();
  }

  private async boot(): Promise<void> {
    this.events.start();
    try {
      await this.store.refreshAll();
    } catch (exc) {
      toastError(exc);
    }
  }

  private refreshSoon = debounce((what: "ecus" | "connection" | "all") => {
    const p =
      what === "ecus"
        ? this.store.refreshEcus()
        : what === "connection"
          ? Promise.all([this.store.refreshConnection(), this.store.refreshEcus()])
          : this.store.refreshAll();
    void p.catch(() => undefined);
  }, 200);

  private onEvent(e: EventMsg): void {
    if (!e || typeof e.topic !== "string") return;
    this.store.events.emit(e);
    switch (e.topic) {
      case "session":
      case "security":
        this.refreshSoon("ecus");
        break;
      case "connection":
      case "simulation":
        this.refreshSoon("connection");
        break;
      case "packages":
        this.refreshSoon("all");
        break;
    }
  }

  // --- Rendering ------------------------------------------------------------------------------------
  private render(): void {
    for (const d of this.disposers) d();
    this.disposers = [];
    for (const v of this.views.values()) v.destroy?.();
    this.views.clear();

    this.headerStatus = h("div", { class: "hdr-status" });
    this.headerEcuState = h("div", { class: "hdr-ecu-state" });
    const ecuSel = ecuSelect(this.store);
    this.disposers.push(ecuSel.dispose);

    const langSel = h(
      "select",
      { "aria-label": t("header.language"), class: "lang-select compact" },
      LANGUAGES.map((l) => h("option", { value: l.id, selected: l.id === getLang() }, l.id.toUpperCase())),
    );
    langSel.addEventListener("change", () => {
      setLang(langSel.value as Lang);
      this.render();
    });
    const effTheme = () => this.theme ?? systemTheme();
    const themeBtn = h("button", {
      class: "btn btn-ghost btn-icon theme-toggle",
      title: t("header.theme"),
      "aria-label": t("header.theme"),
    });
    const syncThemeBtn = () => replace(themeBtn, icon(effTheme() === "dark" ? "sun" : "moon"));
    syncThemeBtn();
    themeBtn.addEventListener("click", () => {
      this.theme = effTheme() === "dark" ? "light" : "dark";
      applyTheme(this.theme);
      syncThemeBtn();
    });

    const searchBox = h("input", {
      type: "search",
      class: "hdr-search",
      placeholder: t("header.searchHelp"),
      "aria-label": t("help.search"),
    });
    searchBox.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        openHelpSearch(searchBox.value);
        searchBox.value = "";
      }
    });

    const header = h(
      "header",
      { class: "app-header" },
      h(
        "button",
        {
          class: "btn btn-ghost btn-icon nav-toggle",
          "aria-label": t("header.menu"),
          onclick: () => this.root.classList.toggle("nav-open"),
        },
        icon("menu"),
      ),
      h("div", { class: "brand" }, h("span", { class: "brand-mark", "aria-hidden": "true" }), "udsbench"),
      this.headerStatus,
      h(
        "div",
        { class: "hdr-ecu" },
        h("span", { class: "label" }, t("header.ecu")),
        ecuSel.el,
        this.headerEcuState,
      ),
      h(
        "div",
        { class: "hdr-tools" },
        h("label", { class: "hdr-search-wrap" }, icon("search", 15), searchBox, h("kbd", null, "Strg K")),
        h(
          "button",
          {
            class: "btn btn-ghost btn-icon help-btn",
            title: `${t("help.contextTitle")} (F1)`,
            "aria-label": t("help.contextTitle"),
            onclick: () => openContextHelp(this.current),
          },
          icon("help"),
        ),
        themeBtn,
        langSel,
        h(
          "button",
          {
            class: "btn btn-ghost btn-icon",
            title: t("token.title"),
            "aria-label": t("token.title"),
            onclick: () => this.showTokenDialog(),
          },
          icon("key"),
        ),
      ),
    );

    // Navigation in Gruppen
    const collapsedGroups = new Set(storage.load<string[]>("nav.groups", []));
    this.root.classList.toggle("nav-mini", storage.load<boolean>("nav.collapsed", false));
    this.nav = h(
      "nav",
      { class: "app-nav", "aria-label": t("header.menu") },
      NAV_GROUPS.map((g) => {
        const items = VIEWS.map((v, i) => ({ v, i })).filter(({ v }) => v.group === g);
        const list = h(
          "div",
          { class: "nav-items", id: `nav-${g}` },
          items.map(({ v, i }) =>
            h(
              "a",
              {
                href: `#/${v.id}`,
                class: "nav-item",
                dataset: { view: v.id },
                title: i < 10 ? `${t(v.title)} (Alt+${(i + 1) % 10})` : t(v.title),
                onclick: (ev: Event) => {
                  ev.preventDefault();
                  this.navigate(v.id);
                  this.root.classList.remove("nav-open");
                },
              },
              icon(v.icon),
              h("span", { class: "nav-label" }, t(v.title)),
              i < 10 ? h("kbd", { class: "nav-kbd" }, String((i + 1) % 10)) : null,
            ),
          ),
        );
        const head = h(
          "button",
          {
            class: "nav-group-head",
            "aria-expanded": String(!collapsedGroups.has(g)),
            "aria-controls": `nav-${g}`,
          },
          h("span", { class: "label" }, t(`nav.group.${g}` as MsgKey)),
          h("span", { class: "nav-caret", "aria-hidden": "true" }),
        );
        list.hidden = collapsedGroups.has(g);
        head.addEventListener("click", () => {
          list.hidden = !list.hidden;
          head.setAttribute("aria-expanded", String(!list.hidden));
          if (list.hidden) collapsedGroups.add(g);
          else collapsedGroups.delete(g);
          storage.save("nav.groups", [...collapsedGroups]);
        });
        return h("div", { class: "nav-group" }, head, list);
      }),
      h(
        "button",
        {
          class: "nav-collapse",
          title: t("nav.collapse"),
          "aria-label": t("nav.collapse"),
          onclick: () => {
            const mini = !this.root.classList.contains("nav-mini");
            this.root.classList.toggle("nav-mini", mini);
            storage.save("nav.collapsed", mini);
          },
        },
        icon("collapse", 16),
        h("span", { class: "nav-label" }, t("nav.collapse")),
      ),
    );

    this.banner = h("div", { class: "conn-banner", hidden: true, role: "status" });
    this.main = h("main", { class: "app-main", id: "main", tabindex: "-1" });
    this.help?.dispose();
    const help = createHelpPanel(this.api, (open) => this.root.classList.toggle("help-open", open));
    this.help = help;
    replace(
      this.root,
      h("a", { class: "skip-link", href: "#main" }, t("app.skip")),
      header,
      h(
        "div",
        { class: "app-body" },
        this.nav,
        h("div", { class: "main-col" }, this.banner, this.main),
        help.el,
      ),
    );
    this.root.classList.add("app");

    this.disposers.push(
      this.store.changed.on((k) => {
        if (k === "connection" || k === "eventsState") this.renderHeaderStatus();
        if (k === "connection") {
          this.connectionKnown = true;
          this.renderBanner();
        }
        if (k === "ecus" || k === "selectedEcu") this.renderEcuState();
      }),
    );
    this.renderHeaderStatus();
    this.renderEcuState();
    this.navigate(this.current);
  }

  private renderHeaderStatus(): void {
    if (!this.headerStatus) return;
    const connected = this.store.connection.channels.filter((c) => c.connected);
    const es = this.store.eventsState;
    replace(
      this.headerStatus,
      h(
        "button",
        {
          class: ["pill", connected.length ? "pill-ok" : "pill-fail"],
          title: t("header.toConnection"),
          onclick: () => this.navigate("connection"),
        },
        h("span", { class: "pill-dot", "aria-hidden": "true" }),
        connected.length
          ? t("header.connected", { list: connected.map((c) => `${c.name} · ${c.backend}`).join(", ") })
          : t("header.disconnected"),
      ),
      h(
        "span",
        { class: ["live", `live-${es}`], title: `${t("header.events")}: ${t(`ws.${es}`)}` },
        h("span", { class: "live-dot", "aria-hidden": "true" }),
        t(`ws.${es}`),
      ),
    );
  }

  private renderBanner(): void {
    if (!this.banner) return;
    const connected = this.store.connection.channels.some((c) => c.connected);
    const show = this.connectionKnown && !connected && this.current !== "connection";
    this.banner.hidden = !show;
    if (!show) return;
    replace(
      this.banner,
      h("strong", null, t("banner.noConnection")),
      h("span", null, t("banner.noConnectionText")),
      button(t("banner.connectNow"), () => this.navigate("connection"), { kind: "primary" }),
      button(t("help.open"), () => openHelpTopic("verbindung"), { kind: "ghost" }),
    );
  }

  private renderEcuState(): void {
    if (!this.headerEcuState) return;
    const e = this.store.ecu();
    if (!e) {
      replace(this.headerEcuState);
      return;
    }
    replace(
      this.headerEcuState,
      h(
        "span",
        { class: ["chip-state", e.session === 1 ? "cs-neutral" : "cs-info"], title: t("header.session") },
        e.session_name.replace(/Session$/, ""),
      ),
      e.unlocked_levels.length
        ? h(
            "span",
            { class: "chip-state cs-ok", title: t("header.unlocked") },
            icon("lock", 13),
            `${t("header.unlockedShort")} ${e.unlocked_levels.map((l) => `L${l}`).join(",")}`,
          )
        : h(
            "span",
            { class: "chip-state cs-neutral", title: t("header.locked") },
            icon("lock", 13),
            t("header.locked"),
          ),
      e.tester_present.enabled
        ? h("span", { class: "chip-state cs-neutral", title: "TesterPresent" }, "TP")
        : null,
    );
  }

  navigate(id: string): void {
    const def: ViewDef | undefined = VIEWS.find((v) => v.id === id) ?? VIEWS.find((v) => v.id === START_VIEW);
    if (!def) return;
    const prev = this.views.get(this.current);
    if (prev && this.current !== def.id) prev.hide?.();
    this.current = def.id;
    storage.save("view", def.id);
    if (window.location.hash !== `#/${def.id}`) {
      try {
        window.history.replaceState(null, "", `#/${def.id}`);
      } catch {
        /* ignorieren */
      }
    }
    let view = this.views.get(def.id);
    if (!view) {
      view = def.create(this.ctx);
      view.el.classList.add("view", `view-${def.id}`);
      this.views.set(def.id, view);
    }
    for (const a of this.nav.querySelectorAll<HTMLElement>(".nav-item")) {
      const active = a.dataset["view"] === def.id;
      a.classList.toggle("active", active);
      if (active) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    replace(
      this.main,
      h(
        "div",
        { class: "view-head" },
        h("h1", { class: "view-title" }, t(def.title)),
        h(
          "a",
          {
            href: `#help:${def.id}`,
            class: "view-help",
            onclick: (ev: Event) => {
              ev.preventDefault();
              openContextHelp(def.id);
            },
          },
          icon("help", 15),
          t("help.thisView"),
        ),
      ),
      def.id === START_VIEW ? this.onboarding() : null,
      view.el,
    );
    document.title = `${t(def.title)} – udsbench`;
    this.renderBanner();
    view.show?.();
  }

  get currentView(): string {
    return this.current;
  }

  /** „Erste Schritte“-Karte beim ersten Öffnen (ausblendbar). */
  private onboarding(): HTMLElement | null {
    if (storage.load<boolean>("onboarding.dismissed", false)) return null;
    const box = h("section", { class: "onboarding", "aria-label": t("onb.title") });
    const dismiss = () => {
      storage.save("onboarding.dismissed", true);
      box.remove();
    };
    const render = (steps: { title: string; text: string }[]) =>
      replace(
        box,
        h(
          "div",
          { class: "onb-head" },
          h("div", null, h("h2", null, t("onb.title")), h("p", { class: "muted" }, t("onb.lead"))),
          h(
            "div",
            { class: "onb-actions" },
            button(t("onb.more"), () => openHelpTopic("erste-schritte"), { kind: "ghost" }),
            button(t("onb.dismiss"), dismiss, { kind: "ghost", cls: "onb-dismiss" }),
          ),
        ),
        h(
          "ol",
          { class: "onb-steps" },
          steps.map((s) => {
            const target = stepTarget(s.title);
            const def = VIEWS.find((v) => v.id === target);
            return h(
              "li",
              null,
              h("strong", null, s.title),
              h("span", { class: "onb-text" }, s.text.replace(/\*\*|\*|`/g, "")),
              def && target ? button(t("onb.go", { view: t(def.title) }), () => this.navigate(target)) : null,
            );
          }),
        ),
      );
    void this.api
      .get<HelpTopic>("/help/topics/erste-schritte")
      .then((tp) => render(extractSteps(tp.markdown).slice(0, 5)))
      .catch(() => box.remove());
    return box;
  }

  // --- Tastatur ---------------------------------------------------------------------------------------
  private onKey(ev: KeyboardEvent): void {
    if (ev.key === "F1") {
      ev.preventDefault();
      openContextHelp(this.current);
      return;
    }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
      ev.preventDefault();
      openHelpSearch();
      return;
    }
    if (document.querySelector(".modal-overlay")) return;
    if (ev.key === "Escape" && this.help?.isOpen()) {
      this.help.close();
      return;
    }
    if (this.views.get(this.current)?.onKey?.(ev)) return;
    if (ev.altKey && !ev.ctrlKey && !ev.metaKey) {
      const idx = viewIndexForKey(ev.key) ?? viewIndexForKey(ev.code.replace(/^Digit/, ""));
      if (idx !== null && VIEWS[idx]) {
        ev.preventDefault();
        this.navigate(VIEWS[idx].id);
        return;
      }
    }
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
      const v = this.views.get(this.current);
      if (v?.submit) {
        ev.preventDefault();
        v.submit();
      }
      return;
    }
    if (isEditable(ev.target)) return;
    if (ev.key === " " && this.current === "trace") {
      ev.preventDefault();
      this.views.get("trace")?.togglePause?.();
    } else if (ev.key === "?") {
      ev.preventDefault();
      this.showShortcuts();
    }
  }

  showShortcuts(): void {
    const rows: [string, string][] = [
      ["F1", t("keys.f1")],
      ["Shift + ?", t("keys.shortcuts")],
      ["Strg + K", t("keys.search")],
      ["Esc", t("keys.esc")],
      ["Alt + 1 … 9, Alt + 0", t("keys.views")],
      ["Strg + Enter", t("keys.send")],
      [t("keys.spaceKey"), t("keys.pause")],
    ];
    const close = modal(
      t("keys.title"),
      h(
        "div",
        { class: "shortcuts" },
        h(
          "table",
          { class: "tbl" },
          h(
            "tbody",
            null,
            rows.map(([k, d]) =>
              h("tr", null, h("td", { class: "nowrap" }, h("kbd", null, k)), h("td", null, d)),
            ),
          ),
        ),
        h("h3", { class: "label" }, t("keys.viewsTitle")),
        h(
          "ol",
          { class: "help-views" },
          VIEWS.slice(0, 10).map((v, i) =>
            h("li", null, h("kbd", null, `Alt+${(i + 1) % 10}`), ` ${t(v.title)}`),
          ),
        ),
      ),
      [
        button(t("keys.more"), () => {
          close();
          openHelpTopic("tastenkuerzel");
        }),
      ],
    );
  }

  showTokenDialog(): void {
    if (this.tokenDialogOpen) return;
    this.tokenDialogOpen = true;
    const input = textInput(this.api.token ?? "", {
      type: "password",
      autocomplete: "off",
      placeholder: "Token",
    });
    const save = async () => {
      this.api.setToken(input.value);
      close();
      this.events.reconnect();
      try {
        await this.store.refreshAll();
        toast(t("token.saved"), "success");
        this.render();
      } catch (exc) {
        toastError(exc);
      }
    };
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") void save();
    });
    const close = modal(
      t("token.title"),
      h("div", null, h("p", null, t("token.text")), field(t("token.label"), input)),
      [button(t("token.save"), save, { kind: "primary" })],
      () => (this.tokenDialogOpen = false),
    );
  }
}
