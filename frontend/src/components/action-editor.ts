/** Editor für Dashboard-Aktionen und -Knöpfe (mit Auswahllisten aus der API und „Testen“). */
import {
  ACTION_FIELDS,
  ACTION_TYPES,
  actionToForm,
  buildAction,
  type Action,
  type ActionForm,
  type ButtonDef,
} from "../action-model";
import type { ApiClient } from "../api";
import { h, replace } from "../dom";
import { t, type MsgKey } from "../i18n";
import type { Store } from "../store";
import type { LibraryItem } from "../types";
import { actionResultView } from "./action-result";
import { toastError } from "./toast";
import { button, checkbox, field, modal, select, textInput } from "./ui";

const LISTS: Record<string, string> = {
  message: "/messages",
  sequence: "/sequences",
  test: "/tests",
  suite: "/testsuites",
};
const cache = new Map<string, { at: number; items: LibraryItem[] }>();

async function listFor(api: ApiClient, type: string): Promise<LibraryItem[]> {
  const path = LISTS[type];
  if (!path) return [];
  const c = cache.get(path);
  if (c && Date.now() - c.at < 10000) return c.items;
  const items = await api.get<LibraryItem[]>(path);
  cache.set(path, { at: Date.now(), items });
  return items;
}

export const BUTTON_COLORS = ["primary", "success", "danger", "warning", "default"];

export interface ActionEditor {
  el: HTMLElement;
  get: () => Action;
}

export function actionEditor(api: ApiClient, store: Store, initial: Action | null): ActionEditor {
  const form: ActionForm = actionToForm(initial);
  // neue Aktionen: aktuell gewählte ECU vorbelegen
  if (!initial && store.selectedEcu) form.ecu = store.selectedEcu;
  const typeSel = select(
    ACTION_TYPES.map((a) => ({ value: a, label: t(`action.${a}` as MsgKey) })),
    form.type,
  );
  const body = h("div", { class: "grid" });
  const confirm = checkbox(t("action.confirm"), form.confirm, undefined, undefined, "dashboards.confirm");
  const inputs: Partial<Record<keyof ActionForm, () => string | boolean>> = {};

  const render = async () => {
    form.type = typeSel.value as ActionForm["type"];
    const fields = ACTION_FIELDS[form.type];
    const parts: HTMLElement[] = [];
    for (const k of Object.keys(inputs)) delete inputs[k as keyof ActionForm];
    if (fields.includes("ref")) {
      let control: HTMLElement;
      if (LISTS[form.type]) {
        const items = await listFor(api, form.type).catch(() => [] as LibraryItem[]);
        const sel = select(
          [
            { value: "", label: "—" },
            ...items.map((i) => ({ value: i.id, label: `${i.id}${i.name ? ` – ${i.name}` : ""}` })),
          ],
          form.ref,
        );
        sel.addEventListener("change", () => (form.ref = sel.value));
        control = sel;
        inputs.ref = () => sel.value;
      } else if (form.type === "unlock" || form.type === "session") {
        const ecu = store.ecu(form.ecu || null);
        const opts =
          form.type === "unlock"
            ? (ecu?.security_levels ?? []).map((l) => ({
                value: String(l.level),
                label: `0x${l.level.toString(16).padStart(2, "0")} ${l.name}`,
              }))
            : (ecu?.sessions ?? []).map((s) => ({
                value: String(s.id),
                label: `0x${s.id.toString(16).padStart(2, "0")} ${s.name}`,
              }));
        const sel = select([{ value: "", label: "—" }, ...opts], form.ref);
        sel.addEventListener("change", () => (form.ref = sel.value));
        control = sel;
        inputs.ref = () => sel.value;
      } else {
        const inp = textInput(form.ref, {
          placeholder: form.type === "marker" ? t("tc.markerText") : t("common.name"),
        });
        inp.addEventListener("input", () => (form.ref = inp.value));
        control = inp;
        inputs.ref = () => inp.value;
      }
      parts.push(field(t(form.type === "marker" ? "action.text" : "action.ref"), control));
    }
    if (fields.includes("ecu")) {
      const sel = select(
        [
          { value: "", label: t("action.ecuDefault") },
          ...store.ecus.map((e) => ({ value: e.id, label: e.id })),
        ],
        form.ecu,
      );
      sel.addEventListener("change", () => {
        form.ecu = sel.value;
        if (form.type === "unlock" || form.type === "session") void render();
      });
      inputs.ecu = () => sel.value;
      parts.push(field("ECU", sel));
    }
    const text = (k: "payload" | "can_id" | "channel", label: string, ph = "") => {
      const inp = textInput(String(form[k]), { class: "mono", placeholder: ph });
      inp.addEventListener("input", () => (form[k] = inp.value));
      inputs[k] = () => inp.value;
      parts.push(field(label, inp));
    };
    if (fields.includes("can_id")) text("can_id", "CAN-ID (hex)", "700");
    if (fields.includes("payload")) text("payload", t("uds.payload"), "22 F1 00");
    if (fields.includes("channel")) text("channel", t("conn.channel"), "default");
    if (fields.includes("functional")) {
      const c = checkbox(t("uds.functional"), form.functional, (v) => (form.functional = v));
      inputs.functional = () => c.input.checked;
      parts.push(c.el);
    }
    const area = (k: "vars" | "step" | "report", label: string, ph: string) => {
      const ta = h("textarea", {
        class: "mono",
        rows: k === "vars" ? "2" : "5",
        placeholder: ph,
        spellcheck: "false",
      });
      ta.value = form[k];
      ta.addEventListener("input", () => (form[k] = ta.value));
      inputs[k] = () => ta.value;
      parts.push(field(label, ta, undefined, "field-wide"));
    };
    if (fields.includes("vars")) area("vars", t("msg.vars"), '{"did": 61697}');
    if (fields.includes("step")) area("step", t("action.stepJson"), '{"read_did": "0xF100"}');
    if (fields.includes("report"))
      area("report", t("action.reportJson"), '{"title": "Schnell-Report", "from": "-5m"}');
    replace(body, ...parts);
  };
  typeSel.addEventListener("change", () => void render());
  void render();

  const get = (): Action => {
    for (const [k, fn] of Object.entries(inputs))
      (form as unknown as Record<string, unknown>)[k] = (fn as () => unknown)();
    form.confirm = confirm.input.checked;
    return buildAction(form);
  };

  return {
    el: h(
      "div",
      { class: "action-editor" },
      field(t("action.type"), typeSel, undefined, undefined, "dashboards.button_action"),
      body,
      confirm.el,
    ),
    get,
  };
}

/** Modal zum Bearbeiten eines Knopfs; löst onSave mit dem neuen Knopf aus. */
export function editButtonModal(
  api: ApiClient,
  store: Store,
  btn: ButtonDef | null,
  onSave: (b: ButtonDef) => void,
): void {
  const label = textInput(btn?.label ?? "");
  const colorSel = select(
    [
      ...BUTTON_COLORS.map((c) => ({ value: c, label: t(`color.${c}` as MsgKey) })),
      { value: "custom", label: t("isotp.custom") },
    ],
    btn?.color && !BUTTON_COLORS.includes(btn.color) ? "custom" : (btn?.color ?? "primary"),
  );
  const colorCustom = h("input", {
    type: "color",
    value: btn?.color && btn.color.startsWith("#") ? btn.color : "#2f6fdf",
  });
  const icon = textInput(btn?.icon ?? "", { class: "w-xs", placeholder: "▶" });
  const shortcut = textInput(btn?.shortcut ?? "", { class: "w-sm", placeholder: "ctrl+1" });
  const desc = textInput(btn?.description ?? "");
  const editor = actionEditor(api, store, btn?.action ?? null);
  const err = h("div");
  const testOut = h("div");
  const syncColor = () => (colorCustom.hidden = colorSel.value !== "custom");
  colorSel.addEventListener("change", syncColor);
  syncColor();

  const collect = (): ButtonDef | null => {
    try {
      const action = editor.get();
      replace(err);
      const b: ButtonDef = { label: label.value.trim() || action.type, action };
      const color = colorSel.value === "custom" ? colorCustom.value : colorSel.value;
      if (color && color !== "default") b.color = color;
      if (icon.value.trim()) b.icon = icon.value.trim();
      if (shortcut.value.trim()) b.shortcut = shortcut.value.trim();
      if (desc.value.trim()) b.description = desc.value.trim();
      return b;
    } catch (exc) {
      replace(err, h("div", { class: "error-box" }, (exc as Error).message));
      return null;
    }
  };

  const close = modal(
    btn ? t("dash.editButton") : t("dash.addButton"),
    h(
      "div",
      null,
      h(
        "div",
        { class: "grid" },
        field(t("dash.label"), label),
        field(t("dash.color"), h("div", { class: "inline" }, colorSel, colorCustom)),
        field(t("dash.icon"), icon),
        field(t("dash.shortcut"), shortcut, t("dash.shortcutHint")),
        field(t("common.description"), desc),
      ),
      editor.el,
      err,
      testOut,
    ),
    [
      button(t("dash.test"), async () => {
        const b = collect();
        if (!b) return;
        try {
          const r = await api.post<Record<string, unknown>>("/actions/run", b.action);
          replace(testOut, actionResultView(r, store));
        } catch (exc) {
          toastError(exc);
        }
      }),
      button(
        t("common.save"),
        () => {
          const b = collect();
          if (!b) return;
          onSave(b);
          close();
        },
        { kind: "primary" },
      ),
    ],
  );
}
