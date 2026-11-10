import { describe, expect, it } from "vitest";
import {
  BYTE_ROLES,
  renderFrames,
  renderLegend,
  renderPayloadBytes,
  renderPreview,
  roleClass,
} from "../src/preview";
import type { PreviewResponse, UdsService } from "../src/types";

const frames = [
  {
    can_id: 0x6f0,
    can_id_hex: "6F0",
    extended_id: false,
    fd: false,
    dlc: 8,
    kind: "FF",
    note: "FF_DL=9 (Gesamtlänge der Nachricht)",
    bytes: [
      { value: "2B", role: "ae" },
      { value: "10", role: "pci" },
      { value: "09", role: "len" },
      { value: "2E", role: "data" },
      { value: "02", role: "data" },
      { value: "00", role: "data" },
      { value: "01", role: "data" },
      { value: "02", role: "data" },
    ],
  },
  {
    can_id: 0x6f0,
    can_id_hex: "6F0",
    extended_id: false,
    fd: false,
    dlc: 8,
    kind: "CF",
    note: "SN=1",
    bytes: [
      { value: "2B", role: "ae" },
      { value: "21", role: "pci" },
      { value: "03", role: "data" },
      { value: "FF", role: "pad" },
    ],
  },
];

describe("byte/frame preview", () => {
  it("maps roles to css classes", () => {
    expect(roleClass("ae")).toBe("b-ae");
    expect(roleClass("pci")).toBe("b-pci");
    expect(roleClass("len")).toBe("b-len");
    expect(roleClass("data")).toBe("b-data");
    expect(roleClass("pad")).toBe("b-pad");
    expect(roleClass("fc")).toBe("b-fc");
    expect(roleClass("weird")).toBe("b-other");
  });

  it("renders frames with colored bytes and notes", () => {
    const el = renderFrames(frames);
    const rows = el.querySelectorAll(".frame-row");
    expect(rows).toHaveLength(2);
    const first = rows[0] as HTMLElement;
    expect(first.classList.contains("k-FF")).toBe(true);
    const bytes = [...first.querySelectorAll(".byte")].map((b) => [b.textContent, b.className]);
    expect(bytes[0]).toEqual(["2B", "byte b-ae"]);
    expect(bytes[1]).toEqual(["10", "byte b-pci"]);
    expect(bytes[2]).toEqual(["09", "byte b-len"]);
    expect(bytes[3]?.[1]).toBe("byte b-data");
    expect(first.querySelector(".frame-note")?.textContent).toContain("FF_DL=9");
    expect(rows[1]?.querySelector(".b-pad")?.textContent).toBe("FF");
  });

  it("renders a legend with all roles", () => {
    const el = renderLegend();
    const items = el.querySelectorAll(".legend-item");
    expect(items).toHaveLength(BYTE_ROLES.length);
    expect(el.textContent).toContain("Adressbyte");
    expect(el.textContent).toContain("Padding");
    expect(el.querySelector(".b-len")).not.toBeNull();
  });

  it("labels payload bytes (SID / Sub)", () => {
    const svc = { has_subfunction: true } as UdsService;
    const el = renderPayloadBytes("10 83", svc);
    const labels = [...el.querySelectorAll(".pbyte-idx")].map((x) => x.textContent);
    expect(labels).toEqual(["SID", "SPRM+Sub"]);
    expect(renderPayloadBytes("zz").textContent).toContain("leer");
  });

  it("renders a full preview incl. validation", () => {
    const p: PreviewResponse = {
      payload: "2E 02 00 01 02 03",
      length: 6,
      validation: { ok: false, errors: ["zu kurz"], warnings: ["Hinweis"] },
      description: "WriteDataByIdentifier",
      profile: {},
      frames,
      flow_control_expected: true,
    };
    const el = renderPreview(p);
    expect(el.querySelector(".v-error")?.textContent).toContain("zu kurz");
    expect(el.querySelector(".v-warning")?.textContent).toContain("Hinweis");
    expect(el.textContent).toContain("Flow-Control");
    expect(el.querySelectorAll(".frame-row")).toHaveLength(2);
  });
});
