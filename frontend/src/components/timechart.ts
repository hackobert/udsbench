import { infoIcon } from "../help";
/** Timechart: gestapelte Balken je Gruppe, Latenzlinie, Ereignis-Spur, Brush-Auswahl, Live-Aktualisierung. */
import type { ApiClient } from "../api";
import { h, replace, svg } from "../dom";
import { t } from "../i18n";
import {
  groupColor,
  niceMax,
  orderGroups,
  pixelToTime,
  scaleLinear,
  stackBuckets,
  ticks,
  timeLabel,
  timeTicks,
  topicColor,
  type Timeseries,
} from "../timechart-math";
import { toastError } from "./toast";
import { button, checkbox, select, textInput } from "./ui";

export interface TimechartConfig {
  metric: "uds" | "frames" | "events";
  group_by: string;
  window_s: number;
  bucket_s?: number | null;
  ecu?: string | null;
  showEvents?: boolean;
  showLatency?: boolean;
  /** Kompakt (Dashboard-Panel): keine Bedienleiste außer Pause. */
  compact?: boolean;
  height?: number;
}

export interface TimelineEvent {
  ts: number;
  topic: string;
  type?: string;
  ecu?: string | null;
  request?: string;
  nrc_name?: string | null;
  text?: string;
  msg?: string;
  service?: string;
  [key: string]: unknown;
}

export interface Timechart {
  el: HTMLElement;
  refresh: () => Promise<void>;
  dispose: () => void;
}

export const GROUP_OPTIONS: Record<string, string[]> = {
  uds: ["type", "service", "ecu", "nrc_name", "sid"],
  frames: ["type", "dir", "ecu", "id", "channel"],
  events: ["topic", "type"],
};

export function eventLabel(e: TimelineEvent): string {
  const parts = [timeLabel(e.ts), e.topic, e.type, e.ecu, e.service, e.request, e.nrc_name, e.text ?? e.msg];
  return parts.filter((p) => p !== null && p !== undefined && p !== "").join(" · ");
}

const M = { l: 40, r: 40, t: 8, b: 22 };
const LANE_H = 18;

/** SVG der Timechart rendern (ohne Interaktion). Exportiert für Tests. */
export function renderChartSvg(
  data: Timeseries,
  events: TimelineEvent[],
  opts: { width: number; height: number; hidden: Set<string>; showLatency: boolean; showEvents: boolean },
): SVGSVGElement {
  const { width, height } = opts;
  const lane = opts.showEvents ? LANE_H + 6 : 0;
  const plotH = Math.max(20, height - M.t - M.b - lane);
  const plotW = Math.max(20, width - M.l - M.r);
  const groups = orderGroups(data.groups, [
    "positive",
    "negative",
    "timeout",
    "suppressed",
    "error",
    "request",
  ]);
  const stacked = stackBuckets(data.buckets, groups, opts.hidden);
  const peak = Math.max(0, ...stacked.map((s) => s.total));
  // Zählwerte: ganzzahlige Achse (mind. 0…4)
  const yMax = peak <= 4 ? 4 : niceMax(peak);
  const x = scaleLinear(data.from, data.to, M.l, M.l + plotW);
  const y = scaleLinear(0, yMax, M.t + plotH, M.t);
  const bw = Math.max(1, (plotW * data.bucket_s) / Math.max(1, data.to - data.from) - 1);
  const root = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}`, class: "tc-svg", role: "img" });

  // Gitter + Y-Achse
  for (const v of ticks(yMax, yMax % 4 === 0 ? 4 : 5)) {
    root.appendChild(svg("line", { x1: M.l, x2: M.l + plotW, y1: y(v), y2: y(v), class: "tc-grid" }));
    root.appendChild(
      svg("text", { x: M.l - 4, y: y(v) + 3, class: "tc-axis", "text-anchor": "end" }, String(v)),
    );
  }
  // X-Achse
  for (const tt of timeTicks(data.from, data.to)) {
    root.appendChild(
      svg("line", { x1: x(tt), x2: x(tt), y1: M.t, y2: M.t + plotH, class: "tc-grid tc-grid-v" }),
    );
    root.appendChild(
      svg("text", { x: x(tt), y: height - 6, class: "tc-axis", "text-anchor": "middle" }, timeLabel(tt)),
    );
  }
  // Balken
  const bars = svg("g", { class: "tc-bars" });
  stacked.forEach((b, i) => {
    for (const s of b.segments) {
      bars.appendChild(
        svg("rect", {
          x: x(b.t),
          y: y(s.y1),
          width: bw,
          height: Math.max(0.5, y(s.y0) - y(s.y1)),
          style: `fill:${groupColor(s.group)}`,
          "data-bucket": i,
          "data-group": s.group,
        }),
      );
    }
  });
  root.appendChild(bars);
  // Latenzlinie (rechte Achse)
  if (opts.showLatency) {
    const pts = data.buckets.filter((b) => typeof b.latency_avg_ms === "number");
    if (pts.length) {
      const lMax = niceMax(Math.max(...pts.map((b) => b.latency_avg_ms ?? 0)));
      const ly = scaleLinear(0, lMax, M.t + plotH, M.t);
      const d = pts
        .map(
          (b, i) => `${i ? "L" : "M"}${(x(b.t) + bw / 2).toFixed(1)},${ly(b.latency_avg_ms ?? 0).toFixed(1)}`,
        )
        .join(" ");
      root.appendChild(svg("path", { d, class: "tc-latency" }));
      root.appendChild(svg("text", { x: M.l + plotW + 4, y: M.t + 8, class: "tc-axis" }, `${lMax} ms`));
    }
  }
  // Ereignis-Spur
  if (opts.showEvents) {
    const ly = M.t + plotH + 4;
    const laneG = svg("g", { class: "tc-lane" });
    laneG.appendChild(svg("rect", { x: M.l, y: ly, width: plotW, height: LANE_H, class: "tc-lane-bg" }));
    events.forEach((e, i) => {
      if (e.ts < data.from || e.ts > data.to) return;
      const cx = x(e.ts);
      const isMarker = e.topic === "marker";
      laneG.appendChild(
        svg(
          isMarker ? "rect" : "circle",
          isMarker
            ? {
                x: cx - 1.5,
                y: ly,
                width: 3,
                height: LANE_H,
                style: `fill:${topicColor(e.topic)}`,
                "data-event": i,
              }
            : {
                cx,
                cy: ly + LANE_H / 2,
                r: e.type === "negative" || e.topic === "log" ? 4 : 3,
                style: `fill:${e.type === "negative" ? "var(--err)" : topicColor(e.topic)}`,
                "data-event": i,
              },
        ),
      );
      if (isMarker)
        root.appendChild(svg("line", { x1: cx, x2: cx, y1: M.t, y2: M.t + plotH, class: "tc-marker-line" }));
    });
    root.appendChild(laneG);
    // X-Beschriftung unter die Spur verschieben
    root.setAttribute("height", String(height));
  }
  root.dataset["x0"] = String(M.l);
  root.dataset["pw"] = String(plotW);
  return root;
}

export function createTimechart(
  api: ApiClient,
  initial: TimechartConfig,
  hooks: { onReport?: (from: number, to: number) => void } = {},
): Timechart {
  const cfg: TimechartConfig = { showEvents: true, showLatency: false, ...initial };
  const hidden = new Set<string>();
  let data: Timeseries | null = null;
  let events: TimelineEvent[] = [];
  let paused = false;
  let fixed: { from: number; to: number } | null = null;
  let selection: { from: number; to: number } | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;

  const chartBox = h("div", { class: "tc-chart" });
  const legend = h("div", { class: "tc-legend" });
  const tooltip = h("div", { class: "tc-tooltip", hidden: true });
  const selInfo = h("div", { class: "tc-selection" });
  const status = h("span", { class: "muted small" });

  // Bedienleiste
  const metricSel = select(
    [
      { value: "uds", label: "UDS" },
      { value: "frames", label: "Frames" },
      { value: "events", label: t("tc.events") },
    ],
    cfg.metric,
  );
  const groupSel = h("select");
  const fillGroups = () => {
    groupSel.replaceChildren(
      ...(GROUP_OPTIONS[metricSel.value] ?? ["type"]).map((g) =>
        h("option", { value: g, selected: g === cfg.group_by }, g),
      ),
    );
  };
  fillGroups();
  const windowSel = select(
    [
      { value: "60", label: "1 min" },
      { value: "300", label: "5 min" },
      { value: "900", label: "15 min" },
      { value: "3600", label: "60 min" },
      { value: "free", label: t("tc.free") },
    ],
    String(cfg.window_s),
  );
  const fromIn = h("input", { type: "datetime-local", step: "1", hidden: true });
  const toIn = h("input", { type: "datetime-local", step: "1", hidden: true });
  const latBox = checkbox(t("tc.latency"), Boolean(cfg.showLatency), (v) => {
    cfg.showLatency = v;
    draw();
  });
  const evBox = checkbox(t("tc.eventLane"), Boolean(cfg.showEvents), (v) => {
    cfg.showEvents = v;
    void refresh();
  });
  const pauseBtn = button(t("trace.pause"), () => {
    paused = !paused;
    pauseBtn.textContent = paused ? t("trace.resume") : t("trace.pause");
    pauseBtn.classList.toggle("btn-warn", paused);
    if (!paused) void refresh();
  });
  const markerIn = textInput("", { placeholder: t("tc.markerText"), class: "w-sm" });
  const markerBtn = button(t("tc.marker"), async () => {
    await api.post("/events/marker", { text: markerIn.value.trim() || t("tc.markerDefault") });
    markerIn.value = "";
    await refresh();
  });

  metricSel.addEventListener("change", () => {
    cfg.metric = metricSel.value as TimechartConfig["metric"];
    cfg.group_by = (GROUP_OPTIONS[cfg.metric] ?? ["type"])[0] ?? "type";
    fillGroups();
    hidden.clear();
    void refresh();
  });
  groupSel.addEventListener("change", () => {
    cfg.group_by = groupSel.value;
    hidden.clear();
    void refresh();
  });
  const toLocal = (ts: number) => {
    const d = new Date(ts * 1000 - new Date().getTimezoneOffset() * 60000);
    return d.toISOString().slice(0, 19);
  };
  windowSel.addEventListener("change", () => {
    if (windowSel.value === "free") {
      const now = Date.now() / 1000;
      fixed = { from: now - cfg.window_s, to: now };
      fromIn.value = toLocal(fixed.from);
      toIn.value = toLocal(fixed.to);
    } else {
      fixed = null;
      cfg.window_s = Number(windowSel.value);
    }
    fromIn.hidden = toIn.hidden = fixed === null;
    void refresh();
  });
  const onFixed = () => {
    const f = new Date(fromIn.value).getTime() / 1000;
    const to = new Date(toIn.value).getTime() / 1000;
    if (Number.isFinite(f) && Number.isFinite(to) && to > f) {
      fixed = { from: f, to };
      void refresh();
    }
  };
  fromIn.addEventListener("change", onFixed);
  toIn.addEventListener("change", onFixed);

  const toolbar = cfg.compact
    ? h("div", { class: "tc-toolbar" }, status)
    : h(
        "div",
        { class: "toolbar tc-toolbar" },
        metricSel,
        infoIcon("timechart.metric"),
        groupSel,
        infoIcon("timechart.group_by"),
        windowSel,
        fromIn,
        toIn,
        latBox.el,
        evBox.el,
        pauseBtn,
        markerIn,
        markerBtn,
        infoIcon("timechart.marker"),
        status,
      );

  const el = h(
    "div",
    { class: ["timechart", cfg.compact ? "tc-compact" : null] },
    toolbar,
    h("div", { class: "tc-wrap" }, chartBox, tooltip),
    legend,
    selInfo,
  );

  const range = () => {
    if (fixed) return fixed;
    const now = Date.now() / 1000;
    return { from: now - cfg.window_s, to: now };
  };

  const refresh = async () => {
    const r = range();
    const q = {
      metric: cfg.metric,
      group_by: cfg.group_by,
      from: r.from.toFixed(3),
      to: r.to.toFixed(3),
      bucket_s: cfg.bucket_s ?? undefined,
      ecu: cfg.ecu ?? undefined,
    };
    try {
      const [ts, ev] = await Promise.all([
        api.get<Timeseries>("/stats/timeseries", q),
        cfg.showEvents
          ? api.get<{ items: TimelineEvent[] }>("/events", { from: q.from, to: q.to, limit: 500, ecu: q.ecu })
          : Promise.resolve({ items: [] as TimelineEvent[] }),
      ]);
      data = ts;
      events = ev.items;
      status.textContent = `${t("tc.total", { n: ts.total })} · ${t("tc.bucket", { s: ts.bucket_s })}`;
      draw();
    } catch (exc) {
      status.textContent = (exc as Error).message;
      if (!cfg.compact) toastError(exc);
    }
  };

  const draw = () => {
    if (!data) return;
    const width = Math.max(240, chartBox.clientWidth || el.clientWidth || 800);
    const height = cfg.height ?? (cfg.compact ? 150 : 260);
    const node = renderChartSvg(data, events, {
      width,
      height,
      hidden,
      showLatency: Boolean(cfg.showLatency),
      showEvents: Boolean(cfg.showEvents),
    });
    attachInteraction(node);
    replace(chartBox, node);
    renderLegend();
  };

  const renderLegend = () => {
    if (!data) return;
    const groups = orderGroups(data.groups, [
      "positive",
      "negative",
      "timeout",
      "suppressed",
      "error",
      "request",
    ]);
    replace(
      legend,
      groups.map((g) =>
        h(
          "button",
          {
            class: ["tc-legend-item", hidden.has(g) ? "off" : null],
            title: t("tc.toggle"),
            onclick: () => {
              if (hidden.has(g)) hidden.delete(g);
              else hidden.add(g);
              draw();
            },
          },
          h("span", { class: "swatch", style: { background: groupColor(g) } }),
          `${g} (${data?.groups[g] ?? 0})`,
        ),
      ),
    );
  };

  const attachInteraction = (node: SVGSVGElement) => {
    if (!data) return;
    const d = data;
    const x0 = Number(node.dataset["x0"]);
    const pw = Number(node.dataset["pw"]);
    let dragStart: number | null = null;
    const brush = svg("rect", {
      class: "tc-brush",
      y: 0,
      height: node.getAttribute("height"),
      x: 0,
      width: 0,
    });
    node.appendChild(brush);
    const localX = (ev: MouseEvent) => ev.clientX - node.getBoundingClientRect().left;

    node.addEventListener("mousemove", (ev) => {
      const target = ev.target as Element;
      const lx = localX(ev);
      if (dragStart !== null) {
        brush.setAttribute("x", String(Math.min(dragStart, lx)));
        brush.setAttribute("width", String(Math.abs(lx - dragStart)));
      }
      let text = "";
      if (target.hasAttribute("data-event")) {
        const e = events[Number(target.getAttribute("data-event"))];
        if (e) text = eventLabel(e);
      } else if (target.hasAttribute("data-bucket")) {
        const b = d.buckets[Number(target.getAttribute("data-bucket"))];
        if (b) {
          const lines = Object.entries(b.counts).map(([g, n]) => `${g}: ${n}`);
          text = `${timeLabel(b.t)} (+${d.bucket_s}s) · Σ ${b.total}${lines.length ? "\n" + lines.join("\n") : ""}${
            typeof b.latency_avg_ms === "number"
              ? `\nØ ${b.latency_avg_ms} ms / max ${b.latency_max_ms ?? "–"} ms`
              : ""
          }`;
        }
      }
      if (text) {
        tooltip.hidden = false;
        tooltip.textContent = text;
        tooltip.style.left = `${Math.min(lx + 12, (node.clientWidth || 800) - 200)}px`;
        tooltip.style.top = `${ev.offsetY + 10}px`;
      } else tooltip.hidden = true;
    });
    node.addEventListener("mouseleave", () => (tooltip.hidden = true));
    node.addEventListener("mousedown", (ev) => {
      dragStart = localX(ev);
      ev.preventDefault();
    });
    window.addEventListener(
      "mouseup",
      (ev) => {
        if (dragStart === null) return;
        const lx = localX(ev);
        const a = Math.min(dragStart, lx);
        const b = Math.max(dragStart, lx);
        dragStart = null;
        if (b - a < 4) {
          brush.setAttribute("width", "0");
          return;
        }
        setSelection({
          from: pixelToTime(a, d.from, d.to, x0, pw),
          to: pixelToTime(b, d.from, d.to, x0, pw),
        });
      },
      { once: true },
    );
  };

  const setSelection = (s: { from: number; to: number } | null) => {
    selection = s;
    if (!s) {
      replace(selInfo);
      return;
    }
    replace(
      selInfo,
      h(
        "span",
        null,
        t("tc.selection", { from: timeLabel(s.from), to: timeLabel(s.to), s: Math.round(s.to - s.from) }),
      ),
      " ",
      hooks.onReport
        ? button(
            t("report.fromSelection"),
            () => selection && hooks.onReport?.(selection.from, selection.to),
            { kind: "primary" },
          )
        : null,
      button(
        t("tc.zoom"),
        () => {
          if (!selection) return;
          fixed = { ...selection };
          windowSel.value = "free";
          fromIn.hidden = toIn.hidden = false;
          fromIn.value = toLocal(fixed.from);
          toIn.value = toLocal(fixed.to);
          setSelection(null);
          void refresh();
        },
        { kind: "ghost" },
      ),
      button("×", () => setSelection(null), { kind: "ghost" }),
    );
  };

  timer = setInterval(() => {
    if (!paused && !fixed && el.isConnected) void refresh();
  }, 2000);
  let ro: ResizeObserver | null = null;
  if (typeof ResizeObserver !== "undefined") {
    ro = new ResizeObserver(() => draw());
    ro.observe(chartBox);
  }
  void refresh();

  return {
    el,
    refresh,
    dispose: () => {
      if (timer) clearInterval(timer);
      ro?.disconnect();
    },
  };
}

/** Kennzahlen-Kacheln aus /stats/summary. */
export interface StatsSummary {
  uds_requests: number;
  uds_totals: Record<string, number>;
  services: Record<string, number>;
  nrc_counts: Record<string, number>;
  latency: { avg: number | null; min: number | null; max: number | null; count?: number };
  frames: number;
  ecus?: Record<string, number>;
}

export function statsTiles(s: StatsSummary): HTMLElement {
  const tile = (label: string, value: string | number, cls = "") =>
    h(
      "div",
      { class: ["tile", cls] },
      h("div", { class: "tile-value" }, String(value)),
      h("div", { class: "tile-label" }, label),
    );
  const top = (o: Record<string, number>, n = 5) =>
    Object.entries(o)
      .sort((a, b) => b[1] - a[1])
      .slice(0, n);
  return h(
    "div",
    { class: "stats" },
    h(
      "div",
      { class: "tiles" },
      tile(t("stats.requests"), s.uds_requests),
      tile(t("stats.positive"), s.uds_totals["positive"] ?? 0, "tile-ok"),
      tile(t("stats.negative"), s.uds_totals["negative"] ?? 0, "tile-fail"),
      tile(t("stats.timeout"), s.uds_totals["timeout"] ?? 0, "tile-warn"),
      tile(
        t("stats.latencyAvg"),
        s.latency?.avg !== null && s.latency?.avg !== undefined ? `${s.latency.avg} ms` : "–",
      ),
      tile(
        t("stats.latencyMax"),
        s.latency?.max !== null && s.latency?.max !== undefined ? `${s.latency.max} ms` : "–",
      ),
      tile(t("stats.frames"), s.frames),
    ),
    h(
      "div",
      { class: "stats-lists" },
      h(
        "div",
        null,
        h("strong", null, t("stats.services")),
        h(
          "ul",
          null,
          top(s.services).map(([k, v]) => h("li", null, `${k}: ${v}`)),
        ),
      ),
      h(
        "div",
        null,
        h("strong", null, "NRC"),
        h(
          "ul",
          null,
          Object.keys(s.nrc_counts).length
            ? top(s.nrc_counts).map(([k, v]) => h("li", null, `${k}: ${v}`))
            : h("li", { class: "muted" }, "–"),
        ),
      ),
    ),
  );
}
