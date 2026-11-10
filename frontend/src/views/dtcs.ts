import { fillSelect, statusBitsFromMask, subfunctionOptions } from "../catalog";
import { ecuSelect } from "../components/ecu-select";
import { toast } from "../components/toast";
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
  confirmDialog,
} from "../components/ui";
import { h, replace } from "../dom";
import { byteHex, parseIntLoose } from "../hex";
import { t } from "../i18n";
import type { StepRunResponse } from "../types";
import type { AppCtx, View } from "../view";

interface DtcRow {
  code: number;
  code_hex: string;
  display?: string;
  status?: number;
  status_hex?: string;
  status_bits?: Record<string, boolean>;
  name?: string | null;
  description?: string | null;
}

export function dtcStatusBadges(bits: Record<string, boolean> | undefined, order: string[]): HTMLElement {
  const names = order.length ? order : Object.keys(bits ?? {});
  return h(
    "span",
    { class: "bits" },
    names.map((n) => h("span", { class: ["badge", bits?.[n] ? "badge-on" : "badge-off"], title: n }, n)),
  );
}

export function createDtcsView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const ecuSel = ecuSelect(store);
  const subSel = h("select");
  const maskIn = textInput("FF", { class: "mono w-xs" });
  const maskBits = h("div", { class: "mask-bits" });
  const extraIn = textInput("", { class: "mono w-sm", placeholder: t("dtc.extraHint") });
  const tableBox = h("div");
  const stepBox = h("div");
  const groupIn = textInput("FFFFFF", { class: "mono w-sm" });
  const clearBox = h("div");

  const maskValue = (): number => {
    try {
      return parseIntLoose(maskIn.value, true) & 0xff;
    } catch {
      return 0xff;
    }
  };

  const renderMaskBits = () => {
    const m = maskValue();
    replace(
      maskBits,
      store.dtcStatusBits.map((name, i) => {
        const c = checkbox(`${i}: ${name}`, Boolean((m >> i) & 1), (v) => {
          const cur = maskValue();
          maskIn.value = byteHex(v ? cur | (1 << i) : cur & ~(1 << i));
        });
        return c.el;
      }),
    );
  };
  maskIn.addEventListener("change", renderMaskBits);

  const renderSubs = () => {
    const svc = store.service(0x19);
    fillSelect(subSel, subfunctionOptions(svc), subSel.value || "2");
    renderMaskBits();
  };

  const read = async () => {
    const body: Record<string, unknown> = {
      ecu: store.selectedEcu,
      subfunction: Number(subSel.value || 2),
      mask: maskValue(),
    };
    if (extraIn.value.trim()) body["extra"] = extraIn.value.trim();
    const r = await api.post<StepRunResponse>("/dtcs/read", body);
    replace(stepBox, stepView(r.step));
    const fields = r.step.decoded?.fields ?? {};
    const dtcs = (fields["dtcs"] as DtcRow[] | undefined) ?? [];
    const other = Object.entries(fields).filter(([k]) => k !== "dtcs");
    replace(
      tableBox,
      other.length
        ? kv(other.map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : String(v)]))
        : null,
      table<DtcRow>(
        [
          { key: "code", label: "DTC", render: (d) => h("code", null, d.code_hex) },
          { key: "disp", label: t("dtc.display"), render: (d) => h("strong", null, d.display ?? "") },
          {
            key: "name",
            label: t("common.name"),
            render: (d) =>
              h(
                "div",
                null,
                d.name ?? h("span", { class: "muted" }, t("dtc.unknown")),
                d.description ? h("div", { class: "muted small" }, d.description) : null,
              ),
          },
          {
            key: "st",
            label: t("dtc.status"),
            render: (d) =>
              h("code", null, d.status_hex ?? (d.status !== undefined ? byteHex(d.status) : "–")),
          },
          {
            key: "bits",
            label: t("dtc.statusBits"),
            render: (d) =>
              d.status_bits
                ? dtcStatusBadges(d.status_bits, store.dtcStatusBits)
                : d.status !== undefined
                  ? statusBitsFromMask(d.status, store.dtcStatusBits).map((n) => badge(n, "on"))
                  : "–",
          },
        ],
        dtcs,
        {
          rowClass: (d) =>
            d.status_bits?.["confirmedDTC"] ? "row-fail" : d.status_bits?.["pendingDTC"] ? "row-warn" : "",
        },
      ),
    );
  };

  const clear = async () => {
    if (!(await confirmDialog(t("dtc.clearConfirm", { ecu: store.selectedEcu ?? "", group: groupIn.value }))))
      return;
    const r = await api.post<StepRunResponse>("/dtcs/clear", {
      ecu: store.selectedEcu,
      group: `0x${groupIn.value.replace(/^0x/i, "")}`,
    });
    replace(clearBox, stepView(r.step));
    toast(
      r.step.status === "passed" ? t("dtc.cleared") : (r.step.decoded?.text ?? r.step.status),
      r.step.status === "passed" ? "success" : "warning",
    );
  };

  const el = h(
    "div",
    { class: "view-grid" },
    card(
      t("dtc.read"),
      h(
        "div",
        { class: "grid" },
        field(t("header.ecu"), ecuSel.el),
        field(t("uds.subfunction"), subSel, undefined, undefined, "dtcs.subfunction"),
        field(t("dtc.mask"), maskIn, t("dtc.maskHint"), undefined, "dtcs.mask"),
        field(t("dtc.extra"), extraIn),
      ),
      maskBits,
      row(button(t("dtc.readBtn"), read, { kind: "primary" })),
      tableBox,
      stepBox,
    ),
    card(
      t("dtc.clear"),
      row(
        field(t("dtc.group"), groupIn, t("dtc.groupHint"), undefined, "dtcs.clear_group"),
        button(t("dtc.clearBtn"), clear, { kind: "danger" }),
      ),
      clearBox,
    ),
  );

  const off = store.changed.on((k) => k === "catalogs" && renderSubs());
  renderSubs();
  return {
    el,
    submit: () => void read(),
    destroy: () => {
      off();
      ecuSel.dispose();
    },
  };
}
