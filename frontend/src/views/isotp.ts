import { infoIcon } from "../help";
import { toast, toastError } from "../components/toast";
import {
  badge,
  button,
  card,
  checkbox,
  field,
  numberInput,
  row,
  select,
  table,
  textInput,
} from "../components/ui";
import { formatErrorDetails, ApiError } from "../api";
import { debounce, h, replace } from "../dom";
import { byteHex, isValidHex, parseIntLoose, stminText, toHexId } from "../hex";
import { t } from "../i18n";
import { renderPreview } from "../preview";
import * as storage from "../storage";
import type { IsoTpProfile, PreviewResponse } from "../types";
import type { AppCtx, View } from "../view";

const PAD_PRESETS = ["00", "AA", "CC", "FF"];
const FD_DLS = [8, 12, 16, 20, 24, 32, 48, 64];

/** Editierbare Felder eines Profils (ohne berechnete Felder der Listenantwort). */
export function editableProfile(p: IsoTpProfile): IsoTpProfile {
  const copy: Partial<IsoTpProfile> & Record<string, unknown> = { ...p };
  delete copy.ecus;
  delete copy.tx_dl;
  delete copy.st_min_text;
  return copy as IsoTpProfile;
}

export function createIsoTpView(ctx: AppCtx): View {
  const { api, store } = ctx;
  let profiles: IsoTpProfile[] = [];
  let current: IsoTpProfile | null = null;
  const listBox = h("div");
  const editorBox = h("div");
  const previewBox = h("div", { class: "preview-box" });
  const errorBox = h("div");
  const sampleIn = textInput(storage.load<string>("isotp.sample", "2E 02 00 01 02 03 04 05 06 07 08 09 0A"), {
    class: "mono",
  });
  const functional = checkbox(t("uds.functional"), false);

  const load = async () => {
    profiles = await api.get<IsoTpProfile[]>("/isotp/profiles");
    renderList();
    const keep = current ? profiles.find((p) => p.name === current?.name) : profiles[0];
    if (keep) edit(keep);
  };

  const renderList = () => {
    replace(
      listBox,
      table<IsoTpProfile>(
        [
          { key: "name", label: t("common.name"), render: (p) => h("strong", null, p.name) },
          { key: "addr", label: t("isotp.addressing"), render: (p) => p.addressing },
          {
            key: "ids",
            label: "TX/RX",
            render: (p) => h("code", null, `${toHexId(p.tx_id)}/${toHexId(p.rx_id)}`),
          },
          {
            key: "pad",
            label: t("isotp.padding"),
            render: (p) => (p.padding.enabled ? `0x${byteHex(p.padding.byte)}` : t("common.off")),
          },
          { key: "fd", label: "FD", render: (p) => (p.can_fd ? `FD ${p.fd_tx_dl}` : "CAN") },
          { key: "stmin", label: "STmin", render: (p) => p.st_min_text ?? stminText(p.st_min) },
          { key: "ecus", label: "ECUs", render: (p) => (p.ecus ?? []).map((e) => badge(e)) },
        ],
        profiles,
        { onRow: (p) => edit(p), rowClass: (p) => (p.name === current?.name ? "row-selected" : "") },
      ),
    );
  };

  // Formularsteuerelemente (werden je Profil neu erzeugt)
  let readForm: () => IsoTpProfile = () => {
    throw new Error("kein Profil");
  };

  const hexField = (v: number | null, width = 3) =>
    textInput(v === null ? "" : toHexId(v, width), { class: "mono w-sm" });

  const edit = (p: IsoTpProfile) => {
    current = editableProfile(p);
    renderList();
    const c = current;
    const desc = textInput(c.description);
    const channel = textInput(c.channel, { class: "w-sm" });
    const txId = hexField(c.tx_id);
    const rxId = hexField(c.rx_id);
    const fnId = hexField(c.functional_id);
    const extId = checkbox(t("isotp.extendedId"), c.extended_id, undefined, undefined, "isotp.extended_id");
    const addressing = select(
      ["normal", "extended", "mixed"].map((v) => ({
        value: v,
        label: t(`isotp.addr.${v}` as "isotp.addr.normal"),
      })),
      c.addressing,
    );
    const txAe = hexField(c.tx_address_extension, 2);
    const rxAe = hexField(c.rx_address_extension, 2);
    const fnAe = hexField(c.functional_address_extension, 2);
    const aeBox = h(
      "div",
      { class: "grid" },
      field(t("isotp.txAe"), txAe, t("isotp.txAeHint"), undefined, "isotp.tx_address_extension"),
      field(t("isotp.rxAe"), rxAe, t("isotp.rxAeHint"), undefined, "isotp.rx_address_extension"),
      field(t("isotp.fnAe"), fnAe),
    );
    const bs = numberInput(c.block_size, { min: "0", max: "255", class: "w-xs" });
    const stmin = hexField(c.st_min, 2);
    const stminInfo = h("span", { class: "field-hint" });
    const stminOv = hexField(c.st_min_tx_override, 2);
    const wft = numberInput(c.wft_max, { min: "0", class: "w-xs" });
    const padOn = checkbox(t("isotp.paddingOn"), c.padding.enabled, undefined, undefined, "isotp.padding");
    const padByteHex = byteHex(c.padding.byte);
    const padSel = select(
      [
        ...PAD_PRESETS.map((v) => ({ value: v, label: `0x${v}` })),
        { value: "custom", label: t("isotp.custom") },
      ],
      PAD_PRESETS.includes(padByteHex) ? padByteHex : "custom",
    );
    const padCustom = textInput(padByteHex, { class: "mono w-xs" });
    const dlcMode = select(
      [
        { value: "fixed", label: t("isotp.dlcFixed") },
        { value: "minimal", label: t("isotp.dlcMinimal") },
      ],
      c.dlc_mode,
    );
    const fd = checkbox("CAN FD", c.can_fd, undefined, undefined, "isotp.can_fd");
    const fdDl = select(
      FD_DLS.map((n) => ({ value: String(n), label: String(n) })),
      String(c.fd_tx_dl),
    );
    const brs = checkbox(t("isotp.brs"), c.bitrate_switch);
    const maxRx = numberInput(c.max_rx_length, { min: "1", class: "w-sm" });
    const tos = (["n_as", "n_ar", "n_bs", "n_cr"] as const).map(
      (k) => [k, numberInput(c.timeouts[k], { min: "0", class: "w-xs" })] as const,
    );

    const sync = () => {
      aeBox.hidden = addressing.value === "normal";
      padSel.disabled = !padOn.input.checked;
      padCustom.hidden = padSel.value !== "custom" || !padOn.input.checked;
      fdDl.disabled = !fd.input.checked;
      brs.input.disabled = !fd.input.checked;
      try {
        stminInfo.textContent = `= ${stminText(parseIntLoose(stmin.value, true))}`;
      } catch {
        stminInfo.textContent = t("isotp.invalid");
      }
    };

    const optHex = (inp: HTMLInputElement): number | null =>
      inp.value.trim() ? parseIntLoose(inp.value, true) : null;

    readForm = () => ({
      name: c.name,
      description: desc.value,
      channel: channel.value.trim() || "default",
      tx_id: parseIntLoose(txId.value, true),
      rx_id: parseIntLoose(rxId.value, true),
      functional_id: optHex(fnId),
      extended_id: extId.input.checked,
      addressing: addressing.value as IsoTpProfile["addressing"],
      tx_address_extension: addressing.value === "normal" ? null : optHex(txAe),
      rx_address_extension: addressing.value === "normal" ? null : optHex(rxAe),
      functional_address_extension: addressing.value === "normal" ? null : optHex(fnAe),
      block_size: Number(bs.value),
      st_min: parseIntLoose(stmin.value, true),
      st_min_tx_override: optHex(stminOv),
      wft_max: Number(wft.value),
      padding: {
        enabled: padOn.input.checked,
        byte: parseIntLoose(padSel.value === "custom" ? padCustom.value : padSel.value, true),
      },
      dlc_mode: dlcMode.value as IsoTpProfile["dlc_mode"],
      can_fd: fd.input.checked,
      fd_tx_dl: Number(fdDl.value),
      bitrate_switch: brs.input.checked,
      max_rx_length: Number(maxRx.value),
      timeouts: Object.fromEntries(tos.map(([k, inp]) => [k, Number(inp.value)])) as IsoTpProfile["timeouts"],
    });

    const onChange = () => {
      sync();
      schedulePreview();
    };
    editorBox.oninput = onChange;
    editorBox.onchange = onChange;

    replace(
      editorBox,
      h("h4", null, c.name, " ", h("span", { class: "muted" }, c.description)),
      h(
        "fieldset",
        null,
        h("legend", null, t("isotp.ids")),
        h(
          "div",
          { class: "grid" },
          field(t("common.description"), desc),
          field(t("conn.channel"), channel),
          field("TX-ID", txId, t("isotp.txIdHint"), undefined, "isotp.tx_id"),
          field("RX-ID", rxId, t("isotp.rxIdHint"), undefined, "isotp.rx_id"),
          field(t("isotp.functionalId"), fnId, undefined, undefined, "isotp.functional_id"),
          extId.el,
        ),
      ),
      h(
        "fieldset",
        null,
        h("legend", null, t("isotp.addressing")),
        h(
          "div",
          { class: "grid" },
          field(t("isotp.addressing"), addressing, undefined, undefined, "isotp.addressing"),
        ),
        aeBox,
      ),
      h(
        "fieldset",
        null,
        h("legend", null, t("isotp.flow")),
        h(
          "div",
          { class: "grid" },
          field("BS", bs, t("isotp.bsHint"), undefined, "isotp.block_size"),
          field(
            "STmin",
            h("div", { class: "inline" }, stmin, stminInfo),
            t("isotp.stminHint"),
            undefined,
            "isotp.st_min",
          ),
          field(t("isotp.stminOverride"), stminOv),
          field("WFTmax", wft),
        ),
      ),
      h(
        "fieldset",
        null,
        h("legend", null, t("isotp.framing")),
        h(
          "div",
          { class: "grid" },
          padOn.el,
          field(
            t("isotp.paddingByte"),
            h("div", { class: "inline" }, padSel, padCustom),
            undefined,
            undefined,
            "isotp.padding_byte",
          ),
          field(t("isotp.dlcMode"), dlcMode, undefined, undefined, "isotp.dlc_mode"),
          fd.el,
          field("FD TX_DL", fdDl),
          brs.el,
          field(t("isotp.maxRx"), maxRx),
        ),
      ),
      h(
        "fieldset",
        null,
        h("legend", null, t("isotp.timeouts"), infoIcon("isotp.timeouts")),
        h(
          "div",
          { class: "grid" },
          tos.map(([k, inp]) => field(`${k.toUpperCase().replace("_", "_")} [ms]`, inp)),
        ),
      ),
      errorBox,
      row(
        button(t("common.save"), save, { kind: "primary" }),
        button(t("common.reset"), () => edit(p), { kind: "ghost" }),
        h("span", { class: "muted" }, t("isotp.runtimeNote")),
      ),
    );
    sync();
    schedulePreview();
  };

  const save = async () => {
    if (!current) return;
    let prof: IsoTpProfile;
    try {
      prof = readForm();
    } catch (exc) {
      toast((exc as Error).message, "error");
      return;
    }
    try {
      await api.put(`/isotp/profiles/${encodeURIComponent(prof.name)}`, prof);
      replace(errorBox);
      toast(t("isotp.saved", { name: prof.name }), "success");
      await Promise.all([load(), store.refreshEcus()]);
    } catch (exc) {
      const lines =
        exc instanceof ApiError ? [exc.message, ...formatErrorDetails(exc.details)] : [String(exc)];
      replace(
        errorBox,
        h(
          "ul",
          { class: "editor-errors" },
          lines.map((l) => h("li", null, l)),
        ),
      );
      toastError(exc);
    }
  };

  let seq = 0;
  const schedulePreview = debounce(async () => {
    storage.save("isotp.sample", sampleIn.value);
    if (!current) return;
    if (!isValidHex(sampleIn.value, false)) {
      replace(previewBox, h("div", { class: "error-box" }, t("uds.invalidHex")));
      return;
    }
    let prof: IsoTpProfile;
    try {
      prof = readForm();
    } catch (exc) {
      replace(previewBox, h("div", { class: "error-box" }, (exc as Error).message));
      return;
    }
    const my = ++seq;
    try {
      const p = await api.post<PreviewResponse>("/uds/preview", {
        payload: sampleIn.value,
        profile: prof,
        functional: functional.input.checked,
      });
      if (my === seq) replace(previewBox, renderPreview(p));
    } catch (exc) {
      if (my !== seq) return;
      const lines =
        exc instanceof ApiError ? [exc.message, ...formatErrorDetails(exc.details)] : [String(exc)];
      replace(
        previewBox,
        h(
          "ul",
          { class: "editor-errors" },
          lines.map((l) => h("li", null, l)),
        ),
      );
    }
  }, 250);
  sampleIn.addEventListener("input", schedulePreview);
  functional.input.addEventListener("change", schedulePreview);

  const el = h(
    "div",
    { class: "two-col" },
    h(
      "div",
      { class: "col" },
      card(
        h("span", null, t("isotp.profiles"), " ", button(t("common.reload"), load, { kind: "ghost" })),
        listBox,
      ),
      card(t("isotp.editor"), editorBox),
    ),
    h(
      "div",
      { class: "col" },
      card(
        t("isotp.livePreview"),
        h(
          "div",
          { class: "grid" },
          field(t("isotp.sample"), sampleIn, undefined, "field-wide"),
          functional.el,
        ),
        previewBox,
      ),
    ),
  );

  return { el, show: () => void load().catch(toastError) };
}
