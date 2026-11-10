import { h } from "../dom";
import { t } from "../i18n";
import type { Store } from "../store";

/**
 * ECU-Auswahl, die mit der globalen Auswahl (Kopfzeile) synchron ist.
 * Liefert das <select> und eine Aufräumfunktion.
 */
export function ecuSelect(
  store: Store,
  opts: { allowNone?: boolean; local?: boolean; value?: string | null } = {},
): { el: HTMLSelectElement; dispose: () => void } {
  const sel = h("select", { class: "ecu-select", "aria-label": t("header.ecu") });
  let localValue = opts.value ?? "";
  const render = () => {
    const selected = opts.local ? localValue : store.selectedEcu;
    sel.replaceChildren();
    if (opts.allowNone) sel.appendChild(h("option", { value: "" }, t("common.default")));
    for (const e of store.ecus) {
      const o = h("option", { value: e.id }, `${e.id} – ${e.name}`);
      if (e.id === selected) o.selected = true;
      sel.appendChild(o);
    }
    if (!store.ecus.length) sel.appendChild(h("option", { value: "" }, t("common.noEcus")));
  };
  render();
  sel.addEventListener("change", () => {
    if (opts.local) localValue = sel.value;
    else store.selectEcu(sel.value || null);
  });
  const off = store.changed.on((k) => {
    if (k === "ecus" || k === "selectedEcu") render();
  });
  return { el: sel, dispose: off };
}
