import { createTimechart, statsTiles, type StatsSummary } from "../components/timechart";
import { ecuSelect } from "../components/ecu-select";
import { card, field, table } from "../components/ui";
import { h, replace } from "../dom";
import { t } from "../i18n";
import { timeLabel, topicColor } from "../timechart-math";
import type { TimelineEvent } from "../components/timechart";
import type { AppCtx, View } from "../view";

export function createTimechartView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const toReport = (from: number, to: number) => {
    store.reportRange = { from, to };
    ctx.navigate("reports");
  };
  const chart = createTimechart(
    api,
    { metric: "uds", group_by: "type", window_s: 300, showEvents: true },
    { onReport: toReport },
  );
  const statsBox = h("div");
  const eventsBox = h("div");
  const ecuSel = ecuSelect(store, { allowNone: true, local: true });
  let statsEcu: string | null = null;
  ecuSel.el.addEventListener("change", () => {
    statsEcu = ecuSel.el.value || null;
    void loadStats();
  });

  const loadStats = async () => {
    const [s, ev] = await Promise.all([
      api.get<StatsSummary>("/stats/summary", { from: "-15m", ecu: statsEcu ?? undefined }),
      api.get<{ items: TimelineEvent[] }>("/events", {
        from: "-15m",
        limit: 100,
        ecu: statsEcu ?? undefined,
      }),
    ]);
    replace(statsBox, statsTiles(s));
    const items = [...ev.items].reverse().slice(0, 100);
    replace(
      eventsBox,
      table<TimelineEvent>(
        [
          {
            key: "ts",
            label: t("trace.col.time"),
            render: (e) => h("span", { class: "mono" }, timeLabel(e.ts)),
          },
          {
            key: "topic",
            label: "Topic",
            render: (e) =>
              h(
                "span",
                { class: "badge", style: { background: topicColor(e.topic), color: "var(--surface)" } },
                e.topic,
              ),
          },
          { key: "type", label: t("did.type"), render: (e) => e.type ?? "" },
          { key: "ecu", label: "ECU", render: (e) => e.ecu ?? "" },
          {
            key: "text",
            label: t("common.message"),
            render: (e) =>
              [e.service, e.request, e.nrc_name, e.text, e.msg, e["name"] as string | undefined]
                .filter(Boolean)
                .join(" · "),
          },
        ],
        items,
        { rowClass: (e) => (e.type === "negative" ? "row-fail" : "") },
      ),
    );
  };
  const timer = setInterval(() => {
    if (el.isConnected) void loadStats().catch(() => undefined);
  }, 4000);

  const el = h(
    "div",
    { class: "view-grid" },
    card(t("tc.title"), h("p", { class: "muted small" }, t("tc.hint")), chart.el),
    card(h("span", null, t("stats.title"), " ", field("ECU", ecuSel.el)), statsBox),
    card(t("tc.eventsTitle"), eventsBox),
  );
  return {
    el,
    show: () => {
      void chart.refresh();
      void loadStats().catch(() => undefined);
    },
    destroy: () => {
      clearInterval(timer);
      chart.dispose();
      ecuSel.dispose();
    },
  };
}
