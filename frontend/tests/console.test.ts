import { describe, expect, it } from "vitest";
import { normalizePath, parseCommand, toCurl } from "../src/console-parser";

describe("console parser", () => {
  it("parses raw API operations", () => {
    expect(parseCommand("GET /info")).toEqual({ kind: "api", method: "GET", path: "/info" });
    expect(parseCommand("get info")).toEqual({ kind: "api", method: "GET", path: "/info" });
    expect(parseCommand('POST /uds/request {"ecu":"ecu_a","payload":"22 F1 00"}')).toEqual({
      kind: "api",
      method: "POST",
      path: "/uds/request",
      body: { ecu: "ecu_a", payload: "22 F1 00" },
    });
    expect(parseCommand("POST /recordings/stop")).toEqual({
      kind: "api",
      method: "POST",
      path: "/recordings/stop",
      body: {},
    });
    expect(parseCommand("DELETE /trace")).toEqual({ kind: "api", method: "DELETE", path: "/trace" });
    expect(
      parseCommand("GET /api/v1/ecus").kind === "api" &&
        (parseCommand("GET /api/v1/ecus") as { path: string }).path,
    ).toBe("/ecus");
    expect(parseCommand("POST /x {bad").kind).toBe("error");
    expect(parseCommand("GET").kind).toBe("error");
  });

  it("parses short forms", () => {
    expect(parseCommand("uds ecu_a 22 f1 00")).toEqual({
      kind: "api",
      method: "POST",
      path: "/uds/request",
      body: { ecu: "ecu_a", payload: "22 F1 00" },
    });
    expect(parseCommand("uds ecu_a 3E 80 --functional")).toMatchObject({
      body: { functional: true, payload: "3E 80" },
    });
    expect(parseCommand("send read_identifier")).toEqual({
      kind: "api",
      method: "POST",
      path: "/messages/read_identifier/send",
      body: {},
    });
    expect(parseCommand("run suite smoke")).toMatchObject({ path: "/testsuites/smoke/run" });
    expect(parseCommand("run test t1")).toMatchObject({ path: "/tests/t1/run" });
    expect(parseCommand("run sequence s1")).toMatchObject({ path: "/sequences/s1/run" });
    expect(parseCommand("run foo x").kind).toBe("error");
    expect(parseCommand("uds ecu_a").kind).toBe("error");
    expect(parseCommand("help")).toEqual({ kind: "help" });
    expect(parseCommand("clear")).toEqual({ kind: "clear" });
    expect(parseCommand("bogus").kind).toBe("error");
  });

  it("normalizes paths", () => {
    expect(normalizePath("info")).toBe("/info");
    expect(normalizePath("/api/health")).toBe("/api/health");
  });

  it("generates curl commands", () => {
    expect(toCurl({ method: "GET", path: "/info" }, "http://127.0.0.1:8765", false)).toBe(
      "curl -s 'http://127.0.0.1:8765/api/v1/info'",
    );
    expect(
      toCurl({ method: "POST", path: "/uds/request", body: { payload: "it's" } }, "http://h", true),
    ).toBe(
      `curl -s -X POST 'http://h/api/v1/uds/request' -H "Authorization: Bearer $UDSBENCH_TOKEN" -H 'Content-Type: application/json' -d '{"payload":"it'\\''s"}'`,
    );
    expect(toCurl({ method: "GET", path: "/api/health" }, "http://h/", false)).toBe(
      "curl -s 'http://h/api/health'",
    );
  });
});
