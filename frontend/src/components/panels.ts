/** Panel-Typen der Dashboards. Jeder Renderer liefert Element + Aufräumfunktion. */
import type { ButtonDef } from "../action-model";
import { formatTime, h, replace } from "../dom";
import { t } from "../i18n";
import { timeLabel, topicColor } from "../timechart-math";
import { toWsFilter, traceCells, traceRowClass, type TraceFilterState } from "../trace-format";
import type { LogEntry, RunInfo, StepRunResponse, TraceBatch, TraceItem } from "../types";
import type { AppCtx } from "../view";
import { ReconnectingSocket } from "../ws";
import { actionResultView } from "./action-result";
import { createTimechart, statsTiles, type StatsSummary, type TimelineEvent } from "./timechart";
import { toastError } from "./toast";
import { badge, statusBadge, valueView, confirmDialog } from "./ui";

export type PanelType =
  | "buttons"
  | "values"
  | "timechart"
  | "stats"
  | "events"
  | "trace"
  | "ecu_status"
  | "log"
  | "note"
  | "run_status";

export const PANEL_TYPES: PanelType[] = [
  "buttons",
  "values",
  "timechart",
  "stats",
  "events",
  "trace",
  "ecu_status",
  "log",
  "note",
  "run_status",
];

export interface PanelDef {
  id: string;
  title: string;
  type: PanelType;
  x: number;
  y: number;
  w: number;
  h: number;
  buttons: ButtonDef[];
  config: Record<string, unknown>;
}

export interface PanelRender {
  el: HTMLElement;
  dispose: () => void;
}

/** Standardkonfiguration je Panel-Typ (für neue Panels / Editor-Vorlage). */
export function defaultConfig(type: PanelType, ecu: string | null): Record<string, unknown> {
  switch (type) {
    case "values":
      return { ecu, dids: ["0x0100", "0x0101"], refresh_ms: 2000 };
    case "timechart":
      return { metric: "uds", group_by: "type", window_s: 300 };
    case "stats":
      return { window_s: 900 };
    case "events":
      return { topics: [], limit: 50 };
    case "trace":
      return { view: "messages", filter: { only_uds: true } };
    case "log":
      return { channel: "", level: "INFO" };
    case "note":
      return { text: "Notiz …" };
    case "run_status":
      return { limit: 5 };
    case "ecu_status":
      return { ecus: [] };
    default:
      return {};
  }
}

export interface PressHandler {
  (btn: ButtonDef, idx: number): Promise<Record<string, unknown>>;
}

/** Hintergrundfarbe/Klasse eines Knopfs. */
export function buttonStyle(color: string | null | undefined): {
  cls: string;
  style?: Record<string, string>;
} {
  const presets = ["primary", "success", "danger", "warning", "default"];
  if (!color || presets.includes(color)) return { cls: `dbtn dbtn-${color ?? "primary"}` };
  return { cls: "dbtn dbtn-custom", style: { background: color, borderColor: color } };
}

function poll(fn: () => Promise<void>, ms: number, el: HTMLElement): () => void {
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    if (el.isConnected) await fn().catch(() => undefined);
    if (!stopped) timer = setTimeout(tick, ms);
  };
  let timer: ReturnType<typeof setTimeout> = setTimeout(tick, 0);
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}

export function renderPanel(ctx: AppCtx, p: PanelDef, press: PressHandler): PanelRender {
  const { api, store } = ctx;
  const c = p.config ?? {};
  const num = (k: string, d: number) =>
    typeof c[k] === "number" ? (c[k] as number) : Number(c[k] ?? d) || d;
  const str = (k: string) => (typeof c[k] === "string" ? (c[k] as string) : "");

  switch (p.type) {
    case "buttons": {
      const el = h("div", { class: "dbtns" });
      p.buttons.forEach((b, i) => {
        const st = buttonStyle(b.color);
        const out = h("div", { class: "dbtn-out" });
        const btn = h(
          "button",
          {
            class: st.cls,
            style: st.style,
            title: [b.description, b.shortcut].filter(Boolean).join(" · "),
            dataset: { idx: String(i) },
          },
          b.icon ? h("span", { class: "dbtn-icon" }, b.icon) : null,
          h("span", null, b.label),
          b.shortcut ? h("kbd", { class: "dbtn-kbd" }, b.shortcut) : null,
        );
        btn.addEventListener("click", async () => {
          if (
            b.action.confirm &&
            !(await confirmDialog(t("dash.confirmPress", { label: b.label }), {
              danger: false,
              confirmLabel: t("dash.pressNow"),
            }))
          )
            return;
          btn.disabled = true;
          btn.classList.add("busy");
          try {
            const r = await press(b, i);
            replace(out, actionResultView(r, store));
          } catch (exc) {
            replace(out, h("div", { class: "action-result tone-fail" }, (exc as Error).message));
            toastError(exc);
          } finally {
            btn.disabled = false;
            btn.classList.remove("busy");
          }
        });
        el.appendChild(h("div", { class: "dbtn-cell" }, btn, out));
      });
      if (!p.buttons.length) el.appendChild(h("div", { class: "empty" }, t("dash.noButtons")));
      return { el, dispose: () => undefined };
    }
    case "values": {
      const el = h("div", { class: "values-panel" }, h("span", { class: "muted" }, t("common.loading")));
      const dids = Array.isArray(c["dids"]) ? (c["dids"] as (string | number)[]) : [];
      const stop = poll(
        async () => {
          if (!dids.length) {
            replace(el, h("div", { class: "empty" }, t("dash.noDids")));
            return;
          }
          try {
            const r = await api.post<StepRunResponse>("/dids/read", {
              ecu: (c["ecu"] as string | null) ?? store.selectedEcu,
              dids,
            });
            const recs =
              (r.step.decoded?.fields?.["records"] as
                { did_hex: string; name: string; value: unknown; unit: string }[] | undefined) ?? [];
            replace(
              el,
              recs.length
                ? h(
                    "div",
                    { class: "value-tiles" },
                    recs.map((x) =>
                      h(
                        "div",
                        { class: "tile" },
                        h("div", { class: "tile-value" }, valueView(x.value, x.unit)),
                        h("div", { class: "tile-label" }, `${x.name} (${x.did_hex})`),
                      ),
                    ),
                  )
                : h("div", { class: "error-box" }, r.step.decoded?.text ?? r.step.message ?? r.step.status),
            );
          } catch (exc) {
            replace(el, h("div", { class: "error-box" }, (exc as Error).message));
          }
        },
        Math.max(250, num("refresh_ms", 2000)),
        el,
      );
      return { el, dispose: stop };
    }
    case "timechart": {
      const tc = createTimechart(
        api,
        {
          metric: (str("metric") || "uds") as "uds",
          group_by: str("group_by") || "type",
          window_s: num("window_s", 300),
          bucket_s: typeof c["bucket_s"] === "number" ? (c["bucket_s"] as number) : null,
          ecu: str("ecu") || null,
          compact: true,
          showEvents: c["show_events"] !== false,
          height: Math.max(120, p.h * 90 - 90),
        },
        {
          onReport: (from, to) => {
            store.reportRange = { from, to };
            ctx.navigate("reports");
          },
        },
      );
      return { el: tc.el, dispose: tc.dispose };
    }
    case "stats": {
      const el = h("div");
      const stop = poll(
        async () => {
          const s = await api.get<StatsSummary>("/stats/summary", {
            from: `-${num("window_s", 900)}s`,
            ecu: str("ecu") || undefined,
          });
          replace(el, statsTiles(s));
        },
        5000,
        el,
      );
      return { el, dispose: stop };
    }
    case "events": {
      const el = h("div", { class: "events-panel" });
      const topics = Array.isArray(c["topics"]) ? (c["topics"] as string[]).join(",") : str("topics");
      const stop = poll(
        async () => {
          const r = await api.get<{ items: TimelineEvent[] }>("/events", {
            from: "-1h",
            topics: topics || undefined,
            limit: num("limit", 50),
          });
          replace(
            el,
            h(
              "ul",
              { class: "event-list" },
              [...r.items]
                .reverse()
                .map((e) =>
                  h(
                    "li",
                    { class: e.type === "negative" ? "ev-neg" : "" },
                    h("span", { class: "mono small" }, timeLabel(e.ts)),
                    " ",
                    h(
                      "span",
                      { class: "badge", style: { background: topicColor(e.topic), color: "var(--surface)" } },
                      e.topic,
                    ),
                    " ",
                    [e.ecu, e.type, e.service, e.request, e.nrc_name, e.text, e.msg]
                      .filter(Boolean)
                      .join(" · "),
                  ),
                ),
            ),
          );
        },
        3000,
        el,
      );
      return { el, dispose: stop };
    }
    case "trace": {
      const tbody = h("tbody");
      const el = h(
        "div",
        { class: "mini-trace" },
        h("table", { class: "tbl trace-table mono small" }, tbody),
      );
      const view = str("view") === "frames" ? "frames" : "messages";
      const flt = (c["filter"] as Partial<TraceFilterState> | undefined) ?? {};
      let t0: number | null = null;
      const sock = new ReconnectingSocket(() => api.wsUrl("/ws/trace"), {
        onOpen: () => {
          sock.send({
            action: "filter",
            filter: toWsFilter({
              ids: "",
              data_contains: "",
              direction: "",
              services: "",
              only_uds: false,
              ...flt,
            }),
          });
          sock.send({ action: "views", views: [view] });
        },
        onMessage: (d) => {
          const b = d as TraceBatch;
          if (b.type !== "batch") return;
          const items = (view === "frames" ? b.frames : b.messages) as TraceItem[];
          for (const it of items.slice(-40)) {
            if (t0 === null) t0 = it.ts;
            const cells = traceCells(it, t0);
            tbody.appendChild(
              h(
                "tr",
                { class: traceRowClass(it) },
                h("td", null, cells.time),
                h("td", null, cells.dir),
                h("td", null, cells.id),
                h("td", null, cells.data),
                h("td", null, cells.text),
              ),
            );
          }
          while (tbody.childElementCount > 40) tbody.firstElementChild?.remove();
          el.scrollTop = el.scrollHeight;
        },
      });
      sock.start();
      return { el, dispose: () => sock.stop() };
    }
    case "ecu_status": {
      const el = h("div");
      const only = Array.isArray(c["ecus"]) ? (c["ecus"] as string[]) : [];
      const render = () =>
        replace(
          el,
          h(
            "table",
            { class: "tbl small" },
            h(
              "tbody",
              null,
              store.ecus
                .filter((e) => !only.length || only.includes(e.id))
                .map((e) =>
                  h(
                    "tr",
                    null,
                    h("td", null, h("strong", null, e.id)),
                    h("td", null, badge(e.session_name, e.session === 1 ? "" : "run")),
                    h(
                      "td",
                      null,
                      e.unlocked_levels.length
                        ? badge(`🔓 ${e.unlocked_levels.join(",")}`, "ok")
                        : badge("🔒"),
                    ),
                    h("td", null, e.tester_present.enabled ? badge("TP", "muted") : ""),
                    h("td", null, badge(e.connected ? "●" : "○", e.connected ? "ok" : "fail")),
                  ),
                ),
            ),
          ),
        );
      render();
      const off = store.changed.on((k) => k === "ecus" && render());
      return { el, dispose: off };
    }
    case "log": {
      const list = h("ul", { class: "log-list mono small" });
      const levels = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];
      const ch = str("channel");
      const lv = str("level");
      const ok = (e: LogEntry) =>
        (!ch || e.channel === ch) && (!lv || levels.indexOf(e.level) >= levels.indexOf(lv));
      const add = (e: LogEntry) => {
        list.appendChild(
          h(
            "li",
            { class: `lv-${e.level.toLowerCase()}` },
            `${formatTime(e.ts)} ${e.level} [${e.channel}] ${e.msg}`,
          ),
        );
        while (list.childElementCount > 60) list.firstElementChild?.remove();
        list.scrollTop = list.scrollHeight;
      };
      void api
        .get<{ items: LogEntry[] }>("/logs", { channel: ch || undefined, level: lv || undefined, limit: 30 })
        .then((r) => r.items.forEach(add))
        .catch(() => undefined);
      const off = store.on("log", (e) => {
        const entry = e["entry"] as LogEntry | undefined;
        if (entry && ok(entry)) add(entry);
      });
      return { el: list, dispose: off };
    }
    case "note": {
      const el = h("div", { class: "note-panel" }, str("text"));
      return { el, dispose: () => undefined };
    }
    case "run_status": {
      const el = h("div");
      const load = async () => {
        const runs = await api.get<RunInfo[]>("/runs");
        runs.sort((a, b) => b.created - a.created);
        replace(
          el,
          h(
            "ul",
            { class: "run-list" },
            runs
              .slice(0, num("limit", 5))
              .map((r) =>
                h(
                  "li",
                  null,
                  statusBadge(r.status),
                  ` ${r.name} `,
                  h(
                    "span",
                    { class: "muted small" },
                    `${r.summary.passed}/${r.planned} · ${formatTime(r.started ?? r.created)}`,
                  ),
                ),
              ),
          ),
        );
      };
      void load().catch(() => undefined);
      const off = store.on("run", () => void load().catch(() => undefined));
      return { el, dispose: off };
    }
    default:
      return { el: h("div", { class: "empty" }, `? ${String(p.type)}`), dispose: () => undefined };
  }
}
