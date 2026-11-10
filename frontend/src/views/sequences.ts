import { infoIcon } from "../help";
import { libraryEditor } from "../components/library-editor";
import { runLog } from "../components/run-log";
import { toast, toastError } from "../components/toast";
import { badge, button, card, field, row, table } from "../components/ui";
import { h, replace } from "../dom";
import { parseJson } from "../editor";
import { t } from "../i18n";
import type { LibraryItem, RunInfo } from "../types";
import type { AppCtx, View } from "../view";

export function createSequencesView(ctx: AppCtx): View {
  const { api, store } = ctx;
  let items: LibraryItem[] = [];
  let current: LibraryItem | null = null;
  const listBox = h("div");
  const log = runLog(store, (_id, status) =>
    toast(t("run.finished", { status }), status === "passed" ? "success" : "warning"),
  );
  const varsIn = h("textarea", { class: "mono", rows: "2", spellcheck: "false" });
  varsIn.value = "{}";
  const selInfo = h("div", { class: "muted" }, t("seq.none"));

  const editor = libraryEditor(
    api,
    "sequences",
    () => ({
      id: "my_sequence",
      name: "Meine Sequenz",
      ecu: store.selectedEcu ?? "ecu_a",
      vars: {},
      steps: [{ session: 3 }, { read_did: "0xF100" }, { log: "fertig" }],
    }),
    async () => load(),
  );

  const load = async () => {
    items = await api.get<LibraryItem[]>("/sequences");
    renderList();
  };

  const renderList = () =>
    replace(
      listBox,
      table<LibraryItem>(
        [
          { key: "id", label: "ID", render: (s) => h("strong", null, s.id) },
          { key: "name", label: t("common.name"), render: (s) => s.name ?? "" },
          { key: "ecu", label: "ECU", render: (s) => s.ecu ?? "–" },
          {
            key: "steps",
            label: t("seq.steps"),
            render: (s) => String((s["steps"] as unknown[] | undefined)?.length ?? 0),
          },
          { key: "pkg", label: t("common.package"), render: (s) => badge(s.package ?? "–") },
          {
            key: "run",
            label: "",
            render: (s) =>
              button(
                t("seq.run"),
                (ev) => {
                  ev.stopPropagation();
                  return run(s);
                },
                { kind: "primary" },
              ),
          },
        ],
        items,
        {
          onRow: (s) => {
            current = s;
            editor.edit(s);
            varsIn.value = JSON.stringify(s["vars"] ?? {});
            replace(selInfo, t("seq.selected", { id: s.id }));
            renderList();
          },
          rowClass: (s) => (s.id === current?.id ? "row-selected" : ""),
        },
      ),
    );

  const run = async (s: LibraryItem | null = current) => {
    if (!s) return;
    const vars = parseJson<Record<string, unknown>>(varsIn.value || "{}");
    if (!vars.ok) {
      toast(`vars: ${vars.message}`, "error");
      return;
    }
    const r = await api.post<RunInfo>(`/sequences/${encodeURIComponent(s.id)}/run`, { vars: vars.value });
    log.attach(r.run_id);
  };

  const el = h(
    "div",
    { class: "two-col" },
    h(
      "div",
      { class: "col" },
      card(h("span", null, t("seq.list"), " ", button(t("common.reload"), load, { kind: "ghost" })), listBox),
      card(
        t("seq.runTitle"),
        selInfo,
        field(t("msg.vars"), varsIn, t("seq.varsHint"), "field-wide"),
        row(button(t("seq.runSelected"), () => run(), { kind: "primary" })),
        log.el,
      ),
    ),
    h(
      "div",
      { class: "col" },
      card(h("span", null, t("editor.title"), infoIcon("sequences.editor")), editor.el),
    ),
  );
  return {
    el,
    show: () => void load().catch(toastError),
    submit: () => void run().catch(toastError),
    destroy: () => log.dispose(),
  };
}
