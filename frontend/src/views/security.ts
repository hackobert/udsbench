import { infoIcon } from "../help";
import { ecuSelect } from "../components/ecu-select";
import { summaryText } from "../components/run-log";
import { toast, toastError } from "../components/toast";
import {
  badge,
  button,
  card,
  checkbox,
  field,
  jsonView,
  kv,
  row,
  statusBadge,
  table,
  textInput,
  udsResultView,
} from "../components/ui";
import { h, replace } from "../dom";
import { parseJson } from "../editor";
import { t } from "../i18n";
import type { LibraryItem, RunInfo, TestCaseResult, UdsResult } from "../types";
import type { AppCtx, View } from "../view";

interface Provider {
  id: string;
  type: string;
  description?: string;
  params?: Record<string, unknown>;
}

interface NrcRow {
  id: string;
  name: string;
  expected: string;
  actual: string;
  status: string;
  message: string;
}

/** Erwarteten/tatsächlichen NRC je Testfall aus dem Lauf-Report ermitteln. */
export function nrcRows(cases: LibraryItem[], run: RunInfo | null): NrcRow[] {
  const fmt = (v: unknown) =>
    typeof v === "number"
      ? `0x${v.toString(16).toUpperCase().padStart(2, "0")}`
      : v === null || v === undefined
        ? "–"
        : String(v);
  return cases.map((c) => {
    const res: TestCaseResult | undefined = run?.tests?.find((x) => x.id === c.id);
    let expected = String(c.description ?? "").replace(/^Erwartet:\s*/i, "");
    let actual = "–";
    for (const s of res?.steps ?? []) {
      const a = s.assertions.find((x) => x.name === "nrc" || x.name.startsWith("nrc"));
      if (a) {
        expected = fmt(a.expected);
        actual = fmt(a.actual);
      } else if (s.nrc !== null && s.nrc !== undefined && actual === "–") {
        actual = fmt(s.nrc);
      }
    }
    return {
      id: c.id,
      name: c.name ?? c.id,
      expected,
      actual,
      status: res?.status ?? (run ? "skipped" : "–"),
      message: res?.message ?? "",
    };
  });
}

export function createSecurityView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const ecuSel = ecuSelect(store);
  const levelSel = h("select");
  const providerSel = h("select");
  const paramsIn = textInput("{}", { class: "mono" });
  const seedIn = textInput("", { class: "mono", placeholder: "AA BB CC DD" });
  const keyIn = textInput("", { class: "mono", placeholder: t("sec.keyHint") });
  const switchSession = checkbox(t("sec.switchSession"), true);
  const outBox = h("div");
  const unlockBox = h("div");
  const nrcBox = h("div");
  const nrcHead = h("div");
  let cases: LibraryItem[] = [];
  let nrcRunId: string | null = null;

  const renderLevels = () => {
    const ecu = store.ecu();
    levelSel.replaceChildren();
    const levels = ecu?.security_levels ?? [];
    for (const l of levels)
      levelSel.appendChild(
        h(
          "option",
          { value: String(l.level) },
          `0x${l.level.toString(16).toUpperCase().padStart(2, "0")} ${l.name} (${l.provider})`,
        ),
      );
    if (!levels.length) levelSel.appendChild(h("option", { value: "1" }, "0x01"));
  };

  const loadProviders = async () => {
    const r = await api.get<{ providers: Provider[]; types: string[] }>("/security/providers");
    providerSel.replaceChildren(h("option", { value: "" }, t("sec.providerDefault")));
    for (const p of r.providers)
      providerSel.appendChild(
        h("option", { value: p.id }, `${p.id} (${p.type})${p.description ? ` – ${p.description}` : ""}`),
      );
  };

  const level = () => Number(levelSel.value || 1);
  const params = (): Record<string, unknown> | null => {
    const r = parseJson<Record<string, unknown>>(paramsIn.value || "{}");
    if (!r.ok) {
      toast(`Parameter: ${r.message}`, "error");
      return null;
    }
    return r.value;
  };

  const requestSeed = async () => {
    const r = await api.post<{ result: UdsResult; seed: string | null; already_unlocked: boolean }>(
      "/security/seed",
      {
        ecu: store.selectedEcu,
        level: level(),
      },
    );
    if (r.seed && !r.seed.includes("*")) seedIn.value = r.seed;
    replace(
      outBox,
      kv([
        ["Seed", h("code", { class: "mono" }, r.seed ?? "–")],
        [t("sec.alreadyUnlocked"), r.already_unlocked ? t("common.yes") : t("common.no")],
      ]),
      r.seed?.includes("*") ? h("div", { class: "muted small" }, t("sec.masked")) : null,
      udsResultView(r.result),
    );
  };

  const computeKey = async () => {
    const p = params();
    if (!p) return;
    const r = await api.post<{ key: string; length: number }>("/security/compute-key", {
      ecu: store.selectedEcu,
      level: level(),
      seed: seedIn.value,
      provider: providerSel.value || null,
      params: p,
    });
    keyIn.value = r.key;
    replace(
      outBox,
      kv([
        ["Key", h("code", { class: "mono" }, r.key)],
        [t("common.length"), String(r.length)],
      ]),
    );
  };

  const sendKey = async () => {
    const body: Record<string, unknown> = { ecu: store.selectedEcu, level: level() };
    if (keyIn.value.trim()) body["key"] = keyIn.value.trim();
    else if (seedIn.value.trim()) body["seed"] = seedIn.value.trim();
    const r = await api.post<{ unlocked?: boolean; result?: UdsResult; [k: string]: unknown }>(
      "/security/key",
      body,
    );
    replace(
      outBox,
      r.unlocked !== undefined
        ? badge(r.unlocked ? t("sec.unlocked") : t("sec.notUnlocked"), r.unlocked ? "ok" : "fail")
        : null,
      r.result ? udsResultView(r.result) : jsonView(r),
    );
    await store.refreshEcus();
  };

  const unlock = async () => {
    const p = params();
    if (!p) return;
    const r = await api.post<{
      unlocked: boolean;
      message: string;
      steps: { step: string; result: UdsResult }[];
    }>("/security/unlock", {
      ecu: store.selectedEcu,
      level: level(),
      provider: providerSel.value || null,
      params: p,
      switch_session: switchSession.input.checked,
    });
    replace(
      unlockBox,
      h(
        "div",
        { class: "result-head" },
        badge(r.unlocked ? t("sec.unlocked") : t("sec.notUnlocked"), r.unlocked ? "ok" : "fail"),
        ` ${r.message}`,
      ),
      h(
        "ol",
        { class: "unlock-steps" },
        (r.steps ?? []).map((s) =>
          h(
            "li",
            null,
            h("strong", null, s.step),
            " ",
            h("code", { class: "mono" }, `${s.result?.request ?? ""} → ${s.result?.response ?? "–"}`),
            " ",
            h("span", { class: "muted" }, s.result?.decoded?.text ?? ""),
          ),
        ),
      ),
    );
    await store.refreshEcus();
  };

  // --- NRC-Testsuite -------------------------------------------------------------------------------
  const loadCases = async () => {
    cases = await api.post<LibraryItem[]>("/security/nrc-suite/cases", {
      ecu: store.selectedEcu,
      level: level(),
    });
    renderNrc(null);
  };
  const renderNrc = (run: RunInfo | null) => {
    const rows = nrcRows(cases, run);
    replace(
      nrcHead,
      run
        ? h(
            "div",
            { class: "result-head" },
            statusBadge(run.status),
            ` ${run.run_id} · ${summaryText(run.summary)}`,
          )
        : null,
    );
    replace(
      nrcBox,
      table<NrcRow>(
        [
          { key: "name", label: t("sec.case"), render: (r) => h("span", { title: r.id }, r.name) },
          { key: "exp", label: t("sec.expectedNrc"), render: (r) => h("code", null, r.expected) },
          { key: "act", label: t("sec.actualNrc"), render: (r) => h("code", null, r.actual) },
          {
            key: "st",
            label: t("common.result"),
            render: (r) => (r.status === "–" ? "–" : statusBadge(r.status)),
          },
          { key: "msg", label: t("common.message"), render: (r) => r.message },
        ],
        rows,
        {
          rowClass: (r) =>
            r.status === "passed"
              ? "row-ok"
              : r.status === "failed" || r.status === "error"
                ? "row-fail"
                : "",
        },
      ),
    );
  };
  const runNrc = async () => {
    if (!cases.length) await loadCases();
    const r = await api.post<RunInfo>("/security/nrc-suite/run", { ecu: store.selectedEcu, level: level() });
    nrcRunId = r.run_id;
    replace(nrcHead, statusBadge(r.status), ` ${r.run_id}`);
  };
  const offRun = store.on("run", (e) => {
    if (!nrcRunId || e["run_id"] !== nrcRunId) return;
    if (e["state"] === "finished" || e["state"] === "progress") {
      void api
        .get<RunInfo>(`/runs/${encodeURIComponent(nrcRunId)}`)
        .then(renderNrc)
        .catch(toastError);
    }
  });

  const el = h(
    "div",
    { class: "view-grid" },
    h(
      "div",
      { class: "two-col" },
      card(
        t("sec.manual"),
        h(
          "div",
          { class: "grid" },
          field(t("header.ecu"), ecuSel.el),
          field(t("sec.level"), levelSel, undefined, undefined, "security.level"),
        ),
        h(
          "div",
          { class: "grid" },
          field(t("sec.provider"), providerSel, undefined, undefined, "security.provider"),
          field(t("sec.params"), paramsIn, t("sec.paramsHint")),
        ),
        row(button(t("sec.requestSeed"), requestSeed, { kind: "primary" })),
        field("Seed", seedIn, undefined, "field-wide"),
        row(button(t("sec.computeKey"), computeKey)),
        field("Key", keyIn, undefined, "field-wide"),
        row(button(t("sec.sendKey"), sendKey, { kind: "primary" })),
        outBox,
      ),
      card(
        h("span", null, t("sec.auto"), infoIcon("security.unlock")),
        switchSession.el,
        row(button(t("sec.unlock"), unlock, { kind: "primary" })),
        unlockBox,
      ),
    ),
    card(
      h("span", null, t("sec.nrcSuite"), infoIcon("security.nrc_suite")),
      h("p", { class: "muted" }, t("sec.nrcHint")),
      row(button(t("sec.loadCases"), loadCases), button(t("sec.runSuite"), runNrc, { kind: "primary" })),
      nrcHead,
      nrcBox,
    ),
  );

  const off = store.changed.on((k) => {
    if (k === "ecus" || k === "selectedEcu") {
      const prev = levelSel.value;
      renderLevels();
      if (prev && [...levelSel.options].some((o) => o.value === prev)) levelSel.value = prev;
    }
  });
  renderLevels();
  return {
    el,
    show: () => void loadProviders().catch(toastError),
    destroy: () => {
      off();
      offRun();
      ecuSel.dispose();
    },
  };
}
