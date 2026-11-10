import { toastError } from "../components/toast";
import { button, checkbox, field, select, textInput } from "../components/ui";
import { debounce, h } from "../dom";
import { t } from "../i18n";
import * as storage from "../storage";
import type { LogEntry } from "../types";
import type { AppCtx, View } from "../view";

const MAX_ROWS = 2000;
const LEVELS = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

interface LogFilter {
  channel: string;
  level: string;
  q: string;
  cid: string;
}

/** Lokaler Abgleich eines Live-Eintrags mit dem Filter (Level = Mindestlevel). */
export function logMatches(e: LogEntry, f: LogFilter): boolean {
  if (f.channel && e.channel !== f.channel) return false;
  if (f.level && LEVELS.indexOf(e.level) < LEVELS.indexOf(f.level)) return false;
  if (f.cid && e.cid !== f.cid) return false;
  if (f.q && !`${e.msg} ${e.logger}`.toLowerCase().includes(f.q.toLowerCase())) return false;
  return true;
}

export function createLogsView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const f: LogFilter = {
    channel: "",
    level: "",
    q: "",
    cid: "",
    ...storage.load<Partial<LogFilter>>("logs.filter", {}),
  };
  const chanSel = select(
    [
      { value: "", label: t("common.all") },
      ...["app", "comm", "audit", "test"].map((c) => ({ value: c, label: c })),
    ],
    f.channel,
  );
  const levelSel = select(
    [{ value: "", label: t("common.all") }, ...LEVELS.map((l) => ({ value: l, label: `≥ ${l}` }))],
    f.level,
  );
  const qIn = textInput(f.q, { type: "search", placeholder: t("logs.search"), class: "w-md" });
  const cidIn = textInput(f.cid, { placeholder: "req_…", class: "w-sm mono" });
  const live = checkbox(t("logs.live"), true);
  const tbody = h("tbody");
  const scroller = h(
    "div",
    { class: "trace-scroll" },
    h(
      "table",
      { class: "tbl logs-table" },
      h(
        "thead",
        null,
        h(
          "tr",
          null,
          [t("trace.col.time"), "Level", t("trace.col.channel"), "Logger", t("common.message"), "CID"].map(
            (c) => h("th", null, c),
          ),
        ),
      ),
      tbody,
    ),
  );

  const rowFor = (e: LogEntry) =>
    h(
      "tr",
      { class: `lv-${e.level.toLowerCase()}` },
      h("td", { class: "mono nowrap" }, e.time?.slice(11) ?? ""),
      h("td", null, h("span", { class: ["badge", `lvl-${e.level.toLowerCase()}`] }, e.level)),
      h("td", null, e.channel),
      h("td", { class: "small muted" }, e.logger),
      h("td", { class: "logmsg" }, e.msg),
      h(
        "td",
        null,
        e.cid
          ? h(
              "a",
              {
                href: "#",
                class: "mono small",
                onclick: (ev: Event) => {
                  ev.preventDefault();
                  cidIn.value = e.cid ?? "";
                  void reload();
                },
              },
              e.cid,
            )
          : "",
      ),
    );

  const atBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 40;

  const append = (entries: LogEntry[]) => {
    const stick = atBottom();
    const frag = document.createDocumentFragment();
    for (const e of entries) frag.appendChild(rowFor(e));
    tbody.appendChild(frag);
    let excess = tbody.childElementCount - MAX_ROWS;
    while (excess-- > 0 && tbody.firstElementChild) tbody.firstElementChild.remove();
    if (stick) scroller.scrollTop = scroller.scrollHeight;
  };

  const readFilter = () => {
    f.channel = chanSel.value;
    f.level = levelSel.value;
    f.q = qIn.value.trim();
    f.cid = cidIn.value.trim();
    storage.save("logs.filter", f);
  };

  const reload = async () => {
    readFilter();
    try {
      const r = await api.get<{ items: LogEntry[] }>("/logs", {
        channel: f.channel || undefined,
        level: f.level || undefined,
        q: f.q || undefined,
        cid: f.cid || undefined,
        limit: 1000,
      });
      tbody.replaceChildren();
      append(r.items);
      scroller.scrollTop = scroller.scrollHeight;
    } catch (exc) {
      toastError(exc);
    }
  };
  const debounced = debounce(() => void reload(), 300);
  for (const c of [chanSel, levelSel]) c.addEventListener("change", debounced);
  for (const c of [qIn, cidIn]) c.addEventListener("input", debounced);

  // Live-Anhängen (gebündelt pro Frame)
  let pending: LogEntry[] = [];
  let raf: number | null = null;
  const off = store.on("log", (e) => {
    if (!live.input.checked) return;
    const entry = e["entry"] as LogEntry | undefined;
    if (!entry || !logMatches(entry, f)) return;
    pending.push(entry);
    if (raf === null)
      raf = requestAnimationFrame(() => {
        raf = null;
        const p = pending;
        pending = [];
        append(p);
      });
  });

  const el = h(
    "div",
    { class: "trace-view" },
    h(
      "div",
      { class: "toolbar filters" },
      field(t("trace.col.channel"), chanSel, undefined, undefined, "logs.channel"),
      field("Level", levelSel),
      field(t("logs.search"), qIn),
      field(t("logs.cid"), cidIn, undefined, undefined, "logs.cid"),
      live.el,
      button(t("common.reload"), reload),
      button(
        t("logs.resetFilter"),
        () => {
          chanSel.value = levelSel.value = qIn.value = cidIn.value = "";
          void reload();
        },
        { kind: "ghost" },
      ),
    ),
    scroller,
  );

  let loaded = false;
  return {
    el,
    show: () => {
      if (!loaded) {
        loaded = true;
        void reload();
      }
    },
    destroy: off,
  };
}
