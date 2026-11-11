/** Wiederverwendbare UI-Bausteine. */
import { type Child, h, replace } from "../dom";
import { t } from "../i18n";
import type { Assertion, StepRecord, UdsResult } from "../types";
import { infoIcon, openHelpTopic } from "../help";
import { asciiOf, isValidHex } from "../hex";
import { toastError } from "./toast";

/**
 * Beschriftetes Eingabefeld. `help` = Tooltip-Schlüssel ("ansicht.feld") für das ⓘ-Symbol.
 * Das ⓘ steht außerhalb des <label>, damit ein Klick darauf nicht das Feld aktiviert.
 */
export function field(
  label: string,
  control: Child,
  hint?: string,
  cls?: string,
  help?: string,
): HTMLElement {
  const lbl = h(
    "label",
    { class: ["field", cls] },
    h("span", { class: "field-label" }, label, help ? infoIcon(help) : null),
    control,
    hint ? h("span", { class: "field-hint" }, hint) : null,
  );
  return lbl;
}

/** Bestätigung im UI (statt window.confirm). */
export function confirmDialog(
  message: string,
  opts: { title?: string; confirmLabel?: string; danger?: boolean } = {},
): Promise<boolean> {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v: boolean) => {
      if (done) return;
      done = true;
      resolve(v);
      close();
    };
    const ok = h(
      "button",
      { type: "button", class: ["btn", opts.danger === false ? "btn-primary" : "btn-danger-solid"] },
      opts.confirmLabel ?? (opts.danger === false ? t("common.confirm") : t("common.deleteConfirm")),
    );
    ok.addEventListener("click", () => finish(true));
    const cancel = h("button", { type: "button", class: "btn" }, t("common.cancel"));
    cancel.addEventListener("click", () => finish(false));
    const close = modal(
      opts.title ?? t("common.confirmTitle"),
      h("p", { class: "confirm-text" }, message),
      [cancel, ok],
      () => finish(false),
    );
    ok.focus();
  });
}

export function checkbox(
  label: string,
  checked: boolean,
  onchange?: (v: boolean) => void,
  title?: string,
  help?: string,
) {
  const input = h("input", { type: "checkbox", checked });
  if (onchange) input.addEventListener("change", () => onchange(input.checked));
  const el = h(
    "label",
    { class: "check", title },
    input,
    h("span", null, label),
    help ? infoIcon(help) : null,
  );
  return { el, input };
}

export function textInput(value = "", attrs: Record<string, unknown> = {}): HTMLInputElement {
  return h("input", { type: "text", value, spellcheck: "false", autocomplete: "off", ...attrs });
}

export function numberInput(
  value: number | string = "",
  attrs: Record<string, unknown> = {},
): HTMLInputElement {
  return h("input", { type: "number", value: String(value), ...attrs });
}

export function select(
  opts: { value: string; label: string }[],
  value?: string,
  attrs: Record<string, unknown> = {},
) {
  const s = h("select", attrs);
  for (const o of opts) {
    const el = h("option", { value: o.value }, o.label);
    if (o.value === value) el.selected = true;
    s.appendChild(el);
  }
  return s;
}

export type BtnKind = "primary" | "danger" | "ghost" | "default";

export function button(
  label: Child,
  onclick: (ev: MouseEvent) => unknown,
  opts: { kind?: BtnKind; title?: string; cls?: string; type?: string } = {},
): HTMLButtonElement {
  const b = h(
    "button",
    {
      type: opts.type ?? "button",
      class: ["btn", opts.kind && opts.kind !== "default" ? `btn-${opts.kind}` : null, opts.cls],
      title: opts.title,
    },
    label,
  );
  b.addEventListener("click", (ev) => {
    const r = onclick(ev);
    if (r instanceof Promise) {
      b.disabled = true;
      b.classList.add("busy");
      r.catch((exc: unknown) => toastError(exc)).finally(() => {
        b.disabled = false;
        b.classList.remove("busy");
      });
    }
  });
  return b;
}

export function card(title: Child, ...children: Child[]): HTMLElement {
  return h("section", { class: "card" }, title ? h("h3", { class: "card-title" }, title) : null, ...children);
}

export function row(...children: Child[]): HTMLElement {
  return h("div", { class: "row" }, ...children);
}

export function badge(text: string, kind = ""): HTMLElement {
  return h("span", { class: ["badge", kind ? `badge-${kind}` : null] }, text);
}

const STATUS_KIND: Record<string, string> = {
  passed: "ok",
  ok: "ok",
  failed: "fail",
  error: "fail",
  cancelled: "warn",
  skipped: "muted",
  running: "run",
  queued: "muted",
};

export function statusBadge(status: string): HTMLElement {
  const key = `status.${status}` as Parameters<typeof t>[0];
  const label = t(key) === key ? status : t(key);
  return badge(label, STATUS_KIND[status] ?? "");
}

export function jsonView(value: unknown, cls = ""): HTMLElement {
  return h("pre", { class: ["json", cls] }, JSON.stringify(value, null, 2));
}

export function empty(text: string): HTMLElement {
  return h("div", { class: "empty" }, text);
}

export interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => Child;
  cls?: string;
}

export function table<T>(
  cols: Column<T>[],
  rows: T[],
  opts: { rowClass?: (r: T) => string; onRow?: (r: T) => void } = {},
) {
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "tbl" },
      h(
        "thead",
        null,
        h(
          "tr",
          null,
          cols.map((c) => h("th", { class: c.cls }, c.label)),
        ),
      ),
      h(
        "tbody",
        null,
        rows.length
          ? rows.map((r) => {
              const tr = h(
                "tr",
                { class: opts.rowClass?.(r) },
                cols.map((c) => h("td", { class: c.cls }, c.render(r))),
              );
              if (opts.onRow) {
                tr.classList.add("clickable");
                tr.addEventListener("click", () => opts.onRow?.(r));
              }
              return tr;
            })
          : h(
              "tr",
              null,
              h("td", { colspan: String(cols.length), class: "muted center" }, t("common.noEntries")),
            ),
      ),
    ),
  );
}

export function kv(pairs: [string, Child][]): HTMLElement {
  return h(
    "dl",
    { class: "kv" },
    pairs.map(([k, v]) => [
      h("dt", null, k),
      h("dd", null, v === null || v === undefined || v === "" ? "–" : v),
    ]),
  );
}

/** Wert einer Feldanzeige typgerecht formatieren (Objekte → Badges). */
export function valueView(value: unknown, unit?: string): Child {
  if (value === null || value === undefined) return "–";
  if (typeof value === "object" && !Array.isArray(value)) {
    return h(
      "span",
      { class: "bits" },
      Object.entries(value as Record<string, unknown>).map(([k, v]) =>
        h("span", { class: ["badge", v ? "badge-on" : "badge-off"] }, `${k}=${String(v)}`),
      ),
    );
  }
  if (Array.isArray(value)) return JSON.stringify(value);
  return h("span", { class: "value" }, String(value), unit ? h("span", { class: "unit" }, ` ${unit}`) : null);
}

/**
 * Hex-Daten mit ASCII-Übersetzung (nicht darstellbare Bytes als „·“).
 * `inline`: ASCII in Anführungszeichen hinter den Hex-Bytes, sonst in einer eigenen Zeile.
 */
export function hexAscii(hex: string | null | undefined, opts: { inline?: boolean } = {}): HTMLElement {
  if (!hex) return h("code", { class: "mono" }, "–");
  const ascii = isValidHex(hex, false) ? asciiOf(hex) : "";
  if (opts.inline) {
    return h(
      "span",
      { class: "hexascii-inline" },
      h("code", { class: "mono" }, hex),
      ascii ? h("code", { class: "ascii", title: "ASCII" }, ` "${ascii}"`) : null,
    );
  }
  return h(
    "span",
    { class: "hexascii" },
    h("code", { class: "mono" }, hex),
    ascii
      ? h(
          "span",
          { class: "ascii-row" },
          h("span", { class: "ascii-label" }, "ASCII"),
          h("code", { class: "ascii" }, ascii),
        )
      : null,
  );
}

/** Antwortanzeige eines UDS-Requests (roh + interpretiert). */
export function udsResultView(r: UdsResult): HTMLElement {
  const kind = r.error ? "fail" : r.negative ? "neg" : r.positive ? "ok" : "muted";
  const head = r.error
    ? t("uds.error", { msg: r.error })
    : r.negative
      ? `NRC 0x${(r.nrc ?? 0).toString(16).toUpperCase().padStart(2, "0")} ${r.nrc_name ?? ""}`
      : r.positive
        ? t("uds.positive")
        : r.suppress_positive
          ? t("uds.suppressed")
          : t("uds.noResponse");
  const fields = r.decoded?.fields;
  const multi = (r.responses ?? []) as { ecu?: string; response?: string; decoded?: { text?: string } }[];
  return h(
    "div",
    { class: ["result", `result-${kind}`] },
    h(
      "div",
      { class: "result-head" },
      badge(head, kind),
      h(
        "span",
        { class: "muted" },
        r.elapsed_ms !== null && r.elapsed_ms !== undefined
          ? ` ${t("uds.elapsed", { ms: r.elapsed_ms })}`
          : "",
        infoIcon("uds.response_time"),
        r.pending_count ? ` · ${t("uds.pending", { n: r.pending_count })}` : "",
        r.pending_count ? infoIcon("uds.pending") : null,
        r.error ? infoIcon("uds.timeout") : null,
        r.functional ? ` · ${t("uds.functional")}` : "",
      ),
    ),
    kv([
      [t("uds.request"), h("code", { class: "mono" }, r.request)],
      [t("uds.response"), hexAscii(r.response)],
      [t("uds.interpretation"), r.decoded?.text ?? "–"],
      ...(r.decoded?.nrc_description
        ? [[t("uds.nrcText"), r.decoded.nrc_description] as [string, Child]]
        : []),
    ]),
    fields && Object.keys(fields).length ? fieldsView(fields) : null,
    r.error
      ? helpHint(
          r.error_kind === "timeout" || /timeout/i.test(r.error) ? "help.hintTimeout" : "help.hintError",
          "fehlerbehebung",
        )
      : r.negative
        ? helpHint("help.hintNrc", "nrc-referenz")
        : null,
    r.warnings?.length
      ? h(
          "ul",
          { class: "validation" },
          r.warnings.map((w) => h("li", { class: "v-warning" }, `⚠ ${w}`)),
        )
      : null,
    multi.length
      ? h(
          "div",
          { class: "multi" },
          h("strong", null, t("uds.multi", { n: multi.length })),
          table(
            [
              { key: "ecu", label: "ECU", render: (m) => m.ecu ?? "–" },
              {
                key: "resp",
                label: t("uds.response"),
                render: (m) => hexAscii(m.response),
              },
              { key: "text", label: t("uds.interpretation"), render: (m) => m.decoded?.text ?? "" },
            ],
            multi,
          ),
        )
      : null,
  );
}

/** Dekodierte Felder: records (DIDs) als Tabelle, sonst Schlüssel/Wert. */
export function fieldsView(fields: Record<string, unknown>): HTMLElement {
  const records = fields["records"];
  if (Array.isArray(records)) {
    type Rec = { did_hex?: string; name?: string; value?: unknown; unit?: string; raw?: string };
    return table<Rec>(
      [
        { key: "did", label: "DID", render: (r) => h("code", null, r.did_hex ?? "") },
        { key: "name", label: t("common.name"), render: (r) => r.name ?? "" },
        { key: "value", label: t("common.value"), render: (r) => valueView(r.value, r.unit) },
        { key: "raw", label: t("common.raw"), render: (r) => hexAscii(r.raw) },
      ],
      records as Rec[],
    );
  }
  return kv(
    Object.entries(fields)
      .filter(([k]) => k !== "dtcs")
      .map(([k, v]) => [
        k,
        typeof v === "object" && v !== null ? h("code", null, JSON.stringify(v)) : valueView(v),
      ]),
  );
}

export function assertionsView(list: Assertion[]): HTMLElement | null {
  if (!list.length) return null;
  return table<Assertion>(
    [
      { key: "ok", label: "", render: (a) => badge(a.ok ? "✔" : "✖", a.ok ? "ok" : "fail") },
      { key: "name", label: t("test.assertion"), render: (a) => a.name },
      { key: "exp", label: t("test.expected"), render: (a) => h("code", null, fmt(a.expected)) },
      { key: "act", label: t("test.actual"), render: (a) => h("code", null, fmt(a.actual)) },
      { key: "msg", label: t("common.message"), render: (a) => a.message },
    ],
    list,
    { rowClass: (a) => (a.ok ? "" : "row-fail") },
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Ergebnis eines Einzelschritts (POST /dids/read …). */
export function stepView(s: StepRecord): HTMLElement {
  return h(
    "div",
    { class: "step" },
    h(
      "div",
      { class: "step-head" },
      statusBadge(s.status),
      h("strong", null, ` ${s.name || s.action}`),
      s.ecu ? h("span", { class: "muted" }, ` · ${s.ecu}`) : null,
      s.elapsed_ms !== null && s.elapsed_ms !== undefined
        ? h("span", { class: "muted" }, ` · ${t("uds.elapsed", { ms: s.elapsed_ms })}`)
        : null,
      s.message ? h("span", { class: "step-msg" }, ` – ${s.message}`) : null,
    ),
    s.request || s.response
      ? kv([
          [t("uds.request"), h("code", { class: "mono" }, s.request ?? "–")],
          [t("uds.response"), hexAscii(s.response)],
          [t("uds.interpretation"), s.decoded?.text ?? "–"],
        ])
      : null,
    assertionsView(s.assertions ?? []),
  );
}

/** Einfaches Modal; liefert Schließfunktion. */
export function modal(
  title: string,
  content: Child,
  actions: HTMLElement[] = [],
  onClose?: () => void,
): () => void {
  const close = () => {
    overlay.remove();
    document.removeEventListener("keydown", onKey, true);
    onClose?.();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (ev.key === "Escape") {
      ev.stopPropagation();
      close();
    }
  };
  const overlay = h(
    "div",
    { class: "modal-overlay", onclick: (ev: Event) => ev.target === overlay && close() },
    h(
      "div",
      { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title },
      h(
        "div",
        { class: "modal-head" },
        h("h2", null, title),
        h("button", { class: "btn btn-ghost", onclick: close, "aria-label": t("common.close") }, "×"),
      ),
      h("div", { class: "modal-body" }, content),
      actions.length ? h("div", { class: "modal-actions" }, actions) : null,
    ),
  );
  document.addEventListener("keydown", onKey, true);
  document.body.appendChild(overlay);
  const first = overlay.querySelector<HTMLElement>("input,textarea,select,button.btn-primary");
  first?.focus();
  return close;
}

/** Tabs: liefert Container + Umschalter. */
export function tabs(items: { id: string; label: string; render: () => HTMLElement }[], initial?: string) {
  const bar = h("div", { class: "tabs", role: "tablist" });
  const body = h("div", { class: "tab-body" });
  let current = initial ?? items[0]?.id ?? "";
  const show = (id: string) => {
    current = id;
    for (const b of bar.querySelectorAll<HTMLButtonElement>("button")) {
      b.classList.toggle("active", b.dataset["tab"] === id);
      b.setAttribute("aria-selected", String(b.dataset["tab"] === id));
    }
    const it = items.find((i) => i.id === id);
    if (it) replace(body, it.render());
  };
  for (const it of items) {
    bar.appendChild(
      h(
        "button",
        { class: "tab", role: "tab", dataset: { tab: it.id }, onclick: () => show(it.id) },
        it.label,
      ),
    );
  }
  show(current);
  return {
    el: h("div", { class: "tabs-wrap" }, bar, body),
    show,
    get current() {
      return current;
    },
  };
}

/** Bereich, dessen Inhalt asynchron geladen wird. */
export function asyncBox(loader: () => Promise<Child>): { el: HTMLElement; reload: () => Promise<void> } {
  const el = h("div", { class: "async-box" }, h("span", { class: "muted" }, t("common.loading")));
  const reload = async () => {
    try {
      replace(el, await loader());
    } catch (exc) {
      replace(el, h("div", { class: "error-box" }, String((exc as Error).message)));
      toastError(exc);
    }
  };
  void reload();
  return { el, reload };
}

/** Kurzer Hinweis mit Link in die Hilfe (leere Zustände, Fehler). */
export function helpHint(textKey: Parameters<typeof t>[0], topic: string, anchor?: string): HTMLElement {
  return h(
    "p",
    { class: "help-hint" },
    t(textKey),
    " ",
    h(
      "a",
      {
        href: `#help:${topic}`,
        onclick: (ev: Event) => {
          ev.preventDefault();
          openHelpTopic(topic, anchor ?? null);
        },
      },
      t("help.readMore"),
    ),
  );
}
