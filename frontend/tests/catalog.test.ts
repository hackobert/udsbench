import { describe, expect, it } from "vitest";
import {
  buildPayload,
  didOptions,
  encodeParam,
  fillSelect,
  paramsFor,
  statusBitsFromMask,
  subfunctionOptions,
} from "../src/catalog";
import type { DidDef, UdsService } from "../src/types";

const did = (id: number, name: string, access: string, io = false, unit = ""): DidDef =>
  ({
    id,
    id_hex: `0x${id.toString(16).toUpperCase().padStart(4, "0")}`,
    name,
    access,
    io_control: io,
    unit,
    type: "uint",
    length: 1,
  }) as DidDef;

const dids = [
  did(0x100, "supply_voltage", "read", false, "V"),
  did(0x200, "user_setting", "readwrite"),
  did(0x300, "out", "read", true),
];

const rdtc: UdsService = {
  sid: 0x19,
  sid_hex: "0x19",
  name: "ReadDTCInformation",
  description: "",
  has_subfunction: true,
  sprm_allowed: false,
  subfunctions: [
    { value: 1, hex: "0x01", name: "reportNumberOfDTCByStatusMask" },
    { value: 2, hex: "0x02", name: "reportDTCByStatusMask" },
    { value: 10, hex: "0x0A", name: "reportSupportedDTC" },
  ],
  params: [],
  sub_params: {
    "0x02": [{ name: "DTCStatusMask", kind: "mask", description: "", optional: false, default: "FF" }],
  },
};
const rdbi: UdsService = {
  sid: 0x22,
  sid_hex: "0x22",
  name: "ReadDataByIdentifier",
  description: "",
  has_subfunction: false,
  sprm_allowed: false,
  subfunctions: [],
  params: [{ name: "dataIdentifier", kind: "did", description: "", optional: false, default: null }],
  sub_params: {},
};
const dsc: UdsService = {
  ...rdtc,
  sid: 0x10,
  sid_hex: "0x10",
  name: "DiagnosticSessionControl",
  sprm_allowed: true,
  sub_params: {},
  subfunctions: [{ value: 3, hex: "0x03", name: "extendedDiagnosticSession" }],
};

describe("catalog dropdowns", () => {
  it("DID catalog → options (with filters)", () => {
    expect(didOptions(dids)).toEqual([
      { value: "0x0100", label: "0100 supply_voltage [V]" },
      { value: "0x0200", label: "0200 user_setting" },
      { value: "0x0300", label: "0300 out" },
    ]);
    expect(didOptions(dids, { access: "write" }).map((o) => o.value)).toEqual(["0x0200"]);
    expect(didOptions(dids, { ioControl: true }).map((o) => o.value)).toEqual(["0x0300"]);
  });

  it("services → subfunction list", () => {
    expect(subfunctionOptions(rdtc)).toEqual([
      { value: "1", label: "01 reportNumberOfDTCByStatusMask" },
      { value: "2", label: "02 reportDTCByStatusMask" },
      { value: "10", label: "0A reportSupportedDTC" },
    ]);
    expect(subfunctionOptions(rdbi)).toEqual([]);
    expect(subfunctionOptions(null)).toEqual([]);
  });

  it("fills a select element", () => {
    const sel = fillSelect(document.createElement("select"), didOptions(dids), "0x0200", "—");
    expect(sel.options).toHaveLength(4);
    expect(sel.value).toBe("0x0200");
  });

  it("resolves sub-function specific params", () => {
    expect(paramsFor(rdtc, 2).map((p) => p.name)).toEqual(["DTCStatusMask"]);
    expect(paramsFor(rdtc, 10)).toEqual([]);
    expect(paramsFor(rdbi, null).map((p) => p.kind)).toEqual(["did"]);
  });

  it("builds payloads from service, subfunction, SPRM and params", () => {
    expect(buildPayload({ service: rdbi, params: { dataIdentifier: "0xF100" } })).toBe("22 F1 00");
    expect(buildPayload({ service: rdtc, sub: 2, params: {} })).toBe("19 02 FF");
    expect(buildPayload({ service: rdtc, sub: 2, params: { DTCStatusMask: "09" } })).toBe("19 02 09");
    expect(buildPayload({ service: dsc, sub: 3, sprm: true, params: {} })).toBe("10 83");
    expect(encodeParam("u24", "FFFFFF")).toBe("FF FF FF");
    expect(encodeParam("did", "F1 90")).toBe("F1 90");
    expect(encodeParam("u16", "256d")).toBe("01 00");
    expect(encodeParam("hex", "aa bb cc")).toBe("AA BB CC");
    expect(() => encodeParam("did", "F1 90 00")).toThrow();
  });

  it("decodes status masks to bit names", () => {
    expect(statusBitsFromMask(0x09, ["testFailed", "a", "b", "confirmedDTC"])).toEqual([
      "testFailed",
      "confirmedDTC",
    ]);
  });
});
