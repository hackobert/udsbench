import { infoIcon } from "../help";
import { didOptions, fillSelect } from "../catalog";
import { ecuSelect } from "../components/ecu-select";
import { toast } from "../components/toast";
import { valueInput, type ValueInput } from "../components/value-input";
import {
  badge,
  button,
  card,
  checkbox,
  field,
  row,
  select,
  stepView,
  table,
  textInput,
  valueView,
} from "../components/ui";
import { h, replace } from "../dom";
import { t } from "../i18n";
import type { DidDef, StepRunResponse } from "../types";
import type { AppCtx, View } from "../view";

type Rec = { did_hex: string; name?: string; value?: unknown; unit?: string; raw?: string };

export function createDidsView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const ecuSel = ecuSelect(store);
  const values = new Map<string, Rec>();
  const checked = new Set<string>();
  const tableBox = h("div");
  const readResult = h("div");
  const writeResult = h("div");
  const ioResult = h("div");

  const read = async (dids: string[]) => {
    if (!dids.length) {
      toast(t("did.noneSelected"), "warning");
      return;
    }
    const r = await api.post<StepRunResponse>("/dids/read", { ecu: store.selectedEcu, dids });
    const recs = (r.step.decoded?.fields?.["records"] as Rec[] | undefined) ?? [];
    for (const rec of recs) values.set(rec.did_hex, rec);
    replace(readResult, stepView(r.step));
    renderTable();
  };

  const renderTable = () => {
    replace(
      tableBox,
      table<DidDef>(
        [
          {
            key: "sel",
            label: "",
            render: (d) => {
              const cb = h("input", {
                type: "checkbox",
                checked: checked.has(d.id_hex),
                "aria-label": d.name,
              });
              cb.addEventListener("change", () =>
                cb.checked ? checked.add(d.id_hex) : checked.delete(d.id_hex),
              );
              return cb;
            },
          },
          { key: "id", label: "DID", render: (d) => h("code", null, d.id_hex) },
          {
            key: "name",
            label: t("common.name"),
            render: (d) => h("span", { title: d.description }, d.name),
          },
          { key: "type", label: t("did.type"), render: (d) => `${d.type}${d.length ? `/${d.length}` : ""}` },
          {
            key: "access",
            label: t("did.access"),
            render: (d) => [badge(d.access), d.io_control ? badge("IO", "run") : null],
          },
          {
            key: "value",
            label: t("common.value"),
            render: (d) => {
              const v = values.get(d.id_hex);
              return v ? valueView(v.value, v.unit || d.unit) : h("span", { class: "muted" }, "–");
            },
          },
          {
            key: "raw",
            label: t("common.raw"),
            render: (d) => h("code", { class: "mono" }, values.get(d.id_hex)?.raw ?? ""),
          },
          {
            key: "act",
            label: "",
            render: (d) =>
              d.access.includes("read")
                ? button(t("did.read"), () => read([d.id_hex]), { kind: "ghost" })
                : null,
          },
        ],
        store.dids,
      ),
    );
  };

  // --- Schreiben ------------------------------------------------------------------------------------
  const writeSel = h("select");
  const writeBox = h("div");
  const writeRaw = checkbox(t("did.useRaw"), false);
  const writeRawIn = textInput("", { class: "mono", placeholder: "01 02" });
  let writeInput: ValueInput | null = null;
  const renderWriteInput = () => {
    const d = store.dids.find((x) => x.id_hex === writeSel.value);
    writeInput = d ? valueInput(d) : null;
    const cur = d ? values.get(d.id_hex) : undefined;
    if (writeInput && cur) writeInput.set(cur.value);
    replace(
      writeBox,
      writeInput ? field(t("common.value"), writeInput.el, d?.unit ? `[${d.unit}]` : d?.type) : null,
    );
    writeBox.hidden = writeRaw.input.checked;
    writeRawIn.hidden = !writeRaw.input.checked;
  };
  writeSel.addEventListener("change", renderWriteInput);
  writeRaw.input.addEventListener("change", renderWriteInput);
  const doWrite = async () => {
    const body: Record<string, unknown> = { ecu: store.selectedEcu, did: writeSel.value };
    if (writeRaw.input.checked) body["raw"] = writeRawIn.value;
    else body["value"] = writeInput?.get() ?? null;
    const r = await api.post<StepRunResponse>("/dids/write", body);
    replace(writeResult, stepView(r.step));
  };

  // --- IO-Control -----------------------------------------------------------------------------------
  const ioSel = h("select");
  const ioParam = select(
    [
      { value: "0", label: "00 returnControlToECU" },
      { value: "1", label: "01 resetToDefault" },
      { value: "2", label: "02 freezeCurrentState" },
      { value: "3", label: "03 shortTermAdjustment" },
    ],
    "3",
  );
  const ioBox = h("div");
  const ioRaw = checkbox(t("did.useRaw"), false);
  const ioRawIn = textInput("", { class: "mono", placeholder: "64" });
  let ioInput: ValueInput | null = null;
  const renderIoInput = () => {
    const d = store.dids.find((x) => x.id_hex === ioSel.value);
    ioInput = d ? valueInput(d) : null;
    const needValue = ioParam.value === "3";
    replace(
      ioBox,
      ioInput && needValue && !ioRaw.input.checked ? field(t("did.controlState"), ioInput.el) : null,
    );
    ioRawIn.hidden = !ioRaw.input.checked;
  };
  ioSel.addEventListener("change", renderIoInput);
  ioParam.addEventListener("change", renderIoInput);
  ioRaw.input.addEventListener("change", renderIoInput);
  const doIo = async () => {
    const body: Record<string, unknown> = {
      ecu: store.selectedEcu,
      did: ioSel.value,
      parameter: Number(ioParam.value),
    };
    if (ioRaw.input.checked) body["raw"] = ioRawIn.value;
    else if (ioParam.value === "3") body["value"] = ioInput?.get() ?? null;
    const r = await api.post<StepRunResponse>("/dids/io-control", body);
    replace(ioResult, stepView(r.step));
  };

  const renderSelects = () => {
    fillSelect(writeSel, didOptions(store.dids, { access: "write" }), writeSel.value || undefined);
    const io = didOptions(store.dids, { ioControl: true });
    fillSelect(ioSel, io.length ? io : didOptions(store.dids), ioSel.value || undefined);
    renderWriteInput();
    renderIoInput();
  };

  const el = h(
    "div",
    { class: "view-grid" },
    card(
      h("span", null, t("did.catalog"), infoIcon("dids.catalog")),
      row(
        field(t("header.ecu"), ecuSel.el),
        button(t("did.readSelected"), () => read([...checked]), { kind: "primary" }),
        button(t("did.readAll"), () =>
          read(store.dids.filter((d) => d.access.includes("read")).map((d) => d.id_hex)),
        ),
      ),
      tableBox,
      readResult,
    ),
    h(
      "div",
      { class: "two-col" },
      card(
        t("did.write"),
        field("DID", writeSel, undefined, undefined, "dids.write_value"),
        writeRaw.el,
        writeBox,
        writeRawIn,
        row(button(t("did.writeBtn"), doWrite, { kind: "primary" })),
        writeResult,
      ),
      card(
        t("did.io"),
        h(
          "div",
          { class: "grid" },
          field("DID", ioSel),
          field(t("did.ioParam"), ioParam, undefined, undefined, "dids.io_parameter"),
        ),
        ioRaw.el,
        ioBox,
        ioRawIn,
        row(button(t("did.ioBtn"), doIo, { kind: "primary" })),
        ioResult,
      ),
    ),
  );

  const off = store.changed.on((k) => {
    if (k === "catalogs") {
      renderTable();
      renderSelects();
    }
  });
  renderTable();
  renderSelects();
  return {
    el,
    destroy: () => {
      off();
      ecuSel.dispose();
    },
  };
}
