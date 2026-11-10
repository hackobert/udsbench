/** JSON-Editor für Arbeitsbereich-Objekte (Botschaften, Sequenzen, Tests, Suiten). */
import type { ApiClient } from "../api";
import { h, replace } from "../dom";
import { parseLibraryItem, renderEditorErrors, toEditorText } from "../editor";
import { t } from "../i18n";
import type { LibraryItem } from "../types";
import { toast } from "./toast";
import { button, row, confirmDialog } from "./ui";

export const WORKSPACE_ID = "workspace";

export type LibraryKind = "messages" | "sequences" | "tests" | "testsuites";

export interface LibraryEditor {
  el: HTMLElement;
  edit: (item: LibraryItem | null) => void;
}

export function isEditable(item: LibraryItem | null): boolean {
  return !item || !item.package || item.package === WORKSPACE_ID;
}

export function libraryEditor(
  api: ApiClient,
  kind: LibraryKind,
  template: () => Record<string, unknown>,
  onSaved: (id: string | null) => void | Promise<void>,
): LibraryEditor {
  const ta = h("textarea", {
    class: "mono json-editor",
    rows: "18",
    spellcheck: "false",
    "aria-label": "JSON",
  });
  const errors = h("div");
  const info = h("div", { class: "muted small" });
  let mode: "create" | "update" = "create";
  let origId: string | null = null;

  const showErr = (e: Parameters<typeof renderEditorErrors>[0]) => replace(errors, renderEditorErrors(e));

  const validateLocal = () => {
    const r = parseLibraryItem(ta.value);
    showErr(r.ok ? null : r);
    ta.classList.toggle("invalid", !r.ok);
    return r;
  };
  ta.addEventListener("input", () => validateLocal());
  ta.addEventListener("keydown", (ev) => {
    if (ev.key === "Tab") {
      ev.preventDefault();
      const s = ta.selectionStart;
      ta.setRangeText("  ", s, ta.selectionEnd, "end");
    }
  });

  const saveBtn = button(
    t("common.save"),
    async () => {
      const r = validateLocal();
      if (!r.ok) return;
      const id = String(r.value["id"]);
      try {
        if (mode === "create") await api.post(`/${kind}`, r.value);
        else await api.put(`/${kind}/${encodeURIComponent(origId ?? id)}`, r.value);
        showErr(null);
        toast(t("editor.saved", { id }), "success");
        mode = "update";
        origId = id;
        updateInfo(true);
        await onSaved(id);
      } catch (exc) {
        showErr(exc as Error);
      }
    },
    { kind: "primary" },
  );

  const delBtn = button(
    t("common.delete"),
    async () => {
      if (!origId || mode !== "update") return;
      if (!(await confirmDialog(t("editor.deleteConfirm", { id: origId })))) return;
      try {
        await api.del(`/${kind}/${encodeURIComponent(origId)}`);
        toast(t("editor.deleted", { id: origId }), "success");
        edit(null);
        await onSaved(null);
      } catch (exc) {
        showErr(exc as Error);
      }
    },
    { kind: "danger" },
  );

  const copyBtn = button(t("editor.copyToWorkspace"), () => {
    const r = parseLibraryItem(ta.value);
    if (!r.ok) return showErr(r);
    const obj = { ...r.value, id: `${String(r.value["id"])}_copy` };
    ta.value = JSON.stringify(obj, null, 2);
    mode = "create";
    origId = null;
    updateInfo(true);
  });

  const formatBtn = button(
    t("editor.format"),
    () => {
      const r = validateLocal();
      if (r.ok) ta.value = JSON.stringify(r.value, null, 2);
    },
    { kind: "ghost" },
  );

  const newBtn = button(t("editor.new"), () => edit(null), { kind: "ghost" });

  const updateInfo = (editable: boolean, pkg?: string | null) => {
    ta.readOnly = !editable;
    saveBtn.hidden = !editable;
    delBtn.hidden = !editable || mode !== "update";
    copyBtn.hidden = editable;
    info.textContent = editable
      ? mode === "create"
        ? t("editor.modeCreate")
        : t("editor.modeUpdate", { id: origId ?? "" })
      : t("editor.readonly", { pkg: pkg ?? "?" });
  };

  const edit = (item: LibraryItem | null) => {
    showErr(null);
    ta.classList.remove("invalid");
    if (!item) {
      mode = "create";
      origId = null;
      ta.value = JSON.stringify(template(), null, 2);
      updateInfo(true);
      return;
    }
    mode = "update";
    origId = item.id;
    ta.value = toEditorText(item);
    updateInfo(isEditable(item), item.package);
  };

  const el = h(
    "div",
    { class: "library-editor" },
    info,
    ta,
    errors,
    row(saveBtn, formatBtn, newBtn, copyBtn, delBtn),
  );
  edit(null);
  return { el, edit };
}
