import { ecuSelect } from "../components/ecu-select";
import { valueInput, type ValueInput } from "../components/value-input";
import {
  badge,
  button,
  card,
  checkbox,
  field,
  jsonView,
  numberInput,
  row,
  select,
  stepView,
  table,
  textInput,
} from "../components/ui";
import { h, replace } from "../dom";
import { t } from "../i18n";
import type { RoutineDef, StepRunResponse } from "../types";
import type { AppCtx, View } from "../view";

export function createRoutinesView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const ecuSel = ecuSelect(store);
  const catBox = h("div");
  const formBox = h("div");
  const resultBox = h("div");
  let current: RoutineDef | null = null;

  const renderCatalog = () => {
    replace(
      catBox,
      table<RoutineDef>(
        [
          { key: "id", label: "RID", render: (r) => h("code", null, r.id_hex) },
          {
            key: "name",
            label: t("common.name"),
            render: (r) => h("span", { title: r.description }, r.name),
          },
          { key: "sup", label: t("routine.supports"), render: (r) => r.supports.map((s) => badge(s)) },
          {
            key: "p",
            label: t("routine.params"),
            render: (r) => r.start_params.map((p) => p.name).join(", ") || "–",
          },
          {
            key: "res",
            label: t("routine.results"),
            render: (r) => r.result_fields.map((p) => p.name).join(", ") || "–",
          },
        ],
        store.routines,
        { onRow: (r) => selectRoutine(r), rowClass: (r) => (r.id === current?.id ? "row-selected" : "") },
      ),
    );
  };

  const selectRoutine = (r: RoutineDef | null) => {
    current = r;
    renderCatalog();
    const ridIn = textInput(r?.id_hex ?? "", { class: "mono w-sm", placeholder: "0x0201" });
    const action = select(
      ["start", "stop", "results"].map((a) => ({
        value: a,
        label: t(`routine.act.${a}` as "routine.act.start"),
      })),
      "start",
    );
    const paramsBox = h("div", { class: "grid" });
    const useRaw = checkbox(t("did.useRaw"), false);
    const rawIn = textInput("", { class: "mono", placeholder: "01 02", hidden: true });
    let inputs: { name: string; inp: ValueInput }[] = [];
    const renderParams = () => {
      const specs =
        action.value === "stop"
          ? (r?.stop_params ?? [])
          : action.value === "start"
            ? (r?.start_params ?? [])
            : [];
      inputs = specs.map((s) => ({ name: s.name ?? "", inp: valueInput(s) }));
      replace(paramsBox, ...inputs.map((i) => field(i.name, i.inp.el)));
      paramsBox.hidden = useRaw.input.checked;
      rawIn.hidden = !useRaw.input.checked;
    };
    action.addEventListener("change", renderParams);
    useRaw.input.addEventListener("change", renderParams);
    const run = async () => {
      const body: Record<string, unknown> = {
        ecu: store.selectedEcu,
        routine: ridIn.value.trim(),
        action: action.value,
      };
      if (useRaw.input.checked) body["raw"] = rawIn.value;
      else body["params"] = Object.fromEntries(inputs.map((i) => [i.name, i.inp.get()]));
      const res = await api.post<StepRunResponse>("/routines/control", body);
      replace(
        resultBox,
        stepView(res.step),
        res.step.decoded?.fields ? jsonView(res.step.decoded.fields) : null,
      );
    };
    replace(
      formBox,
      h(
        "div",
        { class: "grid" },
        field(t("header.ecu"), ecuSel.el),
        field("RID", ridIn),
        field(t("routine.action"), action, undefined, undefined, "routines.action"),
      ),
      paramsBox,
      useRaw.el,
      rawIn,
      row(button(t("routine.run"), run, { kind: "primary" })),
    );
    renderParams();
  };

  // --- Transfer ------------------------------------------------------------------------------------
  const dirSel = select(
    [
      { value: "download", label: t("transfer.download") },
      { value: "upload", label: t("transfer.upload") },
    ],
    "download",
  );
  const addrIn = textInput("0x00010000", { class: "mono w-sm" });
  const sizeIn = textInput("", { class: "mono w-sm", placeholder: t("transfer.sizeHint") });
  const dataIn = h("textarea", {
    class: "mono",
    rows: "3",
    placeholder: "00 11 22 33 …",
    spellcheck: "false",
  });
  const alfidIn = textInput("0x44", { class: "mono w-xs" });
  const dfiIn = textInput("0x00", { class: "mono w-xs" });
  const blIn = numberInput("", { min: "3", class: "w-sm", placeholder: t("transfer.blHint") });
  const transferResult = h("div");
  const syncTransfer = () => {
    dataIn.disabled = dirSel.value === "upload";
  };
  dirSel.addEventListener("change", syncTransfer);
  const doTransfer = async () => {
    const body: Record<string, unknown> = {
      ecu: store.selectedEcu,
      direction: dirSel.value,
      address: addrIn.value.trim(),
      alfid: alfidIn.value.trim() || "0x44",
      data_format: dfiIn.value.trim() || "0x00",
    };
    if (sizeIn.value.trim()) body["size"] = sizeIn.value.trim();
    if (dirSel.value === "download" && dataIn.value.trim()) body["data"] = dataIn.value.trim();
    if (blIn.value) body["block_length"] = Number(blIn.value);
    const r = await api.post<StepRunResponse>("/transfer", body);
    const vars = r.vars ?? {};
    replace(
      transferResult,
      stepView(r.step),
      r.step.details && Object.keys(r.step.details).length ? jsonView(r.step.details) : null,
      Object.keys(vars).length ? h("div", null, h("strong", null, t("transfer.vars")), jsonView(vars)) : null,
    );
  };
  syncTransfer();

  const el = h(
    "div",
    { class: "view-grid" },
    card(t("routine.catalog"), catBox),
    h(
      "div",
      { class: "two-col" },
      card(t("routine.control"), formBox, resultBox),
      card(
        t("transfer.title"),
        h(
          "div",
          { class: "grid" },
          field(t("transfer.direction"), dirSel),
          field(t("transfer.address"), addrIn),
          field(t("transfer.size"), sizeIn),
          field("ALFID", alfidIn, t("transfer.alfidHint"), undefined, "transfer.alfid"),
          field(t("transfer.dfi"), dfiIn),
          field(t("transfer.blockLength"), blIn, undefined, undefined, "transfer.block_length"),
        ),
        field(t("transfer.data"), dataIn, undefined, "field-wide"),
        row(button(t("transfer.start"), doTransfer, { kind: "primary" })),
        transferResult,
      ),
    ),
  );

  const off = store.changed.on((k) => {
    if (k === "catalogs") {
      renderCatalog();
      if (!current) selectRoutine(store.routines[0] ?? null);
    }
  });
  renderCatalog();
  selectRoutine(store.routines[0] ?? null);
  return {
    el,
    destroy: () => {
      off();
      ecuSel.dispose();
    },
  };
}
