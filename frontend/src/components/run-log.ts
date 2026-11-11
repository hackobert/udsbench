/** Live-Schrittprotokoll eines Laufs über die Events run.step / run. */
import { h, replace } from "../dom";
import { t } from "../i18n";
import type { Store } from "../store";
import type { EventMsg, RunInfo, RunSummary, StepRecord } from "../types";
import { assertionsView, hexAscii, statusBadge } from "./ui";

export interface RunLog {
  el: HTMLElement;
  attach: (runId: string) => void;
  dispose: () => void;
}

export function stepLine(s: StepRecord): HTMLElement {
  const line = h(
    "details",
    { class: ["log-step", `st-${s.status}`], style: { marginLeft: `${s.depth * 1.2}rem` } },
    h(
      "summary",
      null,
      statusBadge(s.status),
      h("span", { class: "log-step-name" }, ` ${s.name || s.action}`),
      s.request ? h("code", { class: "mono" }, ` → ${s.request}`) : null,
      s.response ? h("span", null, " ← ", hexAscii(s.response, { inline: true })) : null,
      s.elapsed_ms !== null && s.elapsed_ms !== undefined
        ? h("span", { class: "muted" }, ` (${s.elapsed_ms} ms)`)
        : null,
      s.message ? h("span", { class: "step-msg" }, ` – ${s.message}`) : null,
    ),
    s.decoded?.text ? h("div", { class: "muted small" }, s.decoded.text) : null,
    assertionsView(s.assertions ?? []),
  );
  return line;
}

export function summaryText(s: RunSummary | undefined): string {
  if (!s) return "";
  return t("run.summary", {
    total: s.total,
    passed: s.passed,
    failed: s.failed,
    error: s.error,
    skipped: s.skipped,
  });
}

export function runLog(store: Store, onFinished?: (runId: string, status: string) => void): RunLog {
  const head = h("div", { class: "run-head" });
  const list = h("div", { class: "log-steps" });
  const el = h("div", { class: "run-log" }, head, list);
  let runId: string | null = null;
  // Ereignisse puffern: Events können vor der HTTP-Antwort mit der run_id eintreffen
  const recent: EventMsg[] = [];
  const remember = (e: EventMsg) => {
    recent.push(e);
    if (recent.length > 2000) recent.splice(0, recent.length - 2000);
  };

  const onStep = (e: EventMsg) => {
    if (e["run_id"] !== runId) return;
    const s = e["step"] as StepRecord | undefined;
    if (s) {
      list.appendChild(stepLine(s));
      list.scrollTop = list.scrollHeight;
    }
  };
  const onRun = (e: EventMsg) => {
    if (e["run_id"] !== runId) return;
    const status = String(e["status"] ?? e["state"] ?? "");
    const summary = e["summary"] as RunSummary | undefined;
    const planned = Number(e["planned"] ?? 0);
    const done = summary ? summary.total : 0;
    replace(
      head,
      statusBadge(status),
      h("span", null, ` ${runId}`),
      summary ? h("span", { class: "muted" }, ` · ${summaryText(summary)}`) : null,
      planned ? h("progress", { max: String(planned), value: String(done) }) : null,
    );
    if (e["state"] === "finished") onFinished?.(runId ?? "", status);
  };
  const off1 = store.on("run.step", (e) => {
    remember(e);
    onStep(e);
  });
  const off2 = store.on("run", (e) => {
    remember(e);
    onRun(e);
  });

  return {
    el,
    attach: (id: string) => {
      runId = id;
      list.replaceChildren();
      replace(head, statusBadge("queued"), h("span", null, ` ${id}`));
      for (const e of recent) {
        if (e["run_id"] !== id) continue;
        if (e.topic === "run.step") onStep(e);
        else onRun(e);
      }
    },
    dispose: () => {
      off1();
      off2();
    },
  };
}

/** Kurzinfo aus einer Startantwort. */
export function runStarted(r: RunInfo): string {
  return `${r.run_id} (${r.kind}: ${r.target})`;
}
