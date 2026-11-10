import { infoIcon } from "../help";
import { libraryEditor } from "../components/library-editor";
import { runLog, stepLine, summaryText } from "../components/run-log";
import { toast, toastError } from "../components/toast";
import {
  badge,
  button,
  card,
  jsonView,
  kv,
  row,
  statusBadge,
  table,
  tabs,
  textInput,
} from "../components/ui";
import { debounce, formatDateTime, h, replace } from "../dom";
import { t } from "../i18n";
import type { LibraryItem, RunInfo, TestCaseResult } from "../types";
import type { AppCtx, View } from "../view";

export function collectTags(items: LibraryItem[]): string[] {
  const s = new Set<string>();
  for (const i of items) for (const tag of i.tags ?? []) s.add(tag);
  return [...s].sort();
}

export function createTestsView(ctx: AppCtx): View {
  const { api, store } = ctx;
  let tests: LibraryItem[] = [];
  let suites: LibraryItem[] = [];
  let runs: RunInfo[] = [];
  let tagFilter = "";
  let selectedRun: string | null = null;
  const testsBox = h("div");
  const suitesBox = h("div");
  const runsBox = h("div");
  const tagBox = h("div", { class: "tag-filter" });
  const reportBox = h("div", null, h("div", { class: "empty" }, t("test.noReport")));
  const log = runLog(store, (id) => {
    if (id === selectedRun) void showReport(id);
  });
  const searchIn = textInput("", { type: "search", placeholder: t("common.filter"), class: "w-md" });
  searchIn.addEventListener("input", () => renderLists());

  const editor = libraryEditor(
    api,
    "tests",
    () => ({
      id: "my_test",
      name: "Mein Test",
      ecu: store.selectedEcu ?? "ecu_a",
      tags: ["custom"],
      steps: [{ send: { payload: "22 F1 00" }, expect: { positive: true, max_time_ms: 500 } }],
    }),
    async () => load(),
  );
  const suiteEditor = libraryEditor(
    api,
    "testsuites",
    () => ({ id: "my_suite", name: "Meine Suite", tests: [], tags: ["custom"], stop_on_failure: false }),
    async () => load(),
  );

  const load = async () => {
    [tests, suites] = await Promise.all([
      api.get<LibraryItem[]>("/tests"),
      api.get<LibraryItem[]>("/testsuites"),
    ]);
    renderTags();
    renderLists();
    await loadRuns();
  };
  const loadRuns = async () => {
    runs = await api.get<RunInfo[]>("/runs");
    runs.sort((a, b) => b.created - a.created);
    renderRuns();
  };
  const debouncedRuns = debounce(() => void loadRuns().catch(() => undefined), 300);

  const renderTags = () => {
    const tags = collectTags([...tests, ...suites]);
    replace(
      tagBox,
      h("span", { class: "muted" }, `${t("test.tags")}: `),
      ["", ...tags].map((tag) =>
        h(
          "button",
          {
            class: ["chip", tag === tagFilter ? "active" : null],
            onclick: () => {
              tagFilter = tag;
              renderTags();
              renderLists();
            },
          },
          tag || t("common.all"),
        ),
      ),
    );
  };

  const matches = (i: LibraryItem) => {
    if (tagFilter && !(i.tags ?? []).includes(tagFilter)) return false;
    const q = searchIn.value.toLowerCase();
    return !q || `${i.id} ${i.name ?? ""}`.toLowerCase().includes(q);
  };

  const start = async (kind: "tests" | "testsuites", id: string) => {
    const r = await api.post<RunInfo>(`/${kind}/${encodeURIComponent(id)}/run`, {});
    toast(t("test.started", { id: r.run_id }), "info");
    selectedRun = r.run_id;
    log.attach(r.run_id);
    replace(reportBox, log.el);
    await loadRuns();
  };

  const renderLists = () => {
    replace(
      testsBox,
      table<LibraryItem>(
        [
          { key: "id", label: "ID", render: (x) => h("strong", null, x.id) },
          { key: "name", label: t("common.name"), render: (x) => x.name ?? "" },
          { key: "ecu", label: "ECU", render: (x) => x.ecu ?? "–" },
          { key: "tags", label: t("test.tags"), render: (x) => (x.tags ?? []).map((g) => badge(g)) },
          { key: "pkg", label: t("common.package"), render: (x) => x.package ?? "–" },
          {
            key: "run",
            label: "",
            render: (x) =>
              button(
                "▶",
                (ev) => {
                  ev.stopPropagation();
                  return start("tests", x.id);
                },
                { kind: "primary", title: t("test.run") },
              ),
          },
        ],
        tests.filter(matches),
        { onRow: (x) => editor.edit(x) },
      ),
    );
    replace(
      suitesBox,
      table<LibraryItem>(
        [
          { key: "id", label: "ID", render: (x) => h("strong", null, x.id) },
          { key: "name", label: t("common.name"), render: (x) => x.name ?? "" },
          {
            key: "tests",
            label: t("test.tests"),
            render: (x) => {
              const list = (x["tests"] as string[] | undefined) ?? [];
              return list.length ? String(list.length) : t("test.byTags");
            },
          },
          { key: "tags", label: t("test.tags"), render: (x) => (x.tags ?? []).map((g) => badge(g)) },
          { key: "pkg", label: t("common.package"), render: (x) => x.package ?? "–" },
          {
            key: "run",
            label: "",
            render: (x) =>
              button(
                "▶",
                (ev) => {
                  ev.stopPropagation();
                  return start("testsuites", x.id);
                },
                { kind: "primary", title: t("test.runSuite"), cls: `run-suite-${x.id}` },
              ),
          },
        ],
        suites.filter(matches),
        { onRow: (x) => suiteEditor.edit(x) },
      ),
    );
  };

  const renderRuns = () => {
    replace(
      runsBox,
      table<RunInfo>(
        [
          { key: "st", label: t("common.status"), render: (r) => statusBadge(r.status) },
          { key: "id", label: "Run", render: (r) => h("code", null, r.run_id) },
          { key: "kind", label: t("test.kind"), render: (r) => `${r.kind}: ${r.target}` },
          {
            key: "prog",
            label: t("test.progress"),
            render: (r) =>
              h(
                "span",
                { class: "inline" },
                h("progress", { max: String(r.planned || 1), value: String(r.summary.total) }),
                h(
                  "span",
                  { class: "muted small" },
                  ` ${r.summary.total}/${r.planned} · ✔${r.summary.passed} ✖${r.summary.failed + r.summary.error}`,
                ),
              ),
          },
          { key: "time", label: t("test.started_at"), render: (r) => formatDateTime(r.started ?? r.created) },
          { key: "dur", label: t("test.duration"), render: (r) => `${Math.round(r.duration_ms)} ms` },
          {
            key: "act",
            label: "",
            render: (r) =>
              r.status === "running" || r.status === "queued"
                ? button(
                    t("test.cancel"),
                    async (ev) => {
                      ev.stopPropagation();
                      await api.post(`/runs/${encodeURIComponent(r.run_id)}/cancel`);
                    },
                    { kind: "danger" },
                  )
                : null,
          },
        ],
        runs.slice(0, 50),
        {
          onRow: (r) => void showReport(r.run_id),
          rowClass: (r) => (r.run_id === selectedRun ? "row-selected" : ""),
        },
      ),
    );
  };

  const showReport = async (id: string) => {
    selectedRun = id;
    renderRuns();
    const r = await api.get<RunInfo>(`/runs/${encodeURIComponent(id)}`);
    if (r.status === "running" || r.status === "queued") {
      log.attach(id);
      replace(reportBox, log.el);
      return;
    }
    replace(reportBox, reportView(r));
  };

  const reportView = (r: RunInfo): HTMLElement => {
    const env = r.environment ?? {};
    const pkgs = (env["packages"] as { id: string; version: string; hash: string }[] | undefined) ?? [];
    return h(
      "div",
      { class: "report" },
      h(
        "div",
        { class: "result-head" },
        statusBadge(r.status),
        h("strong", null, ` ${r.name}`),
        h("span", { class: "muted" }, ` ${r.run_id}`),
      ),
      row(
        infoIcon("tests.export"),
        button(t("test.downloadJson"), () =>
          api.download(
            `/runs/${encodeURIComponent(r.run_id)}/report`,
            { format: "json" },
            `${r.run_id}.json`,
          ),
        ),
        button(t("test.downloadJunit"), () =>
          api.download(
            `/runs/${encodeURIComponent(r.run_id)}/report`,
            { format: "junit" },
            `${r.run_id}.xml`,
          ),
        ),
        button(
          t("test.openHtml"),
          () => api.openInTab(`/runs/${encodeURIComponent(r.run_id)}/report`, { format: "html" }),
          { cls: "report-html" },
        ),
        button(
          t("test.downloadZip"),
          () =>
            api.download(
              `/runs/${encodeURIComponent(r.run_id)}/report`,
              { format: "zip" },
              `${r.run_id}.zip`,
            ),
          {
            title: t("test.zipHint"),
          },
        ),
      ),
      kv([
        [t("test.summary"), summaryText(r.summary)],
        [t("test.kind"), `${r.kind}: ${r.target}`],
        [t("test.started_at"), formatDateTime(r.started)],
        [t("test.duration"), `${r.duration_ms} ms`],
        [t("common.error"), r.error ?? "–"],
      ]),
      h(
        "div",
        { class: "report-tests" },
        (r.tests ?? []).map((tc) => testCaseView(tc)),
      ),
      (r.suite_steps ?? []).length
        ? h("details", null, h("summary", null, t("test.suiteSteps")), (r.suite_steps ?? []).map(stepLine))
        : null,
      h(
        "details",
        { class: "env" },
        h("summary", null, t("test.environment")),
        kv([
          ["Tool", `${String(env["tool"] ?? "")} ${String(env["version"] ?? "")}`],
          ["Python", String(env["python"] ?? "")],
          [t("test.platform"), String(env["platform"] ?? "")],
          [t("common.packages"), pkgs.map((p) => badge(`${p.id} ${p.version} (${p.hash})`))],
          [t("test.timestamp"), String(env["timestamp"] ?? "")],
        ]),
        jsonView(env),
      ),
    );
  };

  const testCaseView = (tc: TestCaseResult) =>
    h(
      "details",
      { class: ["testcase", `st-${tc.status}`], open: tc.status !== "passed" },
      h(
        "summary",
        null,
        statusBadge(tc.status),
        h("strong", null, ` ${tc.label || tc.name}`),
        h("span", { class: "muted" }, ` ${tc.id} · ${tc.ecu ?? ""} · ${tc.duration_ms} ms`),
        tc.message ? h("span", { class: "step-msg" }, ` – ${tc.message}`) : null,
        tc.expected_result !== "pass"
          ? badge(`${t("test.expectedResult")}: ${tc.expected_result}`, "warn")
          : null,
      ),
      Object.keys(tc.dataset ?? {}).length
        ? h("div", { class: "muted small" }, `Dataset: ${JSON.stringify(tc.dataset)}`)
        : null,
      tc.steps.map(stepLine),
    );

  const offs = [
    store.on("run", () => debouncedRuns()),
    store.on("packages", () => void load().catch(() => undefined)),
  ];

  const editorTabs = tabs([
    { id: "tests", label: t("test.editTest"), render: () => editor.el },
    { id: "suites", label: t("test.editSuite"), render: () => suiteEditor.el },
  ]);

  const el = h(
    "div",
    { class: "two-col" },
    h(
      "div",
      { class: "col" },
      card(
        h(
          "span",
          null,
          t("test.tests"),
          " ",
          searchIn,
          " ",
          button(t("common.reload"), load, { kind: "ghost" }),
        ),
        tagBox,
        testsBox,
      ),
      card(t("test.suites"), suitesBox),
      card(
        h("span", null, t("test.runs"), " ", button(t("common.reload"), loadRuns, { kind: "ghost" })),
        runsBox,
      ),
    ),
    h(
      "div",
      { class: "col" },
      card(t("test.report"), reportBox),
      card(
        h("span", null, t("editor.title"), infoIcon("tests.expect"), infoIcon("tests.datasets")),
        editorTabs.el,
      ),
    ),
  );

  return {
    el,
    show: () => void load().catch(toastError),
    destroy: () => {
      offs.forEach((o) => o());
      log.dispose();
    },
  };
}
