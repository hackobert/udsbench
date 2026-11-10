import { infoIcon } from "../help";
import { libraryEditor } from "../components/library-editor";
import { addMessageButton } from "./dashboards";
import { toastError } from "../components/toast";
import {
  badge,
  button,
  card,
  checkbox,
  field,
  kv,
  row,
  stepView,
  table,
  textInput,
  udsResultView,
} from "../components/ui";
import { h, replace } from "../dom";
import { parseJson } from "../editor";
import { t } from "../i18n";
import type { LibraryItem, StepRunResponse } from "../types";
import type { AppCtx, View } from "../view";

export function createMessagesView(ctx: AppCtx): View {
  const { api, store } = ctx;
  let items: LibraryItem[] = [];
  let current: LibraryItem | null = null;
  const listBox = h("div");
  const detailBox = h("div");
  const filterIn = textInput("", { type: "search", placeholder: t("common.filter"), class: "w-md" });
  filterIn.addEventListener("input", () => renderList());

  const editor = libraryEditor(
    api,
    "messages",
    () => ({
      id: "my_message",
      name: "Meine Botschaft",
      ecu: store.selectedEcu ?? "ecu_a",
      payload: "22 F1 00",
      functional: false,
    }),
    async (id) => {
      await load();
      const it = items.find((i) => i.id === id);
      if (it) select(it, false);
    },
  );

  const load = async () => {
    items = await api.get<LibraryItem[]>("/messages");
    renderList();
  };

  const renderList = () => {
    const q = filterIn.value.toLowerCase();
    const shown = items.filter(
      (i) => !q || `${i.id} ${i.name ?? ""} ${String(i["payload"] ?? "")}`.toLowerCase().includes(q),
    );
    replace(
      listBox,
      table<LibraryItem>(
        [
          { key: "id", label: "ID", render: (m) => h("strong", null, m.id) },
          { key: "name", label: t("common.name"), render: (m) => m.name ?? "" },
          { key: "ecu", label: "ECU", render: (m) => m.ecu ?? "–" },
          {
            key: "payload",
            label: t("uds.payload"),
            render: (m) => h("code", { class: "mono" }, String(m["payload"] ?? "")),
          },
          { key: "f", label: "", render: (m) => (m["functional"] ? badge("func") : null) },
          {
            key: "pkg",
            label: t("common.package"),
            render: (m) => badge(m.package ?? "–", m.package === "workspace" ? "run" : ""),
          },
        ],
        shown,
        { onRow: (m) => select(m), rowClass: (m) => (m.id === current?.id ? "row-selected" : "") },
      ),
    );
  };

  const select = (m: LibraryItem, toEditor = true) => {
    current = m;
    renderList();
    if (toEditor) editor.edit(m);
    const varsIn = h("textarea", { class: "mono", rows: "3", spellcheck: "false" });
    varsIn.value = JSON.stringify(m["vars"] ?? {}, null, 0);
    const funcBox = checkbox(t("uds.functional"), Boolean(m["functional"]));
    const out = h("div");
    const getVars = (): Record<string, unknown> | null => {
      const r = parseJson<Record<string, unknown>>(varsIn.value || "{}");
      if (!r.ok) {
        replace(out, h("div", { class: "error-box" }, `vars: ${r.message}`));
        return null;
      }
      return r.value;
    };
    const preview = async () => {
      const vars = getVars();
      if (!vars) return;
      const r = await api.post<{ payload: string; description: string }>(
        `/messages/${encodeURIComponent(m.id)}/preview`,
        {
          vars,
          ecu: store.selectedEcu && !m.ecu ? store.selectedEcu : undefined,
        },
      );
      replace(
        out,
        kv([
          [t("uds.payload"), h("code", { class: "mono" }, r.payload)],
          [t("common.description"), r.description],
        ]),
      );
    };
    const send = async () => {
      const vars = getVars();
      if (!vars) return;
      try {
        const r = await api.post<StepRunResponse>(`/messages/${encodeURIComponent(m.id)}/send`, {
          vars,
          functional: funcBox.input.checked,
        });
        replace(
          out,
          r.result ? udsResultView(r.result) : stepView(r.step),
          r.result ? stepView(r.step) : null,
        );
      } catch (exc) {
        toastError(exc);
      }
    };
    replace(
      detailBox,
      kv([
        ["ID", m.id],
        [t("common.name"), m.name ?? ""],
        [t("common.description"), m.description ?? ""],
        ["ECU", m.ecu ?? "–"],
        [t("uds.payload"), h("code", { class: "mono" }, String(m["payload"] ?? ""))],
        [t("common.package"), m.package ?? "–"],
        [t("msg.expect"), m["expect"] ? h("code", null, JSON.stringify(m["expect"])) : "–"],
      ]),
      field(t("msg.vars"), varsIn, t("msg.varsHint"), "field-wide"),
      funcBox.el,
      row(
        button(t("msg.preview"), preview),
        button(t("msg.send"), send, { kind: "primary" }),
        infoIcon("messages.to_dashboard"),
        button(t("dash.addToDashboard"), () => addMessageButton(ctx, m.id, m.name ?? m.id), {
          kind: "ghost",
        }),
      ),
      out,
    );
    sendCurrent = send;
  };
  let sendCurrent: (() => Promise<void>) | null = null;

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
          t("msg.library"),
          " ",
          filterIn,
          " ",
          button(t("common.reload"), load, { kind: "ghost" }),
        ),
        listBox,
      ),
      card(h("span", null, t("msg.detail"), infoIcon("messages.payload")), detailBox),
    ),
    h("div", { class: "col" }, card(t("editor.title"), editor.el)),
  );
  const off = store.on("packages", () => void load().catch(() => undefined));
  return {
    el,
    show: () => void load().catch(toastError),
    submit: () => void sendCurrent?.(),
    destroy: off,
  };
}
