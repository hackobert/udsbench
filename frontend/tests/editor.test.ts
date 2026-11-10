import { describe, expect, it } from "vitest";
import { ApiError } from "../src/api";
import {
  editorErrorLines,
  offsetToLineCol,
  parseJson,
  parseLibraryItem,
  renderEditorErrors,
  toEditorText,
} from "../src/editor";

describe("sequence/test editor helpers", () => {
  it("parses valid JSON", () => {
    const r = parseJson('{"id":"x","steps":[]}');
    expect(r.ok).toBe(true);
  });

  it("reports line/column of syntax errors", () => {
    const text = '{\n  "id": "x",\n  "steps": [,]\n}';
    const r = parseJson(text);
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.line).toBe(3);
      expect(r.column).toBeGreaterThan(1);
      expect(editorErrorLines(r)[0]).toMatch(/Zeile 3/);
    }
  });

  it("converts offsets to line/col", () => {
    expect(offsetToLineCol("ab\ncd", 4)).toEqual({ line: 2, column: 2 });
  });

  it("validates library items", () => {
    expect(parseLibraryItem("[]").ok).toBe(false);
    const r = parseLibraryItem('{"name":"no id"}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.message).toContain("id");
    expect(parseLibraryItem('{"id":"t1"}').ok).toBe(true);
    expect(parseLibraryItem("").ok).toBe(false);
  });

  it("strips API-only fields for editing", () => {
    expect(JSON.parse(toEditorText({ id: "a", package: "demo", steps: [] }))).toEqual({ id: "a", steps: [] });
  });

  it("renders API validation errors with details", () => {
    const err = new ApiError(422, "validation_error", "Ungültige Anfrage", [
      { loc: "body.steps.0", msg: "Field required" },
    ]);
    expect(editorErrorLines(err)).toEqual(["Ungültige Anfrage", "body.steps.0: Field required"]);
    const el = renderEditorErrors(err);
    expect(el?.querySelectorAll("li")).toHaveLength(2);
    expect(renderEditorErrors(null)).toBeNull();
  });
});
