import { describe, expect, it } from "vitest";
import {
  canCheck,
  canImport,
  checkView,
  currentStep,
  defaultPromptForm,
  explainMsg,
  formatLoc,
  initialFlow,
  promptQuery,
  withAnswer,
  withCheck,
  withImport,
  withPrompt,
} from "../src/ai-flow";

const ok = {
  ok: true,
  package: {
    id: "ecu_a",
    name: "ECU A",
    version: "0.1.0",
    counts: { ecus: 1, dids: 12, dtcs: 0, tests: 4, isotp_profiles: 1 },
  },
  todos: ["TODO: Seed-Key-Algorithmus fehlt"],
};
const fail = {
  ok: false,
  message: "Paket ist ungültig",
  errors: [{ loc: "ecus.0.isotp", msg: "Extra inputs are not permitted", type: "extra_forbidden" }],
  todos: [],
  fix_prompt: "# Korrektur …",
};

describe("KI-Konfiguration: Ablauf", () => {
  it("builds the prompt query (default: all sections except simulation)", () => {
    const f = defaultPromptForm();
    expect(f.sections).not.toContain("simulation");
    expect(promptQuery({ ...f, packageId: " ecu_a ", notes: "" })).toEqual({
      sections: "isotp,ecus,security,dids,dtcs,routines,messages,sequences,tests",
      simulation: "false",
      tests: "true",
      json_schema: "false",
      package_id: "ecu_a",
    });
    const q = promptQuery({ ...f, simulation: true, tests: false, jsonSchema: true, notes: "nur ecu_a" });
    expect(q["sections"]).toBe("isotp,ecus,security,dids,dtcs,routines,messages,sequences,simulation");
    expect(q["json_schema"]).toBe("true");
    expect(q["notes"]).toBe("nur ecu_a");
  });

  it("allows import only after a successful check of exactly this answer", () => {
    let s = initialFlow();
    expect(currentStep(s)).toBe(1);
    expect(canCheck(s)).toBe(false);
    s = withPrompt(s, "# Auftrag");
    expect(currentStep(s)).toBe(2);
    s = withAnswer(s, "```yaml\n…\n```");
    expect(canCheck(s)).toBe(true);
    expect(canImport(s)).toBe(false);
    s = withCheck(s, s.answer, fail);
    expect(canImport(s)).toBe(false);
    s = withCheck(s, s.answer, ok);
    expect(canImport(s)).toBe(true);
    expect(currentStep(s)).toBe(3);
    // Antwort geändert → Prüfung verfällt
    const edited = withAnswer(s, s.answer + " ");
    expect(edited.check).toBeNull();
    expect(canImport(edited)).toBe(false);
    // unveränderte Antwort behält die Prüfung
    expect(canImport(withAnswer(s, s.answer))).toBe(true);
    // Import erfolgreich → fertig, kein zweiter Import
    const done = withImport(s, { ...ok, imported: true });
    expect(currentStep(done)).toBe(4);
    expect(canImport(done)).toBe(false);
    // Import abgelehnt (z. B. Paket existiert) → Fehler als Prüfergebnis
    const rejected = withImport(s, { ...fail, message: "existiert bereits" });
    expect(rejected.check?.ok).toBe(false);
    expect(canImport(rejected)).toBe(false);
  });

  it("prepares results for display (tiles, todos, readable errors, fix prompt)", () => {
    const v = checkView(ok);
    expect(v.tone).toBe("ok");
    expect(v.tiles.map((x) => x.key)).toEqual(["ecus", "isotp_profiles", "dids", "dtcs", "tests"]);
    expect(v.todos).toHaveLength(1);
    expect(v.fixPrompt).toBeNull();
    const e = checkView(fail);
    expect(e.tone).toBe("fail");
    expect(e.errors).toEqual([
      {
        path: "ecus › Eintrag 1 › isotp",
        message: "Feld ist im Schema nicht vorgesehen (Tippfehler oder unbekanntes Feld).",
        raw: "Extra inputs are not permitted",
      },
    ]);
    expect(e.fixPrompt).toBe("# Korrektur …");
    expect(checkView(null).tone).toBe("none");
    // Kollisionen beim Import kommen als reine Texte
    const col = checkView({
      ok: false,
      message: "Namenskollision",
      errors: ["ecu 'ecu_a' in 'demo' und 'x'"],
    });
    expect(col.errors[0]).toEqual({
      path: "Paket",
      message: "ecu 'ecu_a' in 'demo' und 'x'",
      raw: "ecu 'ecu_a' in 'demo' und 'x'",
    });
  });

  it("formats locations and messages", () => {
    expect(formatLoc(undefined)).toBe("Paket");
    expect(formatLoc("dids.3.enum")).toBe("dids › Eintrag 4 › enum");
    expect(explainMsg("Field required")).toBe("Pflichtfeld fehlt.");
    expect(explainMsg("custom")).toBe("custom");
  });
});
