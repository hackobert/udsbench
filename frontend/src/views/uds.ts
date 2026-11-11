import {
  buildPayload,
  didOptions,
  fillSelect,
  paramsFor,
  routineOptions,
  serviceOptions,
  subfunctionOptions,
} from "../catalog";
import { ecuSelect } from "../components/ecu-select";
import { toast, toastError } from "../components/toast";
import {
  badge,
  button,
  card,
  checkbox,
  field,
  jsonView,
  row,
  select,
  textInput,
  hexAscii,
  udsResultView,
} from "../components/ui";
import { debounce, h, replace } from "../dom";
import { isValidHex, normalizeHex, prettyHex } from "../hex";
import { t } from "../i18n";
import { renderPreview } from "../preview";
import * as storage from "../storage";
import type { PreviewResponse, ServiceParam, UdsResult, UdsService } from "../types";
import type { AppCtx, View } from "../view";

interface HistoryEntry {
  ecu: string | null;
  payload: string;
  functional: boolean;
  ts: number;
  summary: string;
  ok: boolean | null;
}

const HISTORY_MAX = 30;

export function createUdsView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const ecuSel = ecuSelect(store);
  const addrSel = select(
    [
      { value: "phys", label: t("uds.physical") },
      { value: "func", label: t("uds.functional") },
    ],
    storage.load<string>("uds.addr", "phys"),
  );
  const serviceSel = h("select", { "aria-label": t("uds.service") });
  const subSel = h("select", { "aria-label": t("uds.subfunction") });
  const subField = field(t("uds.subfunction"), subSel, undefined, undefined, "uds.subfunction");
  const sprm = checkbox(t("uds.sprm"), false, undefined, t("uds.sprmHint"), "uds.sprm");
  const paramBox = h("div", { class: "grid params" });
  const payloadIn = h("textarea", {
    class: "mono payload-input",
    rows: "2",
    spellcheck: "false",
    placeholder: "22 F1 00",
    "aria-label": t("uds.payload"),
  });
  payloadIn.value = storage.load<string>("uds.payload", "22 F1 00");
  const hexState = h("span", { class: "field-hint" });
  const previewBox = h("div", { class: "preview-box" });
  const resultBox = h("div", { class: "result-box" }, h("div", { class: "empty" }, t("uds.noResult")));
  const historyBox = h("div", { class: "history" });
  let paramInputs: { p: ServiceParam; get: () => string }[] = [];
  let currentService: UdsService | null = null;

  // --- Raw-Frame-Modus -----------------------------------------------------------------------
  const rawMode = checkbox(t("uds.rawMode"), false, () => updateMode(), t("uds.rawModeHint"), "uds.raw");
  const rawChannel = textInput("default", { class: "w-sm" });
  const rawId = textInput("700", { class: "w-sm mono" });
  const rawData = textInput("02 3E 00 CC CC CC CC CC", { class: "mono" });
  const rawExt = checkbox(t("uds.rawExt"), false);
  const rawFd = checkbox("FD", false);
  const rawBrs = checkbox("BRS", false);
  const rawBox = card(
    t("uds.rawTitle"),
    h(
      "div",
      { class: "grid" },
      field(t("conn.channel"), rawChannel),
      field(t("uds.rawId"), rawId, t("uds.rawIdHint")),
      field(t("uds.rawData"), rawData),
    ),
    row(rawExt.el, rawFd.el, rawBrs.el),
    row(button(t("uds.rawSend"), () => sendRaw(), { kind: "primary" })),
  );

  const builderCard = card(
    t("uds.title"),
    h(
      "div",
      { class: "grid" },
      field(t("header.ecu"), ecuSel.el, undefined, undefined, "uds.ecu"),
      field(t("uds.addressing"), addrSel, undefined, undefined, "uds.functional"),
      field(t("uds.service"), serviceSel, undefined, undefined, "uds.service"),
      subField,
    ),
    sprm.el,
    paramBox,
    field(t("uds.payload"), payloadIn, undefined, "field-wide", "uds.payload"),
    hexState,
    row(
      button(t("uds.send"), () => send(), { kind: "primary", title: "Strg+Enter", cls: "send-btn" }),
      button(
        t("uds.format"),
        () => {
          payloadIn.value = prettyHex(payloadIn.value);
          onPayloadChange();
        },
        { kind: "ghost" },
      ),
      h("span", { class: "muted" }, t("uds.sendHint")),
    ),
  );
  const previewCard = card(t("preview.title"), previewBox);
  const left = h("div", { class: "col" }, rawMode.el, builderCard, rawBox, previewCard);
  const right = h(
    "div",
    { class: "col" },
    card(t("uds.responseTitle"), resultBox),
    card(
      h(
        "span",
        null,
        t("uds.history"),
        " ",
        button(
          t("common.clear"),
          () => {
            storage.save("uds.history", []);
            renderHistory();
          },
          { kind: "ghost" },
        ),
      ),
      historyBox,
    ),
  );
  const el = h("div", { class: "two-col" }, left, right);

  const updateMode = () => {
    const raw = rawMode.input.checked;
    builderCard.hidden = raw;
    previewCard.hidden = raw;
    rawBox.hidden = !raw;
  };

  // --- Service-/Parameter-Builder -------------------------------------------------------------
  const renderServices = () => {
    const prev =
      store.services.length && serviceSel.options.length > 1
        ? serviceSel.value
        : storage.load<string>("uds.sid", "34");
    fillSelect(serviceSel, serviceOptions(store.services), prev, t("uds.serviceFree"));
    onServiceChange(false);
  };

  const onServiceChange = (rebuild = true) => {
    const sid = Number(serviceSel.value);
    currentService = serviceSel.value ? (store.service(sid) ?? null) : null;
    if (store.services.length) storage.save("uds.sid", serviceSel.value);
    const subs = subfunctionOptions(currentService);
    fillSelect(subSel, subs);
    subField.hidden = !subs.length;
    sprm.el.hidden = !(currentService?.has_subfunction && currentService.sprm_allowed);
    if (sprm.el.hidden) sprm.input.checked = false;
    renderParams();
    if (rebuild) rebuildPayload();
  };

  const renderParams = () => {
    paramInputs = [];
    const sub = subSel.value ? Number(subSel.value) : null;
    const params = paramsFor(currentService, sub);
    const fields = params.map((p, idx) => {
      let control: HTMLElement;
      let get: () => string;
      if (p.kind === "did" || p.kind === "rid") {
        const opts = p.kind === "did" ? didOptions(store.dids) : routineOptions(store.routines);
        const sel = fillSelect(h("select"), opts);
        sel.appendChild(h("option", { value: "__free" }, t("uds.freeInput")));
        const free = textInput("", { class: "mono w-sm", placeholder: "F1 90", hidden: true });
        // Vorauswahl aus der aktuellen Nutzlast (z. B. "22 F1 00" → DID 0xF100)
        if (idx === 0) {
          try {
            const hex = normalizeHex(payloadIn.value);
            const off = (1 + (currentService?.has_subfunction ? 1 : 0)) * 2;
            const v = hex.slice(off, off + 4);
            if (v.length === 4 && opts.some((o) => o.value === `0x${v}`)) sel.value = `0x${v}`;
          } catch {
            /* ignorieren */
          }
        }
        sel.addEventListener("change", () => {
          free.hidden = sel.value !== "__free";
          rebuildPayload();
        });
        free.addEventListener("input", rebuildPayload);
        control = h("div", { class: "inline" }, sel, free);
        get = () => (sel.value === "__free" ? free.value : sel.value);
      } else {
        const inp = textInput(p.default ?? "", {
          class: "mono",
          placeholder: p.kind === "hex" ? "AA BB …" : p.kind,
        });
        inp.addEventListener("input", rebuildPayload);
        control = inp;
        get = () => inp.value;
      }
      paramInputs.push({ p, get });
      return field(
        `${p.name}${p.optional ? ` (${t("common.optional")})` : ""}`,
        control,
        p.description || p.kind,
      );
    });
    replace(paramBox, ...fields);
  };

  const rebuildPayload = () => {
    if (!currentService) return;
    const params: Record<string, string> = {};
    for (const pi of paramInputs) params[pi.p.name] = pi.get();
    try {
      payloadIn.value = buildPayload({
        service: currentService,
        sub: subSel.value ? Number(subSel.value) : null,
        sprm: sprm.input.checked,
        params,
      });
      payloadIn.classList.remove("invalid");
    } catch (exc) {
      hexState.textContent = (exc as Error).message;
      payloadIn.classList.add("invalid");
      return;
    }
    onPayloadChange();
  };

  serviceSel.addEventListener("change", () => onServiceChange());
  subSel.addEventListener("change", () => {
    renderParams();
    rebuildPayload();
  });
  sprm.input.addEventListener("change", rebuildPayload);

  // --- Vorschau ------------------------------------------------------------------------------------
  let previewSeq = 0;
  const loadPreview = debounce(async () => {
    const payload = payloadIn.value;
    const ecu = store.selectedEcu;
    if (!ecu) {
      replace(previewBox, h("div", { class: "empty" }, t("common.noEcus")));
      return;
    }
    if (!isValidHex(payload, false)) {
      replace(previewBox, h("div", { class: "error-box" }, t("uds.invalidHex")));
      return;
    }
    const seq = ++previewSeq;
    try {
      const p = await api.post<PreviewResponse>("/uds/preview", {
        ecu,
        payload,
        functional: addrSel.value === "func",
      });
      if (seq !== previewSeq) return;
      const sid = Number.parseInt(normalizeHex(payload).slice(0, 2), 16);
      replace(previewBox, renderPreview(p, store.service(sid) ?? null));
    } catch (exc) {
      if (seq !== previewSeq) return;
      const e = exc as Error & { details?: unknown };
      replace(previewBox, h("div", { class: "error-box" }, e.message));
    }
  }, 250);

  /** Manuell getippte Nutzlast: Service-Auswahl (nur Anzeige) an das erste Byte angleichen. */
  const syncServiceFromPayload = () => {
    try {
      const first = normalizeHex(payloadIn.value).slice(0, 2);
      if (!first) return;
      const sid = String(parseInt(first, 16));
      if (sid !== serviceSel.value && store.service(Number(sid))) {
        serviceSel.value = sid;
        onServiceChange(false);
      }
    } catch {
      /* ungültige Eingabe – Hinweis zeigt onPayloadChange */
    }
  };

  const onPayloadChange = () => {
    storage.save("uds.payload", payloadIn.value);
    try {
      const n = normalizeHex(payloadIn.value).length / 2;
      hexState.textContent = t("uds.bytes", { n });
      payloadIn.classList.remove("invalid");
    } catch (exc) {
      hexState.textContent = (exc as Error).message;
      payloadIn.classList.add("invalid");
    }
    loadPreview();
  };
  payloadIn.addEventListener("input", () => {
    syncServiceFromPayload();
    onPayloadChange();
  });
  addrSel.addEventListener("change", () => {
    storage.save("uds.addr", addrSel.value);
    loadPreview();
  });

  // --- Senden ----------------------------------------------------------------------------------------
  const send = async () => {
    if (rawMode.input.checked) return sendRaw();
    const payload = payloadIn.value.trim();
    if (!isValidHex(payload, false)) {
      toast(t("uds.invalidHex"), "error");
      return;
    }
    const body = { ecu: store.selectedEcu, payload, functional: addrSel.value === "func" };
    replace(resultBox, h("div", { class: "muted" }, t("uds.sending")));
    try {
      const r = await api.post<UdsResult>("/uds/request", body);
      replace(resultBox, udsResultView(r));
      addHistory({
        ecu: body.ecu,
        payload: prettyHex(payload),
        functional: body.functional,
        ts: Date.now(),
        summary: r.response ?? r.error ?? (r.suppress_positive ? "SPRM" : "–"),
        ok: r.error ? false : r.negative ? false : r.positive ? true : null,
      });
    } catch (exc) {
      replace(resultBox, h("div", { class: "error-box" }, (exc as Error).message));
      toastError(exc);
    }
  };

  const sendRaw = async () => {
    const body = {
      channel: rawChannel.value.trim() || "default",
      id: /^0x/i.test(rawId.value.trim()) ? rawId.value.trim() : `0x${rawId.value.trim()}`,
      data: rawData.value,
      extended: rawExt.input.checked,
      fd: rawFd.input.checked,
      brs: rawBrs.input.checked,
    };
    try {
      const r = await api.post<{ frame: unknown }>("/can/send", body);
      replace(resultBox, h("div", null, badge(t("uds.rawSent"), "ok"), jsonView(r.frame)));
    } catch (exc) {
      toastError(exc);
    }
  };

  // --- Verlauf --------------------------------------------------------------------------------------
  const addHistory = (e: HistoryEntry) => {
    const list = storage.load<HistoryEntry[]>("uds.history", []);
    list.unshift(e);
    storage.save("uds.history", list.slice(0, HISTORY_MAX));
    renderHistory();
  };
  const renderHistory = () => {
    const list = storage.load<HistoryEntry[]>("uds.history", []);
    replace(
      historyBox,
      list.length
        ? h(
            "ul",
            { class: "history-list" },
            list.map((e) =>
              h(
                "li",
                {
                  class: ["history-item", e.ok === true ? "h-ok" : e.ok === false ? "h-fail" : null],
                  title: new Date(e.ts).toLocaleString(),
                  onclick: () => {
                    if (e.ecu) store.selectEcu(e.ecu);
                    addrSel.value = e.functional ? "func" : "phys";
                    payloadIn.value = e.payload;
                    onPayloadChange();
                  },
                },
                h("code", { class: "mono" }, e.payload),
                h("span", { class: "muted" }, ` ${e.ecu ?? ""}${e.functional ? " (func)" : ""} → `),
                isValidHex(e.summary, false)
                  ? hexAscii(e.summary, { inline: true })
                  : h("code", { class: "mono" }, e.summary),
              ),
            ),
          )
        : h("div", { class: "empty" }, t("common.noEntries")),
    );
  };

  const offs = [
    store.changed.on((k) => {
      if (k === "catalogs") renderServices();
      if (k === "selectedEcu") loadPreview();
    }),
  ];

  renderServices();
  renderHistory();
  updateMode();
  onPayloadChange();

  return {
    el,
    submit: () => void send(),
    show: () => loadPreview(),
    destroy: () => {
      offs.forEach((o) => o());
      ecuSel.dispose();
    },
  };
}
