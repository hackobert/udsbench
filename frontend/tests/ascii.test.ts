import { describe, expect, it } from "vitest";
import { hexAscii, stepView, udsResultView } from "../src/components/ui";
import { stepLine } from "../src/components/run-log";
import { asciiOf } from "../src/hex";
import { collectResponses } from "../src/views/console";
import type { StepRecord, UdsResult } from "../src/types";

describe("ASCII-Übersetzung von UDS-Antworten", () => {
  it("übersetzt druckbare Bytes und markiert den Rest", () => {
    expect(asciiOf("62 F1 90 57 30 4C 2E 00")).toBe("b··W0L.·");
    expect(asciiOf("zz")).toBe("");
  });

  it("zeigt Hex und ASCII als Block und inline", () => {
    const block = hexAscii("62 F1 90 41 42");
    expect(block.querySelector("code.mono")?.textContent).toBe("62 F1 90 41 42");
    expect(block.querySelector("code.ascii")?.textContent).toBe("b··AB");
    const inline = hexAscii("41 42", { inline: true });
    expect(inline.textContent).toBe('41 42 "AB"');
    expect(hexAscii(null).textContent).toBe("–");
    expect(hexAscii("Timeout").querySelector("code.ascii")).toBeNull();
  });

  it("erscheint in Antwort-, Schritt- und Protokollansicht", () => {
    const r = {
      ecu: "e",
      functional: false,
      request: "22 F1 90",
      response: "62 F1 90 57 30 4C",
      positive: true,
      negative: false,
      nrc: null,
      nrc_name: null,
      pending_count: 0,
      suppress_positive: false,
      elapsed_ms: 1,
      error: null,
      decoded: {},
      responses: [],
      warnings: [],
    } as unknown as UdsResult;
    expect(udsResultView(r).querySelector("code.ascii")?.textContent).toBe("b··W0L");
    const s = {
      status: "passed",
      action: "uds",
      name: "x",
      depth: 0,
      request: "22",
      response: "62 41",
    } as StepRecord;
    expect(stepView(s).querySelector("code.ascii")?.textContent).toBe("bA");
    expect(stepLine(s).querySelector("code.ascii")?.textContent).toBe(' "bA"');
  });

  it("findet Antworten in Konsolen-Ergebnissen", () => {
    expect(
      collectResponses({ response: "62 01", step: { response: "71 01" }, x: [{ response: "nicht" }] }),
    ).toEqual(["62 01", "71 01"]);
  });
});
