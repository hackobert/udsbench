import { describe, expect, it } from "vitest";
import {
  decodeDbcBytes,
  filterLive,
  formatCanId,
  formatSignal,
  parseSignalInput,
  signalActive,
  signalLayout,
  type DbcSignal,
  type LiveMessage,
} from "../src/dbc-model";

const sig = (o: Partial<DbcSignal> = {}): DbcSignal => ({
  name: "Speed",
  start: 0,
  length: 16,
  byte_order: "little_endian",
  signed: false,
  float: false,
  scale: 0.25,
  offset: 0,
  minimum: 0,
  maximum: 100,
  unit: "km/h",
  choices: null,
  comment: null,
  multiplexer: false,
  multiplexer_ids: null,
  ...o,
});

describe("dbc model", () => {
  it("decodes UTF-8 and falls back to Windows-1252", () => {
    expect(decodeDbcBytes(new TextEncoder().encode('CM_ "Größe";'))).toBe('CM_ "Größe";');
    expect(decodeDbcBytes(new Uint8Array([0x47, 0x72, 0xf6, 0xdf, 0x65]))).toBe("Größe");
    expect(decodeDbcBytes(new Uint8Array([0xef, 0xbb, 0xbf, 0x41]))).toBe("A");
  });

  it("formats values, ids and layout", () => {
    expect(formatSignal(0.1 + 0.2, "V")).toBe("0.3 V");
    expect(formatSignal("active")).toBe("active");
    expect(formatSignal(null)).toBe("–");
    expect(formatCanId(0x100, false)).toBe("0x100");
    expect(formatCanId(0x18fef1fe, true)).toBe("0x18FEF1FE");
    expect(signalLayout(sig())).toBe("Start 0, 16 Bit, Intel, unsigned");
    expect(signalLayout(sig({ byte_order: "big_endian", signed: true }))).toContain("Motorola, signed");
  });

  it("parses inputs and multiplexing", () => {
    expect(parseSignalInput("", sig())).toBeNull();
    expect(parseSignalInput("12,5", sig())).toBe(12.5);
    expect(parseSignalInput("on", sig({ choices: { "1": "on" } }))).toBe("on");
    expect(() => parseSignalInput("abc", sig())).toThrow(/keine Zahl/);
    expect(signalActive(sig(), null)).toBe(true);
    expect(signalActive(sig({ multiplexer_ids: [1, 2] }), 2)).toBe(true);
    expect(signalActive(sig({ multiplexer_ids: [1] }), 3)).toBe(false);
    expect(signalActive(sig({ multiplexer_ids: [1] }), null)).toBe(false);
  });

  it("filters live messages", () => {
    const m = (message: string, id_hex: string, signals: string[]): LiveMessage =>
      ({
        message,
        id_hex,
        signals: Object.fromEntries(signals.map((s) => [s, 1])),
      }) as unknown as LiveMessage;
    const items = [m("EngineData", "100", ["EngineSpeed"]), m("Status", "200", ["Mux"])];
    expect(filterLive(items, "").length).toBe(2);
    expect(filterLive(items, "engine").map((x) => x.message)).toEqual(["EngineData"]);
    expect(filterLive(items, "0x200").map((x) => x.message)).toEqual(["Status"]);
    expect(filterLive(items, "mux").map((x) => x.message)).toEqual(["Status"]);
  });
});
