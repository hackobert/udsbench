import { describe, expect, it } from "vitest";
import {
  bytesToAscii,
  formatHex,
  HexError,
  intToHexBytes,
  isValidHex,
  normalizeHex,
  parseHex,
  parseIntLoose,
  prettyHex,
  stminText,
  toHexId,
} from "../src/hex";

describe("hex utilities", () => {
  it("parses various notations", () => {
    expect(parseHex("22 F1 00")).toEqual([0x22, 0xf1, 0x00]);
    expect(parseHex("22f100")).toEqual([0x22, 0xf1, 0x00]);
    expect(parseHex("0x22,0xF1, 0x00")).toEqual([0x22, 0xf1, 0x00]);
    expect(parseHex("22:F1-00")).toEqual([0x22, 0xf1, 0x00]);
    expect(parseHex("")).toEqual([]);
  });

  it("rejects invalid input", () => {
    expect(() => parseHex("2")).toThrow(HexError);
    expect(() => parseHex("ZZ")).toThrow(/Ungültiges Hex-Zeichen 'Z'/);
    expect(isValidHex("12 3")).toBe(false);
    expect(isValidHex("", false)).toBe(false);
    expect(isValidHex("")).toBe(true);
  });

  it("formats bytes", () => {
    expect(formatHex([0x2, 0xab, 0xff])).toBe("02 AB FF");
    expect(formatHex([1, 2], "")).toBe("0102");
    expect(prettyHex("22f100")).toBe("22 F1 00");
    expect(prettyHex("xyz")).toBe("xyz");
    expect(normalizeHex("0xAb cD")).toBe("ABCD");
  });

  it("converts integers", () => {
    expect(intToHexBytes(0xf100, 2)).toBe("F1 00");
    expect(intToHexBytes(1, 3)).toBe("00 00 01");
    expect(() => intToHexBytes(0x10000, 2)).toThrow(HexError);
    expect(parseIntLoose("0x7E0")).toBe(0x7e0);
    expect(parseIntLoose("7E0h")).toBe(0x7e0);
    expect(parseIntLoose("0b101")).toBe(5);
    expect(parseIntLoose("700")).toBe(700);
    expect(parseIntLoose("700", true)).toBe(0x700);
    expect(() => parseIntLoose("xyz")).toThrow();
    expect(toHexId(0x700)).toBe("0x700");
    expect(toHexId(0x18da00f1, 8)).toBe("0x18DA00F1");
  });

  it("renders ascii and stmin", () => {
    expect(bytesToAscii("44 45 4D 4F 00")).toBe("DEMO.");
    expect(stminText(0x0a)).toBe("10 ms");
    expect(stminText(0xf5)).toBe("500 µs");
    expect(stminText(0x80)).toMatch(/reserviert/);
  });
});
