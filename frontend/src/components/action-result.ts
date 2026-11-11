/** Kompakte Anzeige eines Aktionsergebnisses (Dashboard-Knopf / „Testen“). */
import { h, replace } from "../dom";
import { t } from "../i18n";
import type { Store } from "../store";
import type { RunSummary, StepRecord, UdsResult } from "../types";
import { summaryText } from "./run-log";
import { hexAscii, statusBadge } from "./ui";

export type ResultTone = "ok" | "fail" | "run" | "muted";

/** Ton (grün/rot/…) eines Aktionsergebnisses. */
export function resultTone(res: Record<string, unknown>): ResultTone {
  const r = res["result"] as UdsResult | null | undefined;
  if (r) {
    if (r.error || r.negative) return "fail";
    if (r.positive || r.suppress_positive) return "ok";
  }
  const status = String(res["status"] ?? "");
  if (["failed", "error", "cancelled"].includes(status)) return "fail";
  if (["started", "running", "queued"].includes(status)) return "run";
  if (["passed", "ok"].includes(status)) return "ok";
  return "muted";
}

export function actionResultView(res: Record<string, unknown>, store: Store): HTMLElement {
  const tone = resultTone(res);
  const step = res["step"] as StepRecord | undefined;
  const r = res["result"] as UdsResult | null | undefined;
  const runId = res["run_id"] as string | undefined;
  const parts: (HTMLElement | string | null)[] = [];
  const resp = r?.response ?? step?.response ?? null;
  if (resp) parts.push(hexAscii(resp, { inline: true }));
  const text = r?.decoded?.nrc_description
    ? `NRC ${r.decoded.nrc_hex ?? ""} ${r.decoded.nrc_name ?? ""} – ${r.decoded.nrc_description}`
    : (r?.decoded?.text ??
      step?.decoded?.text ??
      step?.message ??
      (res["message"] as string | undefined) ??
      null);
  if (text) parts.push(h("span", { class: "small" }, text));
  const ms = r?.elapsed_ms ?? step?.elapsed_ms;
  if (ms !== null && ms !== undefined) parts.push(h("span", { class: "muted small" }, `${ms} ms`));
  if (r?.error) parts.push(h("span", { class: "small" }, r.error));
  const runBox = h("span", { class: "small" });
  if (runId) {
    parts.push(runBox);
    replace(runBox, statusBadge(String(res["status"] ?? "queued")), ` ${runId}`);
    const off = store.on("run", (e) => {
      if (e["run_id"] !== runId) return;
      if (!el.isConnected) {
        off();
        return;
      }
      const st = String(e["status"] ?? e["state"] ?? "");
      replace(runBox, statusBadge(st), ` ${summaryText(e["summary"] as RunSummary | undefined)}`);
      el.className = `action-result tone-${["passed"].includes(st) ? "ok" : ["failed", "error", "cancelled"].includes(st) ? "fail" : "run"}`;
      if (e["state"] === "finished") off();
    });
  }
  if (!parts.length) parts.push(h("span", { class: "small" }, String(res["status"] ?? t("common.ok"))));
  const el = h("div", { class: ["action-result", `tone-${tone}`] }, parts);
  return el;
}
