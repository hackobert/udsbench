import { infoIcon } from "../help";
import { ecuSelect } from "../components/ecu-select";
import { toast, toastError } from "../components/toast";
import { badge, button, card, checkbox, field, row, table, textInput, confirmDialog } from "../components/ui";
import { ApiError, formatErrorDetails } from "../api";
import { formatDateTime, h, replace } from "../dom";
import { t } from "../i18n";
import type { RunInfo } from "../types";
import type { AppCtx, View } from "../view";

export const INCLUDE_KEYS = ["stats", "events", "runs", "messages", "frames", "logs", "recordings"] as const;
export const TRACE_FORMATS = ["asc", "csv", "candump", "jsonl"] as const;

interface ReportItem {
  id: string;
  title: string;
  created: number;
  from: number;
  to: number;
  ecu: string | null;
  uds_requests?: number;
  uds_totals?: Record<string, number>;
  frames?: number;
  runs?: number;
  attachments?: { name: string; description: string; size: number }[];
}

export interface ReportForm {
  title: string;
  from: number;
  to: number;
  ecu: string | null;
  notes: string;
  author: string;
  include: Record<(typeof INCLUDE_KEYS)[number], boolean>;
  trace_formats: string[];
  run_ids: string[];
}

/** Formular → Request-Body für POST /reports (Zeiten als Epoch-Sekunden). */
export function reportBody(f: ReportForm): Record<string, unknown> {
  if (!(f.to > f.from)) throw new Error(t("report.badRange"));
  const body: Record<string, unknown> = {
    title: f.title.trim() || t("report.defaultTitle"),
    from: Math.floor(f.from * 1000) / 1000,
    to: Math.ceil(f.to * 1000) / 1000,
    notes: f.notes,
    author: f.author,
    include: { ...f.include },
    trace_formats: [...f.trace_formats],
  };
  if (f.ecu) body["ecu"] = f.ecu;
  if (f.run_ids.length) body["run_ids"] = [...f.run_ids];
  return body;
}

/** Epoch-Sekunden → Wert für <input type="datetime-local"> (lokale Zeit). */
export function toLocalInput(ts: number): string {
  const d = new Date(ts * 1000 - new Date(ts * 1000).getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 19);
}

export function fromLocalInput(v: string): number {
  return new Date(v).getTime() / 1000;
}

export function createReportsView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const now = () => Date.now() / 1000;
  const titleIn = textInput(t("report.defaultTitle"));
  const fromIn = h("input", { type: "datetime-local", step: "1" });
  const toIn = h("input", { type: "datetime-local", step: "1" });
  const ecuSel = ecuSelect(store, { allowNone: true, local: true });
  const notesIn = h("textarea", { rows: "3" });
  const authorIn = textInput("");
  const inc = INCLUDE_KEYS.map((k) => ({ k, c: checkbox(t(`report.inc.${k}`), true) }));
  const fmts = TRACE_FORMATS.map((f) => ({ f, c: checkbox(f, f === "asc" || f === "csv") }));
  const runsBox = h("div", { class: "runs-pick" });
  const runChecks = new Map<string, HTMLInputElement>();
  const resultBox = h("div");
  const listBox = h("div");

  const setRange = (from: number, to: number) => {
    fromIn.value = toLocalInput(from);
    toIn.value = toLocalInput(to);
  };
  setRange(now() - 900, now());

  const quick = (sec: number) => () => setRange(now() - sec, now());
  const sinceConnect = () => {
    const ts = store.connection.channels.map((c) => c.connected_at ?? 0).filter(Boolean);
    if (!ts.length) {
      toast(t("report.noConnection"), "warning");
      return;
    }
    setRange(Math.min(...ts), now());
  };

  const loadRuns = async () => {
    const runs = await api.get<RunInfo[]>("/runs");
    runs.sort((a, b) => b.created - a.created);
    runChecks.clear();
    replace(
      runsBox,
      runs.length
        ? runs.slice(0, 50).map((r) => {
            const c = checkbox(
              `${r.name} · ${r.run_id} · ${formatDateTime(r.started ?? r.created)} · ${r.status}`,
              false,
            );
            runChecks.set(r.run_id, c.input);
            return c.el;
          })
        : h("span", { class: "muted" }, t("common.noEntries")),
    );
  };

  const loadList = async () => {
    const items = await api.get<ReportItem[]>("/reports");
    items.sort((a, b) => b.created - a.created);
    replace(
      listBox,
      table<ReportItem>(
        [
          { key: "title", label: t("report.title_"), render: (r) => h("strong", null, r.title) },
          { key: "created", label: t("report.created"), render: (r) => formatDateTime(r.created) },
          {
            key: "range",
            label: t("report.range"),
            render: (r) => `${formatDateTime(r.from)} – ${formatDateTime(r.to)}`,
          },
          { key: "ecu", label: "ECU", render: (r) => r.ecu ?? t("common.all") },
          {
            key: "uds",
            label: "UDS",
            render: (r) => [
              `${r.uds_requests ?? 0} `,
              r.uds_totals?.["negative"] ? badge(`NRC ${r.uds_totals["negative"]}`, "fail") : null,
            ],
          },
          { key: "frames", label: t("stats.frames"), render: (r) => String(r.frames ?? 0) },
          {
            key: "att",
            label: t("report.attachments"),
            render: (r) =>
              h(
                "span",
                { class: "bits" },
                (r.attachments ?? []).map((a) =>
                  h(
                    "a",
                    {
                      href: "#",
                      class: "chip",
                      title: `${a.description} (${a.size} B)`,
                      onclick: (ev: Event) => {
                        ev.preventDefault();
                        api
                          .download(
                            `/reports/${encodeURIComponent(r.id)}/attachments/${encodeURIComponent(a.name)}`,
                            undefined,
                            a.name,
                          )
                          .catch(toastError);
                      },
                    },
                    a.name,
                  ),
                ),
              ),
          },
          {
            key: "act",
            label: "",
            render: (r) =>
              h(
                "span",
                { class: "inline" },
                button(
                  t("report.view"),
                  () => api.openInTab(`/reports/${encodeURIComponent(r.id)}`, { format: "html" }),
                  { kind: "primary" },
                ),
                button("ZIP", () =>
                  api.download(`/reports/${encodeURIComponent(r.id)}`, { format: "zip" }, `${r.id}.zip`),
                ),
                button(
                  "JSON",
                  () =>
                    api.download(`/reports/${encodeURIComponent(r.id)}`, { format: "json" }, `${r.id}.json`),
                  { kind: "ghost" },
                ),
                button(
                  t("common.delete"),
                  async () => {
                    if (!(await confirmDialog(t("report.deleteConfirm", { title: r.title })))) return;
                    await api.del(`/reports/${encodeURIComponent(r.id)}`);
                    await loadList();
                  },
                  { kind: "danger" },
                ),
              ),
          },
        ],
        items,
      ),
    );
  };

  const create = async () => {
    let body: Record<string, unknown>;
    try {
      body = reportBody({
        title: titleIn.value,
        from: fromLocalInput(fromIn.value),
        to: fromLocalInput(toIn.value),
        ecu: ecuSel.el.value || null,
        notes: notesIn.value,
        author: authorIn.value,
        include: Object.fromEntries(inc.map(({ k, c }) => [k, c.input.checked])) as ReportForm["include"],
        trace_formats: fmts.filter(({ c }) => c.input.checked).map(({ f }) => f),
        run_ids: [...runChecks].filter(([, c]) => c.checked).map(([id]) => id),
      });
    } catch (exc) {
      toast((exc as Error).message, "error");
      return;
    }
    try {
      const r = await api.post<ReportItem>("/reports", body);
      replace(
        resultBox,
        h(
          "div",
          { class: "result-head" },
          badge(t("report.created_"), "ok"),
          ` ${r.title} (${r.id}) `,
          button(
            t("report.view"),
            () => api.openInTab(`/reports/${encodeURIComponent(r.id)}`, { format: "html" }),
            { kind: "primary" },
          ),
          button("ZIP", () =>
            api.download(`/reports/${encodeURIComponent(r.id)}`, { format: "zip" }, `${r.id}.zip`),
          ),
        ),
      );
      await loadList();
    } catch (exc) {
      const lines =
        exc instanceof ApiError ? [exc.message, ...formatErrorDetails(exc.details)] : [String(exc)];
      replace(
        resultBox,
        h(
          "ul",
          { class: "editor-errors" },
          lines.map((l) => h("li", null, l)),
        ),
      );
    }
  };

  const el = h(
    "div",
    { class: "view-grid" },
    card(
      t("report.new"),
      h(
        "div",
        { class: "grid" },
        field(t("report.title_"), titleIn),
        field(t("report.from"), fromIn, undefined, undefined, "reports.range"),
        field(t("report.to"), toIn),
        field("ECU", ecuSel.el),
        field(t("report.author"), authorIn),
      ),
      row(
        h("span", { class: "muted" }, `${t("report.quick")}:`),
        button(t("report.last", { n: 5 }), quick(300), { kind: "ghost" }),
        button(t("report.last", { n: 15 }), quick(900), { kind: "ghost" }),
        button(t("report.last", { n: 60 }), quick(3600), { kind: "ghost" }),
        button(t("report.sinceConnect"), sinceConnect, { kind: "ghost" }),
      ),
      field(t("report.notes"), notesIn, undefined, "field-wide"),
      h(
        "fieldset",
        null,
        h("legend", null, t("report.include"), infoIcon("reports.include")),
        h(
          "div",
          { class: "inline wrap" },
          inc.map(({ c }) => c.el),
        ),
      ),
      h(
        "fieldset",
        null,
        h("legend", null, t("report.traceFormats"), infoIcon("reports.trace_formats")),
        h(
          "div",
          { class: "inline wrap" },
          fmts.map(({ c }) => c.el),
        ),
      ),
      h(
        "details",
        null,
        h("summary", null, t("report.runs")),
        h("p", { class: "muted small" }, t("report.runsHint")),
        runsBox,
      ),
      row(button(t("report.create"), create, { kind: "primary" })),
      resultBox,
    ),
    card(
      h("span", null, t("report.list"), " ", button(t("common.reload"), loadList, { kind: "ghost" })),
      listBox,
    ),
  );

  return {
    el,
    submit: () => void create(),
    show: () => {
      if (store.reportRange) {
        setRange(store.reportRange.from, store.reportRange.to);
        titleIn.value = t("report.selectionTitle");
        store.reportRange = null;
        toast(t("report.rangeAdopted"), "info");
      }
      void loadList().catch(toastError);
      void loadRuns().catch(() => undefined);
    },
    destroy: ecuSel.dispose,
  };
}
