import { infoIcon } from "./help";
/** Darstellung der Byte-/Frame-Vorschau aus POST /uds/preview (Rollen kommen vom Backend). */
import { h } from "./dom";
import { parseHex, byteHex } from "./hex";
import { t, type MsgKey } from "./i18n";
import type { PreviewFrame, PreviewResponse, UdsService, Validation } from "./types";

export const BYTE_ROLES = ["ae", "pci", "len", "data", "pad", "fc"] as const;
export type ByteRole = (typeof BYTE_ROLES)[number];

const ROLE_LABEL: Record<ByteRole, MsgKey> = {
  ae: "role.ae",
  pci: "role.pci",
  len: "role.len",
  data: "role.data",
  pad: "role.pad",
  fc: "role.fc",
};

/** Byte-Rolle → CSS-Klasse; unbekannte Rollen → "b-other". */
export function roleClass(role: string): string {
  return (BYTE_ROLES as readonly string[]).includes(role) ? `b-${role}` : "b-other";
}

export function roleLabel(role: string): string {
  return (BYTE_ROLES as readonly string[]).includes(role) ? t(ROLE_LABEL[role as ByteRole]) : role;
}

export function renderByte(value: string, role: string, title?: string): HTMLElement {
  return h("span", { class: ["byte", roleClass(role)], title: title ?? roleLabel(role) }, value);
}

/** Legende aller Byte-Rollen. */
export function renderLegend(roles: readonly string[] = BYTE_ROLES): HTMLElement {
  return h(
    "div",
    { class: "legend", role: "list" },
    roles.map((r) =>
      h(
        "span",
        { class: "legend-item", role: "listitem" },
        h("span", { class: ["byte", "byte-sm", roleClass(r)] }, "  "),
        roleLabel(r),
      ),
    ),
  );
}

/** Byte-für-Byte-Darstellung der UDS-Nutzlast (Index + Byte; Byte 0 = SID, Byte 1 = Subfunktion wenn vorhanden). */
export function renderPayloadBytes(payloadHex: string, service?: UdsService | null): HTMLElement {
  let bytes: number[] = [];
  try {
    bytes = parseHex(payloadHex);
  } catch {
    bytes = [];
  }
  const cells = bytes.map((b, i) => {
    let label = t("preview.byteN", { n: i });
    if (i === 0) label = "SID";
    else if (i === 1 && service?.has_subfunction) label = (b & 0x80 ? "SPRM+" : "") + "Sub";
    return h(
      "div",
      { class: "pbyte" },
      h("span", { class: ["byte", "b-data"], title: label }, byteHex(b)),
      h("span", { class: "pbyte-idx" }, label),
    );
  });
  return h(
    "div",
    { class: "payload-bytes" },
    cells.length ? cells : h("span", { class: "muted" }, t("preview.empty")),
  );
}

export function renderFrame(f: PreviewFrame, index: number): HTMLElement {
  return h(
    "div",
    { class: ["frame-row", `k-${f.kind}`] },
    h("span", { class: "frame-idx" }, `#${index + 1}`),
    h("span", { class: ["badge", `kind-${f.kind}`] }, f.kind),
    h("span", { class: "frame-id mono", title: "CAN-ID" }, f.can_id_hex + (f.extended_id ? " (29)" : "")),
    h("span", { class: "frame-dlc mono", title: "DLC" }, `[${f.dlc}]${f.fd ? " FD" : ""}`),
    h(
      "span",
      { class: "frame-bytes" },
      f.bytes.map((b) => renderByte(b.value, b.role)),
    ),
    h("span", { class: "frame-note" }, f.note),
  );
}

export function renderFrames(frames: PreviewFrame[]): HTMLElement {
  return h(
    "div",
    { class: "frames" },
    frames.length
      ? frames.map((f, i) => renderFrame(f, i))
      : h("span", { class: "muted" }, t("preview.noFrames")),
  );
}

export function renderValidation(v: Validation | null | undefined): HTMLElement | null {
  if (!v || (!v.errors.length && !v.warnings.length)) return null;
  return h(
    "ul",
    { class: "validation" },
    v.errors.map((e) => h("li", { class: "v-error" }, `✖ ${e}`)),
    v.warnings.map((w) => h("li", { class: "v-warning" }, `⚠ ${w}`)),
  );
}

/** Komplette Vorschau (Nutzlast + Frames + Legende + Validierung). */
export function renderPreview(p: PreviewResponse, service?: UdsService | null): HTMLElement {
  return h(
    "div",
    { class: "preview" },
    h(
      "div",
      { class: "preview-head" },
      h("strong", null, t("preview.payload")),
      infoIcon("uds.preview_payload"),
      h("span", { class: "muted" }, ` ${t("preview.length", { n: p.length })}`),
      p.description ? h("span", { class: "preview-desc" }, ` – ${p.description}`) : null,
    ),
    renderPayloadBytes(p.payload, service),
    p.validation.errors.length || p.validation.warnings.length
      ? h(
          "div",
          { class: "preview-head" },
          h("strong", null, t("preview.validation")),
          infoIcon("uds.validate"),
        )
      : null,
    renderValidation(p.validation),
    h(
      "div",
      { class: "preview-head" },
      h("strong", null, t("preview.frames", { n: p.frames.length })),
      infoIcon("uds.preview_frames"),
      p.flow_control_expected ? h("span", { class: "muted" }, ` – ${t("preview.fcExpected")}`) : null,
    ),
    renderFrames(p.frames),
    renderLegend(),
  );
}
