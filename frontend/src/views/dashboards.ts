import { infoIcon } from "../help";
import { matchShortcut, parseShortcut, type ButtonDef } from "../action-model";
import { ApiError, formatErrorDetails } from "../api";
import { editButtonModal } from "../components/action-editor";
import {
  defaultConfig,
  PANEL_TYPES,
  renderPanel,
  type PanelDef,
  type PanelRender,
  type PanelType,
} from "../components/panels";
import { toast, toastError } from "../components/toast";
import { badge, button, field, modal, numberInput, select, textInput, confirmDialog } from "../components/ui";
import { clampRect, nextFreeSpot, pixelDeltaToCells, resolveLayout, uniqueId } from "../dashboard-grid";
import { h, replace } from "../dom";
import { parseJson } from "../editor";
import { t, type MsgKey } from "../i18n";
import * as storage from "../storage";
import type { AppCtx, View } from "../view";

export interface Dashboard {
  id: string;
  name: string;
  description: string;
  columns: number;
  panels: PanelDef[];
  source?: string;
  editable?: boolean;
}

const ROW_PX = 80;
const GAP_PX = 10;

/** Für PUT/POST: nur Modellfelder. */
export function dashboardPayload(d: Dashboard): Omit<Dashboard, "source" | "editable"> {
  return {
    id: d.id,
    name: d.name,
    description: d.description ?? "",
    columns: d.columns || 12,
    panels: d.panels.map((p) => ({
      id: p.id,
      title: p.title ?? "",
      type: p.type,
      x: p.x,
      y: p.y,
      w: p.w,
      h: p.h,
      buttons: p.buttons ?? [],
      config: p.config ?? {},
    })),
  };
}

/** Eingabe-Prompt als Modal. */
function promptModal(title: string, label: string, value = ""): Promise<string | null> {
  return new Promise((resolve) => {
    const inp = textInput(value);
    let done = false;
    const finish = (v: string | null) => {
      if (done) return;
      done = true;
      resolve(v);
      close();
    };
    inp.addEventListener("keydown", (ev) => ev.key === "Enter" && finish(inp.value));
    const close = modal(
      title,
      field(label, inp),
      [button(t("common.save"), () => finish(inp.value), { kind: "primary" })],
      () => finish(null),
    );
  });
}

export function createDashboardsView(ctx: AppCtx): View {
  const { api, store } = ctx;
  let list: Dashboard[] = [];
  let current: Dashboard | null = null;
  let draft: Dashboard | null = null;
  let editMode = false;
  let dirty = false;
  const renders = new Map<string, PanelRender>();
  const panelEls = new Map<string, HTMLElement>();

  const dashSel = h("select", { "aria-label": t("dash.select") });
  const info = h("span", { class: "muted small" });
  const toolbar = h("div", { class: "toolbar" });
  const grid = h("div", { class: "dash-grid" });

  const load = async (keep?: string) => {
    list = await api.get<Dashboard[]>("/dashboards");
    const want = keep ?? current?.id ?? storage.load<string | null>("dashboard", null);
    const d = list.find((x) => x.id === want) ?? list[0] ?? null;
    replace(
      dashSel,
      ...list.map((x) =>
        h(
          "option",
          { value: x.id, selected: x.id === d?.id },
          `${x.name}${x.editable === false ? " 🔒" : ""}`,
        ),
      ),
    );
    open(d);
  };

  const open = (d: Dashboard | null) => {
    current = d ? structuredClone(d) : null;
    draft = d ? structuredClone(d) : null;
    dirty = false;
    if (d) storage.save("dashboard", d.id);
    if (d && d.editable === false) editMode = false;
    renderToolbar();
    renderGrid();
  };

  dashSel.addEventListener("change", async () => {
    if (
      dirty &&
      !(await confirmDialog(t("dash.discardConfirm"), { danger: false, confirmLabel: t("dash.discard") }))
    ) {
      dashSel.value = current?.id ?? "";
      return;
    }
    open(list.find((x) => x.id === dashSel.value) ?? null);
  });

  const markDirty = () => {
    dirty = true;
    renderToolbar();
  };

  const renderToolbar = () => {
    const d = draft;
    const editable = d?.editable !== false;
    const addSel = select(
      PANEL_TYPES.map((p) => ({ value: p, label: t(`panel.${p}` as MsgKey) })),
      "buttons",
    );
    replace(
      toolbar,
      field(t("dash.select"), dashSel),
      d && !editable ? badge(t("dash.fromPackage", { src: d.source ?? "" }), "warn") : null,
      editable && d
        ? button(
            editMode ? t("dash.editDone") : t("dash.edit"),
            () => {
              editMode = !editMode;
              renderToolbar();
              renderGrid();
            },
            { kind: editMode ? "primary" : "default", cls: "dash-edit-toggle" },
          )
        : null,
      editable && d ? infoIcon("dashboards.edit") : null,
      button(t("dash.new"), createDash, { kind: "ghost" }),
      d ? button(t("dash.duplicate"), duplicate, { kind: "ghost" }) : null,
      editMode && d
        ? [
            button(t("dash.rename"), rename, { kind: "ghost" }),
            h(
              "span",
              { class: "inline" },
              addSel,
              button(t("dash.addPanel"), () => addPanel(addSel.value as PanelType)),
            ),
            button(t("common.save"), save, { kind: "primary", cls: dirty ? "pulse" : "" }),
            dirty
              ? button(t("dash.discard"), () => open(list.find((x) => x.id === d.id) ?? null), {
                  kind: "ghost",
                })
              : null,
            button(t("common.delete"), del, { kind: "danger" }),
          ]
        : null,
      info,
    );
    info.textContent = dirty ? t("dash.unsaved") : (d?.description ?? "");
  };

  const renderGrid = () => {
    for (const r of renders.values()) r.dispose();
    renders.clear();
    panelEls.clear();
    grid.replaceChildren();
    grid.classList.toggle("editing", editMode);
    const d = draft;
    if (!d) {
      grid.appendChild(h("div", { class: "empty" }, t("dash.none")));
      return;
    }
    grid.style.gridTemplateColumns = `repeat(${d.columns || 12}, minmax(0, 1fr))`;
    for (const p of d.panels) grid.appendChild(panelEl(p));
    if (!d.panels.length)
      grid.appendChild(h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, t("dash.empty")));
  };

  const place = (el: HTMLElement, p: PanelDef) => {
    el.style.gridColumn = `${p.x + 1} / span ${p.w}`;
    el.style.gridRow = `${p.y + 1} / span ${p.h}`;
  };

  const press = (p: PanelDef) => async (b: ButtonDef, idx: number) => {
    // gespeicherter Knopf → press-Endpunkt; ungespeicherte Änderungen → Aktion direkt ausführen
    if (!dirty && current && current.panels.some((x) => x.id === p.id)) {
      return api.post<Record<string, unknown>>(
        `/dashboards/${encodeURIComponent(current.id)}/panels/${encodeURIComponent(p.id)}/buttons/${idx}/press`,
        {},
      );
    }
    return api.post<Record<string, unknown>>("/actions/run", b.action);
  };

  const panelEl = (p: PanelDef): HTMLElement => {
    const r = renderPanel(ctx, p, press(p));
    renders.set(p.id, r);
    const head = h(
      "div",
      { class: "panel-head" },
      h("span", { class: "panel-title" }, p.title || t(`panel.${p.type}` as MsgKey)),
      editMode
        ? h(
            "span",
            { class: "panel-tools" },
            button("⚙", () => editPanel(p), { kind: "ghost", title: t("dash.panelSettings") }),
            button("×", () => void removePanel(p), { kind: "ghost", title: t("dash.removePanel") }),
          )
        : null,
    );
    const el = h(
      "div",
      { class: ["panel", `panel-${p.type}`], dataset: { panel: p.id } },
      head,
      h("div", { class: "panel-body" }, r.el),
      editMode ? h("div", { class: "panel-resize", title: t("dash.resize") }) : null,
    );
    place(el, p);
    panelEls.set(p.id, el);
    if (editMode) {
      head.classList.add("draggable");
      head.addEventListener("pointerdown", (ev) => startDrag(ev, p, "move"));
      el.querySelector<HTMLElement>(".panel-resize")?.addEventListener("pointerdown", (ev) =>
        startDrag(ev, p, "resize"),
      );
    }
    return el;
  };

  const startDrag = (ev: PointerEvent, p: PanelDef, mode: "move" | "resize") => {
    if ((ev.target as HTMLElement).closest("button")) return;
    if (!draft) return;
    ev.preventDefault();
    const d = draft;
    const cols = d.columns || 12;
    const rect = grid.getBoundingClientRect();
    const colStep = (rect.width + GAP_PX) / cols;
    const rowStep = ROW_PX + GAP_PX;
    const sx = ev.clientX;
    const sy = ev.clientY;
    const orig = { ...p };
    panelEls.get(p.id)?.classList.add("dragging");
    const onMove = (e: PointerEvent) => {
      const delta = pixelDeltaToCells(e.clientX - sx, e.clientY - sy, colStep, rowStep);
      const cand =
        mode === "move"
          ? clampRect({ ...orig, x: orig.x + delta.dx, y: orig.y + delta.dy }, cols)
          : clampRect({ ...orig, w: orig.w + delta.dx, h: orig.h + delta.dy }, cols);
      const others = d.panels.map((x) => (x.id === p.id ? { ...x, ...cand } : x));
      const resolved = resolveLayout(others, p.id, cols);
      let changed = false;
      d.panels.forEach((x, i) => {
        const nx = resolved[i];
        if (nx && (nx.x !== x.x || nx.y !== x.y || nx.w !== x.w || nx.h !== x.h)) {
          Object.assign(x, { x: nx.x, y: nx.y, w: nx.w, h: nx.h });
          const el = panelEls.get(x.id);
          if (el) place(el, x);
          changed = true;
        }
      });
      if (changed && !dirty) markDirty();
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      panelEls.get(p.id)?.classList.remove("dragging");
      if (mode === "resize") renderGrid(); // Inhalte (z. B. Diagrammhöhe) neu aufbauen
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const addPanel = (type: PanelType) => {
    if (!draft) return;
    const w = type === "timechart" || type === "trace" ? 8 : 4;
    const hh = 3;
    const spot = nextFreeSpot(draft.panels, w, hh, draft.columns || 12);
    const p: PanelDef = {
      id: uniqueId(
        `${type}_`,
        draft.panels.map((x) => x.id),
      ),
      title: t(`panel.${type}` as MsgKey),
      type,
      ...spot,
      w,
      h: hh,
      buttons: [],
      config: defaultConfig(type, store.selectedEcu),
    };
    draft.panels.push(p);
    markDirty();
    renderGrid();
    if (type === "buttons") editPanel(p);
  };

  const removePanel = async (p: PanelDef) => {
    if (!draft || !(await confirmDialog(t("dash.removeConfirm", { title: p.title || p.id })))) return;
    draft.panels = draft.panels.filter((x) => x.id !== p.id);
    markDirty();
    renderGrid();
  };

  const editPanel = (p: PanelDef) => {
    const title = textInput(p.title);
    const typeSel = select(
      PANEL_TYPES.map((x) => ({ value: x, label: t(`panel.${x}` as MsgKey) })),
      p.type,
    );
    const w = numberInput(p.w, { min: "1", max: "12", class: "w-xs" });
    const hh = numberInput(p.h, { min: "1", max: "24", class: "w-xs" });
    const cfg = h("textarea", { class: "mono", rows: "6", spellcheck: "false" });
    cfg.value = JSON.stringify(p.config ?? {}, null, 2);
    const err = h("div");
    const buttons: ButtonDef[] = structuredClone(p.buttons ?? []);
    const btnList = h("div", { class: "btn-list" });
    typeSel.addEventListener("change", () => {
      cfg.value = JSON.stringify(defaultConfig(typeSel.value as PanelType, store.selectedEcu), null, 2);
      btnSection.hidden = typeSel.value !== "buttons";
    });
    const renderBtns = (): void =>
      replace(
        btnList,
        buttons.length
          ? buttons.map((b, i) =>
              h(
                "div",
                { class: "btn-list-item" },
                h("span", { class: "btn-list-label" }, `${b.icon ?? ""} ${b.label}`),
                h(
                  "code",
                  { class: "small" },
                  `${b.action.type}${b.action.ref !== undefined && b.action.ref !== null ? `:${b.action.ref}` : b.action.payload ? `:${b.action.payload}` : ""}`,
                ),
                button(
                  "✎",
                  () =>
                    editButtonModal(api, store, b, (nb) => {
                      buttons[i] = nb;
                      renderBtns();
                    }),
                  { kind: "ghost", title: t("dash.editButton") },
                ),
                button(
                  "↑",
                  () => {
                    if (i > 0)
                      [buttons[i - 1], buttons[i]] = [buttons[i] as ButtonDef, buttons[i - 1] as ButtonDef];
                    renderBtns();
                  },
                  { kind: "ghost" },
                ),
                button(
                  "×",
                  () => {
                    buttons.splice(i, 1);
                    renderBtns();
                  },
                  { kind: "ghost", title: t("common.delete") },
                ),
              ),
            )
          : h("div", { class: "muted" }, t("dash.noButtons")),
      );
    renderBtns();
    const btnSection = h(
      "fieldset",
      { hidden: p.type !== "buttons" },
      h("legend", null, t("dash.buttons")),
      btnList,
      button(
        t("dash.addButton"),
        () =>
          editButtonModal(api, store, null, (nb) => {
            buttons.push(nb);
            renderBtns();
          }),
        { kind: "primary" },
      ),
    );
    const close = modal(
      t("dash.panelSettings"),
      h(
        "div",
        null,
        h(
          "div",
          { class: "grid" },
          field(t("dash.panelTitle"), title),
          field(t("dash.panelType"), typeSel),
          field(t("dash.width"), w),
          field(t("dash.height"), hh),
        ),
        field(t("dash.config"), cfg, t("dash.configHint"), "field-wide"),
        btnSection,
        err,
      ),
      [
        button(
          t("common.save"),
          () => {
            const r = parseJson<Record<string, unknown>>(cfg.value || "{}");
            if (!r.ok || typeof r.value !== "object" || Array.isArray(r.value)) {
              replace(err, h("div", { class: "error-box" }, r.ok ? t("dash.configObject") : r.message));
              return;
            }
            if (!draft) return;
            Object.assign(p, {
              title: title.value,
              type: typeSel.value as PanelType,
              w: Number(w.value) || p.w,
              h: Number(hh.value) || p.h,
              config: r.value,
              buttons: typeSel.value === "buttons" ? buttons : [],
            });
            draft.panels = resolveLayout(draft.panels, p.id, draft.columns || 12);
            markDirty();
            renderGrid();
            close();
          },
          { kind: "primary" },
        ),
      ],
    );
  };

  const showApiError = (exc: unknown) => {
    if (exc instanceof ApiError) toast(exc.message, "error", formatErrorDetails(exc.details));
    else toastError(exc);
  };

  const save = async () => {
    if (!draft) return;
    try {
      await api.put(`/dashboards/${encodeURIComponent(draft.id)}`, dashboardPayload(draft));
      toast(t("dash.saved", { name: draft.name }), "success");
      dirty = false;
      await load(draft.id);
    } catch (exc) {
      showApiError(exc);
    }
  };

  const createDash = async () => {
    const name = await promptModal(t("dash.new"), t("common.name"), t("dash.newName"));
    if (!name) return;
    const base =
      name
        .toLowerCase()
        .replace(/[^a-z0-9_.-]+/g, "_")
        .replace(/^_+|_+$/g, "") || "dashboard";
    const ids = list.map((x) => x.id);
    const id = ids.includes(base) ? uniqueId(`${base}_`, ids) : base;
    try {
      await api.post("/dashboards", { id, name, description: "", columns: 12, panels: [] });
      editMode = true;
      await load(id);
    } catch (exc) {
      showApiError(exc);
    }
  };

  const duplicate = async () => {
    if (!draft) return;
    const name = await promptModal(
      t("dash.duplicate"),
      t("common.name"),
      `${draft.name} (${t("dash.copy")})`,
    );
    if (!name) return;
    const copy = dashboardPayload({
      ...draft,
      id: uniqueId(
        `${draft.id}_copy`,
        list.map((x) => x.id),
      ),
      name,
    });
    try {
      await api.post("/dashboards", copy);
      await load(copy.id);
    } catch (exc) {
      showApiError(exc);
    }
  };

  const rename = async () => {
    if (!draft) return;
    const name = await promptModal(t("dash.rename"), t("common.name"), draft.name);
    if (!name) return;
    draft.name = name;
    await save();
  };

  const del = async () => {
    if (!draft || !(await confirmDialog(t("dash.deleteConfirm", { name: draft.name })))) return;
    try {
      await api.del(`/dashboards/${encodeURIComponent(draft.id)}`);
      current = null;
      draft = null;
      dirty = false;
      editMode = false;
      await load();
    } catch (exc) {
      showApiError(exc);
    }
  };

  /** Knopf-Tastenkürzel des angezeigten Dashboards. */
  const onKey = (ev: KeyboardEvent): boolean => {
    if (!draft || editMode) return false;
    for (const p of draft.panels) {
      if (p.type !== "buttons") continue;
      for (let i = 0; i < p.buttons.length; i++) {
        const sc = parseShortcut(p.buttons[i]?.shortcut);
        if (sc && matchShortcut(ev, sc)) {
          ev.preventDefault();
          panelEls.get(p.id)?.querySelector<HTMLButtonElement>(`button[data-idx="${i}"]`)?.click();
          return true;
        }
      }
    }
    return false;
  };

  const offs = [store.on("packages", () => void load().catch(() => undefined))];
  const el = h("div", { class: "dashboards" }, toolbar, grid);
  let loaded = false;
  return {
    el,
    onKey,
    show: () => {
      if (!loaded) {
        loaded = true;
        void load().catch(toastError);
      } else renderGrid();
    },
    hide: () => {
      for (const r of renders.values()) r.dispose();
      renders.clear();
    },
    destroy: () => {
      offs.forEach((o) => o());
      for (const r of renders.values()) r.dispose();
    },
  };
}

/** Schnellfunktion: Botschaft als Knopf auf ein Dashboard legen. */
export async function addMessageButton(ctx: AppCtx, messageId: string, label: string): Promise<void> {
  const { api } = ctx;
  const dashes = (await api.get<Dashboard[]>("/dashboards")).filter((d) => d.editable !== false);
  if (!dashes.length) {
    toast(t("dash.noEditable"), "warning");
    return;
  }
  const dashSel = select(
    dashes.map((d) => ({ value: d.id, label: d.name })),
    dashes[0]?.id,
  );
  const panelSel = h("select");
  const labelIn = textInput(label);
  const fill = () => {
    const d = dashes.find((x) => x.id === dashSel.value);
    replace(
      panelSel,
      ...(d?.panels ?? [])
        .filter((p) => p.type === "buttons")
        .map((p) => h("option", { value: p.id }, p.title || p.id)),
      h("option", { value: "__new" }, t("dash.newButtonPanel")),
    );
  };
  dashSel.addEventListener("change", fill);
  fill();
  const close = modal(
    t("dash.addToDashboard"),
    h(
      "div",
      { class: "grid" },
      field("Dashboard", dashSel),
      field(t("dash.panel"), panelSel),
      field(t("dash.label"), labelIn),
    ),
    [
      button(
        t("common.save"),
        async () => {
          const d = dashes.find((x) => x.id === dashSel.value);
          if (!d) return;
          const btn: ButtonDef = {
            label: labelIn.value.trim() || messageId,
            action: { type: "message", ref: messageId },
          };
          let panel = d.panels.find((p) => p.id === panelSel.value);
          if (!panel) {
            const spot = nextFreeSpot(d.panels, 4, 2, d.columns || 12);
            panel = {
              id: uniqueId(
                "buttons_",
                d.panels.map((p) => p.id),
              ),
              title: t("panel.buttons"),
              type: "buttons",
              ...spot,
              w: 4,
              h: 2,
              buttons: [],
              config: {},
            };
            d.panels.push(panel);
          }
          panel.buttons.push(btn);
          try {
            await api.put(`/dashboards/${encodeURIComponent(d.id)}`, dashboardPayload(d));
            toast(t("dash.buttonAdded", { label: btn.label, name: d.name }), "success");
            close();
          } catch (exc) {
            toastError(exc);
          }
        },
        { kind: "primary" },
      ),
    ],
  );
}
