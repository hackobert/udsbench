import { infoIcon } from "../help";
import { button, checkbox, field, modal, select, textInput } from "../components/ui";
import { toast, toastError } from "../components/toast";
import { debounce, h, replace } from "../dom";
import { t, type MsgKey } from "../i18n";
import * as storage from "../storage";
import {
  matchesSearch,
  toWsFilter,
  traceCells,
  traceRowClass,
  TRACE_COLUMNS,
  type TraceFilterState,
  type TraceRowCells,
  type TraceView,
} from "../trace-format";
import type { TraceBatch, TraceFrame, TraceItem, TraceMessage } from "../types";
import type { AppCtx, View } from "../view";
import { ReconnectingSocket, type WsState } from "../ws";

export const MAX_DOM_ROWS = 2000;
const MAX_BUFFER = 20000;

const COL_LABEL: Record<keyof TraceRowCells, MsgKey> = {
  time: "trace.col.time",
  channel: "trace.col.channel",
  dir: "trace.col.dir",
  id: "trace.col.id",
  dlc: "trace.col.dlc",
  data: "trace.col.data",
  ascii: "trace.col.ascii",
  text: "trace.col.text",
};

const DEFAULT_FILTER: TraceFilterState = {
  ids: "",
  data_contains: "",
  direction: "",
  services: "",
  only_uds: false,
};

export function createTraceView(ctx: AppCtx): View {
  const { api } = ctx;
  let view: TraceView =
    storage.load<TraceView>("trace.view", "frames") === "messages" ? "messages" : "frames";
  const filter: TraceFilterState = {
    ...DEFAULT_FILTER,
    ...storage.load<Partial<TraceFilterState>>("trace.filter", {}),
  };
  const hidden = new Set<string>(storage.load<string[]>("trace.hiddenCols", []));
  const buffers: { frames: TraceFrame[]; messages: TraceMessage[] } = { frames: [], messages: [] };
  const maxSeq = { frames: -1, messages: -1 };
  const bookmarks = new Map<number, string>();
  let pending: TraceItem[] = [];
  let rafId: number | null = null;
  let paused = false;
  let dropped = 0;
  let t0: number | null = null;
  let search = "";
  let selected: TraceItem | null = null;
  let historyLoaded = false;

  // --- DOM ----------------------------------------------------------------------------------
  const tbody = h("tbody");
  const theadRow = h(
    "tr",
    null,
    h("th", { class: "c-bm" }, "★"),
    TRACE_COLUMNS.map((c) => h("th", { class: `c-${c}` }, t(COL_LABEL[c]))),
  );
  const tableEl = h("table", { class: "tbl trace-table mono" }, h("thead", null, theadRow), tbody);
  const scroller = h("div", { class: "trace-scroll", tabindex: "0" }, tableEl);
  const detail = h("div", { class: "trace-detail" });
  const counters = h("span", { class: "trace-counters muted" });
  const droppedEl = h("span", { class: "badge badge-warn", hidden: true });
  const wsBadge = h("span", { class: "badge" });
  const selBar = h("div", { class: "trace-selbar", hidden: true });

  const applyColumnClasses = () => {
    for (const c of TRACE_COLUMNS) tableEl.classList.toggle(`hide-${c}`, hidden.has(c));
  };

  const viewBtns = (["frames", "messages"] as TraceView[]).map((v) =>
    h(
      "button",
      { class: ["seg-btn", v === view ? "active" : null], onclick: () => setView(v) },
      t(v === "frames" ? "trace.viewFrames" : "trace.viewMessages"),
    ),
  );
  const pauseBtn = button(t("trace.pause"), () => togglePause(), { title: t("trace.pauseHint") });

  const idsIn = textInput(filter.ids, { placeholder: "700, 708", class: "w-sm" });
  const dataIn = textInput(filter.data_contains, { placeholder: "F1 00", class: "w-sm" });
  const dirSel = select(
    [
      { value: "", label: t("trace.dirAll") },
      { value: "tx", label: "TX" },
      { value: "rx", label: "RX" },
    ],
    filter.direction,
  );
  const svcIn = textInput(filter.services, { placeholder: "22, 2E", class: "w-xs" });
  const onlyUds = checkbox(t("trace.onlyUds"), filter.only_uds, undefined, undefined, "trace.only_uds");
  const searchIn = textInput("", { placeholder: t("trace.search"), type: "search", class: "w-md" });

  const readFilter = () => {
    filter.ids = idsIn.value;
    filter.data_contains = dataIn.value;
    filter.direction = dirSel.value as TraceFilterState["direction"];
    filter.services = svcIn.value;
    filter.only_uds = onlyUds.input.checked;
    storage.save("trace.filter", filter);
  };
  const sendFilter = () => {
    readFilter();
    sock.send({ action: "filter", filter: toWsFilter(filter) });
  };
  const applyFilter = () => {
    sendFilter();
    // Puffer neu (server-seitig gefiltert) laden
    buffers.frames = [];
    buffers.messages = [];
    maxSeq.frames = maxSeq.messages = -1;
    void loadHistory();
  };
  const debouncedApply = debounce(applyFilter, 400);
  for (const inp of [idsIn, dataIn, svcIn]) {
    inp.addEventListener("input", debouncedApply);
    inp.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") applyFilter();
    });
  }
  dirSel.addEventListener("change", applyFilter);
  onlyUds.input.addEventListener("change", applyFilter);
  searchIn.addEventListener(
    "input",
    debounce(() => {
      search = searchIn.value.trim();
      rebuild();
    }, 200),
  );

  const colMenu = h(
    "details",
    { class: "dropdown" },
    h("summary", { class: "btn" }, t("trace.columns")),
    h(
      "div",
      { class: "dropdown-body" },
      TRACE_COLUMNS.map(
        (c) =>
          checkbox(t(COL_LABEL[c]), !hidden.has(c), (v) => {
            if (v) hidden.delete(c);
            else hidden.add(c);
            storage.save("trace.hiddenCols", [...hidden]);
            applyColumnClasses();
          }).el,
      ),
    ),
  );
  const exportMenu = h(
    "details",
    { class: "dropdown" },
    h("summary", { class: "btn" }, t("trace.export")),
    h(
      "div",
      { class: "dropdown-body" },
      ["csv", "asc", "candump", "jsonl"].map((fmt) =>
        button(fmt.toUpperCase(), () => api.download("/trace/export", { format: fmt }, `trace.${fmt}`), {
          kind: "ghost",
        }),
      ),
    ),
  );

  const legend = h(
    "div",
    { class: "legend trace-legend" },
    (
      [
        ["t-req", "trace.legend.req"],
        ["t-pos", "trace.legend.pos"],
        ["t-neg", "trace.legend.neg"],
        ["t-ff", "FF"],
        ["t-cf", "CF"],
        ["t-fc", "FC"],
      ] as [string, string][]
    ).map(([cls, key]) =>
      h(
        "span",
        { class: "legend-item" },
        h("span", { class: ["swatch", cls] }),
        key.includes(".") ? t(key as MsgKey) : key,
      ),
    ),
  );

  const el = h(
    "div",
    { class: "trace-view" },
    h(
      "div",
      { class: "toolbar" },
      h("div", { class: "seg" }, viewBtns),
      infoIcon("trace.view"),
      pauseBtn,
      infoIcon("trace.pause"),
      button(t("trace.clear"), () => clearAll(), { kind: "danger" }),
      exportMenu,
      infoIcon("trace.export"),
      colMenu,
      searchIn,
      wsBadge,
      droppedEl,
      infoIcon("trace.dropped"),
      counters,
    ),
    h(
      "div",
      { class: "toolbar filters" },
      field(t("trace.filterIds"), idsIn, undefined, undefined, "trace.ids"),
      field(t("trace.filterData"), dataIn, undefined, undefined, "trace.data_contains"),
      field(t("trace.filterDir"), dirSel),
      field(t("trace.filterServices"), svcIn, undefined, undefined, "trace.services"),
      onlyUds.el,
      button(t("trace.applyFilter"), applyFilter),
      button(
        t("trace.resetFilter"),
        () => {
          idsIn.value = dataIn.value = svcIn.value = "";
          dirSel.value = "";
          onlyUds.input.checked = false;
          applyFilter();
        },
        { kind: "ghost" },
      ),
      legend,
    ),
    selBar,
    h("div", { class: "trace-main" }, scroller, detail),
  );

  // --- Rendering ----------------------------------------------------------------------------
  const rowFor = (item: TraceItem): HTMLTableRowElement => {
    const c = traceCells(item, t0 ?? item.ts);
    const bm = bookmarks.has(item.seq);
    const tr = h(
      "tr",
      { class: traceRowClass(item) + (bm ? " bookmarked" : ""), dataset: { seq: String(item.seq) } },
      h(
        "td",
        { class: "c-bm", title: bm ? bookmarks.get(item.seq) : t("trace.bookmarkAdd") },
        bm ? "★" : "☆",
      ),
      TRACE_COLUMNS.map((k) => h("td", { class: `c-${k}` }, c[k])),
    );
    return tr;
  };

  const atBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 40;

  const updateCounters = () => {
    counters.textContent = t("trace.counters", {
      shown: tbody.childElementCount,
      total: buffers[view].length,
    });
    droppedEl.hidden = dropped === 0;
    droppedEl.textContent = t("trace.dropped", { n: dropped });
  };

  const appendRows = (items: TraceItem[]) => {
    const stick = atBottom();
    const frag = document.createDocumentFragment();
    const visible = items.filter((i) => matchesSearch(i, search));
    for (const it of visible.slice(-MAX_DOM_ROWS)) frag.appendChild(rowFor(it));
    tbody.appendChild(frag);
    let excess = tbody.childElementCount - MAX_DOM_ROWS;
    while (excess-- > 0 && tbody.firstElementChild) tbody.firstElementChild.remove();
    if (stick) scroller.scrollTop = scroller.scrollHeight;
    updateCounters();
  };

  const rebuild = () => {
    pending = [];
    tbody.replaceChildren();
    const all = (buffers[view] as TraceItem[]).filter((i) => matchesSearch(i, search));
    appendRows(all.slice(-MAX_DOM_ROWS));
    scroller.scrollTop = scroller.scrollHeight;
  };

  const flush = () => {
    rafId = null;
    if (!pending.length) return;
    const items = pending;
    pending = [];
    appendRows(items);
  };
  const scheduleFlush = () => {
    if (rafId === null) rafId = requestAnimationFrame(flush);
  };

  const push = (kind: TraceView, items: TraceItem[]) => {
    const fresh = items.filter((i) => i.seq > maxSeq[kind]);
    if (!fresh.length) return;
    maxSeq[kind] = fresh[fresh.length - 1]?.seq ?? maxSeq[kind];
    if (t0 === null) t0 = fresh[0]?.ts ?? null;
    const buf = buffers[kind] as TraceItem[];
    buf.push(...fresh);
    if (buf.length > MAX_BUFFER) buf.splice(0, buf.length - MAX_BUFFER);
    if (kind === view) {
      pending.push(...fresh);
      scheduleFlush();
    }
  };

  const onBatch = (b: TraceBatch) => {
    if (b.dropped) dropped += b.dropped;
    if (b.frames?.length) push("frames", b.frames);
    if (b.messages?.length) push("messages", b.messages);
    if (b.dropped) updateCounters();
  };

  const setView = (v: TraceView) => {
    view = v;
    storage.save("trace.view", v);
    viewBtns.forEach((b, i) => b.classList.toggle("active", (i === 0 ? "frames" : "messages") === v));
    pending = [];
    rebuild();
  };

  const togglePause = () => {
    paused = !paused;
    sock.send({ action: paused ? "pause" : "resume" });
    pauseBtn.textContent = paused ? t("trace.resume") : t("trace.pause");
    pauseBtn.classList.toggle("btn-warn", paused);
    el.classList.toggle("paused", paused);
  };

  const clearAll = async () => {
    try {
      await api.del("/trace");
    } catch (exc) {
      toastError(exc);
    }
    buffers.frames = [];
    buffers.messages = [];
    pending = [];
    dropped = 0;
    t0 = null;
    selected = null;
    replace(detail);
    rebuild();
  };

  const loadHistory = async () => {
    const q = toWsFilter(filter);
    const query = {
      limit: 1000,
      ids: Array.isArray(q["ids"]) ? (q["ids"] as string[]).join(",") : undefined,
      services: Array.isArray(q["services"]) ? (q["services"] as string[]).join(",") : undefined,
      direction: (q["direction"] as string | undefined) ?? undefined,
      data_contains: (q["data_contains"] as string | undefined) ?? undefined,
      only_uds: q["only_uds"] ? "true" : undefined,
    };
    try {
      const [fr, ms] = await Promise.all([
        api.get<{ items: TraceFrame[]; bookmarks: { seq: number; note: string }[] }>("/trace", {
          ...query,
          view: "frames",
        }),
        api.get<{ items: TraceMessage[] }>("/trace", { ...query, view: "messages" }),
      ]);
      for (const b of fr.bookmarks ?? []) bookmarks.set(b.seq, b.note);
      if (t0 === null) t0 = fr.items[0]?.ts ?? ms.items[0]?.ts ?? null;
      push("frames", fr.items);
      push("messages", ms.items);
      rebuild();
      historyLoaded = true;
    } catch (exc) {
      toastError(exc);
    }
  };

  // Zeitbereich per Ziehen über Zeilen markieren → Report aus Auswahl
  let dragFrom: number | null = null;
  let dragMoved = false;
  let range: { from: number; to: number } | null = null;
  const itemBySeq = (seq: number) => (buffers[view] as TraceItem[]).find((i) => i.seq === seq);
  const markRange = (a: number, b: number) => {
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    for (const tr of tbody.children) {
      const seq = Number((tr as HTMLElement).dataset["seq"]);
      tr.classList.toggle("in-range", seq >= lo && seq <= hi);
    }
  };
  const clearRange = () => {
    range = null;
    selBar.hidden = true;
    for (const tr of tbody.querySelectorAll("tr.in-range")) tr.classList.remove("in-range");
  };
  tbody.addEventListener("mousedown", (ev) => {
    const tr = (ev.target as HTMLElement).closest("tr");
    if (!tr || ev.button !== 0 || (ev.target as HTMLElement).closest(".c-bm")) return;
    dragFrom = Number(tr.dataset["seq"]);
    dragMoved = false;
  });
  tbody.addEventListener("mouseover", (ev) => {
    if (dragFrom === null) return;
    const tr = (ev.target as HTMLElement).closest("tr");
    if (!tr) return;
    const seq = Number(tr.dataset["seq"]);
    if (seq !== dragFrom) {
      dragMoved = true;
      ev.preventDefault();
      window.getSelection()?.removeAllRanges();
    }
    markRange(dragFrom, seq);
  });
  window.addEventListener("mouseup", (ev) => {
    if (dragFrom === null) return;
    const tr = (ev.target as HTMLElement).closest?.("tr");
    const endSeq = tr && tbody.contains(tr) ? Number(tr.dataset["seq"]) : dragFrom;
    const a = itemBySeq(dragFrom);
    const b = itemBySeq(endSeq);
    const moved = dragMoved;
    dragFrom = null;
    if (!moved || !a || !b) return;
    const from = Math.min(a.ts, b.ts);
    const to = Math.max(
      a.kind === "message" ? (a.ts_end ?? a.ts) : a.ts,
      b.kind === "message" ? (b.ts_end ?? b.ts) : b.ts,
    );
    range = { from: from - 0.001, to: to + 0.001 };
    selBar.hidden = false;
    replace(
      selBar,
      h(
        "span",
        null,
        t("trace.selection", { n: tbody.querySelectorAll("tr.in-range").length, s: (to - from).toFixed(3) }),
      ),
      " ",
      button(
        t("report.fromSelection"),
        () => {
          if (!range) return;
          ctx.store.reportRange = { ...range };
          ctx.navigate("reports");
        },
        { kind: "primary" },
      ),
      button("×", clearRange, { kind: "ghost" }),
    );
  });

  // Lesezeichen & Details
  tbody.addEventListener("click", (ev) => {
    const target = ev.target as HTMLElement;
    const tr = target.closest("tr");
    if (!tr) return;
    const seq = Number(tr.dataset["seq"]);
    const item = (buffers[view] as TraceItem[]).find((i) => i.seq === seq);
    if (!item || dragMoved) return;
    if (target.closest(".c-bm")) {
      addBookmark(item, tr);
      return;
    }
    for (const r of tbody.querySelectorAll("tr.selected")) r.classList.remove("selected");
    tr.classList.add("selected");
    selected = item;
    replace(
      detail,
      h(
        "div",
        { class: "trace-detail-head" },
        h("strong", null, `#${item.seq}`),
        button(
          "×",
          () => {
            selected = null;
            replace(detail);
          },
          { kind: "ghost" },
        ),
      ),
      h("pre", { class: "json" }, JSON.stringify(selected, null, 2)),
    );
  });

  const addBookmark = (item: TraceItem, tr: HTMLElement) => {
    const note = textInput("", { placeholder: t("trace.bookmarkNote") });
    const doSave = async () => {
      try {
        await api.post("/trace/bookmarks", { seq: item.seq, note: note.value });
        bookmarks.set(item.seq, note.value);
        tr.classList.add("bookmarked");
        const cell = tr.querySelector(".c-bm");
        if (cell) cell.textContent = "★";
        toast(t("trace.bookmarkSaved", { seq: item.seq }), "success");
        close();
      } catch (exc) {
        toastError(exc);
      }
    };
    note.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") void doSave();
    });
    const close = modal(t("trace.bookmarkAdd"), field(t("trace.bookmarkNote"), note), [
      button(t("common.save"), doSave, { kind: "primary" }),
    ]);
  };

  // --- WebSocket ----------------------------------------------------------------------------
  const setWsState = (s: WsState) => {
    wsBadge.textContent = t(`ws.${s}` as MsgKey);
    wsBadge.className = `badge ${s === "open" ? "badge-ok" : s === "connecting" ? "badge-warn" : "badge-fail"}`;
  };
  const sock = new ReconnectingSocket(() => api.wsUrl("/ws/trace"), {
    onOpen: () => {
      sock.send({ action: "filter", filter: toWsFilter(filter) });
      if (paused) sock.send({ action: "pause" });
    },
    onMessage: (d) => {
      const msg = d as { type?: string };
      if (msg.type === "batch") onBatch(d as TraceBatch);
    },
    onClose: (code) => {
      if (code === 4401) api.onUnauthorized?.();
    },
    onStateChange: setWsState,
  });
  setWsState("closed");
  applyColumnClasses();
  updateCounters();

  let started = false;
  return {
    el,
    show: () => {
      requestAnimationFrame(() => (scroller.scrollTop = scroller.scrollHeight));
      if (!started) {
        started = true;
        // erst den Puffer laden, dann live anhängen (Duplikate werden über seq verworfen)
        void (historyLoaded ? Promise.resolve() : loadHistory()).finally(() => sock.start());
      }
    },
    togglePause,
    destroy: () => {
      sock.stop();
      if (rafId !== null) cancelAnimationFrame(rafId);
    },
  };
}
