/** Typgerechte Eingabe eines Katalogwerts (enum → Select, bool → Checkbox, bitfield → Felder, Zahl/Text). */
import { h } from "../dom";
import { t } from "../i18n";
import type { ValueSpec } from "../types";

export interface ValueInput {
  el: HTMLElement;
  get: () => unknown;
  set: (v: unknown) => void;
}

const NUMERIC = new Set(["uint", "int", "float", "number", "u8", "u16", "u32", "i8", "i16", "i32", "scaled"]);

export function valueInput(spec: ValueSpec): ValueInput {
  if (spec.type === "enum" && spec.enum) {
    const sel = h("select");
    for (const [k, name] of Object.entries(spec.enum))
      sel.appendChild(h("option", { value: name }, `${name} (${k})`));
    return { el: sel, get: () => sel.value, set: (v) => (sel.value = String(v)) };
  }
  if (spec.type === "bool") {
    const cb = h("input", { type: "checkbox" });
    return {
      el: h("label", { class: "check" }, cb, h("span", null, t("common.on"))),
      get: () => cb.checked,
      set: (v) => (cb.checked = Boolean(v)),
    };
  }
  if (spec.type === "bitfield" && spec.bits) {
    const parts = spec.bits.map((b) => {
      if (b.enum) {
        const sel = h("select");
        for (const [k, name] of Object.entries(b.enum))
          sel.appendChild(h("option", { value: k }, `${name} (${k})`));
        return {
          b,
          el: h("label", { class: "field" }, h("span", { class: "field-label" }, b.name), sel),
          get: () => Number(sel.value),
          set: (v: unknown) => (sel.value = String(v)),
        };
      }
      if (b.length === 1) {
        const cb = h("input", { type: "checkbox" });
        return {
          b,
          el: h("label", { class: "check" }, cb, h("span", null, `${b.name} (Bit ${b.bit})`)),
          get: () => (cb.checked ? 1 : 0),
          set: (v: unknown) => (cb.checked = Boolean(Number(v))),
        };
      }
      const inp = h("input", {
        type: "number",
        min: "0",
        max: String(2 ** b.length - 1),
        value: "0",
        class: "w-xs",
      });
      return {
        b,
        el: h(
          "label",
          { class: "field" },
          h("span", { class: "field-label" }, `${b.name} (Bit ${b.bit}–${b.bit + b.length - 1})`),
          inp,
        ),
        get: () => Number(inp.value),
        set: (v: unknown) => (inp.value = String(v)),
      };
    });
    return {
      el: h(
        "div",
        { class: "bitfield" },
        parts.map((p) => p.el),
      ),
      get: () => Object.fromEntries(parts.map((p) => [p.b.name, p.get()])),
      set: (v) => {
        if (v && typeof v === "object")
          for (const p of parts) p.set((v as Record<string, unknown>)[p.b.name] ?? 0);
      },
    };
  }
  if (NUMERIC.has(spec.type)) {
    const inp = h("input", {
      type: "number",
      step: spec.scale && spec.scale < 1 ? String(spec.scale) : "any",
      min: spec.min !== null ? String(spec.min) : undefined,
      max: spec.max !== null ? String(spec.max) : undefined,
      class: "w-sm",
    });
    return {
      el: h("span", { class: "inline" }, inp, spec.unit ? h("span", { class: "unit" }, spec.unit) : null),
      get: () => (inp.value === "" ? null : Number(inp.value)),
      set: (v) => (inp.value = v === null || v === undefined ? "" : String(v)),
    };
  }
  const inp = h("input", { type: "text", class: spec.type === "ascii" ? "" : "mono", spellcheck: "false" });
  if (spec.length) inp.placeholder = t("did.lengthHint", { n: spec.length });
  return {
    el: inp,
    get: () => inp.value,
    set: (v) => (inp.value = v === null || v === undefined ? "" : String(v)),
  };
}
