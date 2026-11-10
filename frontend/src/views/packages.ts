import { createAiConfigCard } from "../components/ai-config";
import { infoIcon } from "../help";
import { ApiError, formatErrorDetails } from "../api";
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
  confirmDialog,
} from "../components/ui";
import { h, readFileText, replace } from "../dom";
import { t } from "../i18n";
import type { PackageSummary, PackagesResponse } from "../types";
import type { AppCtx, View } from "../view";

interface RuntimeConfig {
  timing: {
    p2_ms: number;
    p2_star_ms: number;
    margin_ms: number;
    max_response_pending: number;
    adopt_server_timing: boolean;
    await_nrc_on_suppress: boolean;
    validation: "strict" | "warn" | "off";
  };
  tester_present: {
    enabled: boolean;
    interval_ms: number;
    suppress_response: boolean;
    addressing: "physical" | "functional";
    s3_server_ms: number;
  };
  logging: { level: string; mask_secrets: boolean };
}

export function createPackagesView(ctx: AppCtx): View {
  const { api, store } = ctx;
  let data: PackagesResponse = { packages: [], active: [], invalid: [] };
  const listBox = h("div");
  const invalidBox = h("div");
  const uploadResult = h("div");
  const fileIn = h("input", { type: "file", accept: ".yaml,.yml,.json" });
  const activate = checkbox(t("pkg.activateAfter"), true);
  const overwrite = checkbox(t("pkg.overwrite"), false);
  const cfgBox = h("div");

  const load = async () => {
    data = await api.get<PackagesResponse>("/packages");
    render();
  };

  const render = () => {
    replace(
      listBox,
      table<PackageSummary>(
        [
          {
            key: "act",
            label: t("pkg.active"),
            render: (p) =>
              checkbox("", p.active, async (v) => {
                try {
                  await api.post(`/packages/${encodeURIComponent(p.id)}/${v ? "activate" : "deactivate"}`);
                  toast(t(v ? "pkg.activated" : "pkg.deactivated", { id: p.id }), "success");
                } catch (exc) {
                  toastError(exc);
                }
                await Promise.all([load(), store.refreshAll()]);
              }).el,
          },
          {
            key: "id",
            label: "ID",
            render: (p) =>
              h("div", null, h("strong", null, p.id), p.builtin ? badge(t("pkg.builtin")) : null),
          },
          {
            key: "name",
            label: t("common.name"),
            render: (p) => h("div", null, p.name, h("div", { class: "muted small" }, p.description)),
          },
          { key: "ver", label: t("pkg.version"), render: (p) => `${p.version} (${p.hash})` },
          {
            key: "counts",
            label: t("pkg.counts"),
            render: (p) =>
              h(
                "span",
                { class: "bits" },
                Object.entries(p.counts)
                  .filter(([, n]) => n > 0)
                  .map(([k, n]) => badge(`${k}: ${n}`)),
              ),
          },
          {
            key: "src",
            label: t("pkg.source"),
            render: (p) => h("code", { class: "small" }, p.source ?? "–"),
          },
          {
            key: "x",
            label: "",
            render: (p) =>
              h(
                "span",
                { class: "inline" },
                button(
                  "YAML",
                  () => api.download("/config/export", { package: p.id, format: "yaml" }, `${p.id}.yaml`),
                  { kind: "ghost" },
                ),
                button(
                  "JSON",
                  () => api.download("/config/export", { package: p.id, format: "json" }, `${p.id}.json`),
                  { kind: "ghost" },
                ),
                !p.builtin
                  ? button(
                      t("common.delete"),
                      async () => {
                        if (!(await confirmDialog(t("pkg.deleteConfirm", { id: p.id })))) return;
                        await api.del(`/packages/${encodeURIComponent(p.id)}`);
                        await Promise.all([load(), store.refreshAll()]);
                      },
                      { kind: "danger" },
                    )
                  : null,
              ),
          },
        ],
        data.packages,
      ),
    );
    replace(
      invalidBox,
      data.invalid.length
        ? h(
            "ul",
            { class: "editor-errors" },
            data.invalid.map((i) =>
              h(
                "li",
                null,
                h("code", null, String(i.path ?? i.file ?? "?")),
                ": ",
                String(i.error ?? JSON.stringify(i)),
              ),
            ),
          )
        : h("div", { class: "muted" }, t("pkg.noInvalid")),
    );
  };

  const upload = async () => {
    const file = fileIn.files?.[0];
    if (!file) {
      toast(t("rec.noFile"), "warning");
      return;
    }
    const content = await readFileText(file);
    try {
      const fmt = /\.json$/i.test(file.name) ? "json" : "yaml";
      const r = await api.post<{ package: PackageSummary }>("/packages", {
        content,
        format: fmt,
        activate: activate.input.checked,
        overwrite: overwrite.input.checked,
      });
      replace(
        uploadResult,
        h(
          "div",
          { class: "result-head" },
          badge(t("pkg.uploaded"), "ok"),
          ` ${r.package.id} ${r.package.version}`,
        ),
      );
      await Promise.all([load(), store.refreshAll()]);
    } catch (exc) {
      const lines =
        exc instanceof ApiError ? [exc.message, ...formatErrorDetails(exc.details)] : [String(exc)];
      replace(
        uploadResult,
        h(
          "ul",
          { class: "editor-errors" },
          lines.map((l) => h("li", null, l)),
        ),
      );
    }
  };

  const rescan = async () => {
    await api.post("/packages/rescan");
    toast(t("pkg.rescanned"), "success");
    await Promise.all([load(), store.refreshAll()]);
  };

  // --- Laufzeit-Konfiguration --------------------------------------------------------------------
  const loadConfig = async () => {
    const cfg = await api.get<RuntimeConfig>("/config");
    const tm = cfg.timing;
    const tp = cfg.tester_present;
    const p2 = numberInput(tm.p2_ms, { min: "0" });
    const p2s = numberInput(tm.p2_star_ms, { min: "0" });
    const margin = numberInput(tm.margin_ms, { min: "0" });
    const maxPending = numberInput(tm.max_response_pending, { min: "0" });
    const adopt = checkbox(t("cfg.adopt"), tm.adopt_server_timing);
    const awaitNrc = checkbox(t("cfg.awaitNrc"), tm.await_nrc_on_suppress);
    const validation = select(
      ["strict", "warn", "off"].map((v) => ({ value: v, label: v })),
      tm.validation,
    );
    const tpOn = checkbox(t("cfg.tpEnabled"), tp.enabled);
    const tpInt = numberInput(tp.interval_ms, { min: "100" });
    const tpSup = checkbox(t("cfg.tpSuppress"), tp.suppress_response);
    const tpAddr = select(
      [
        { value: "physical", label: t("uds.physical") },
        { value: "functional", label: t("uds.functional") },
      ],
      tp.addressing,
    );
    const s3 = numberInput(tp.s3_server_ms, { min: "0" });
    const level = select(
      ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"].map((v) => ({ value: v, label: v })),
      cfg.logging.level,
    );
    const mask = checkbox(
      t("cfg.mask"),
      cfg.logging.mask_secrets,
      undefined,
      undefined,
      "config.mask_secrets",
    );
    const err = h("div");
    const saveCfg = async () => {
      try {
        await api.put("/config", {
          timing: {
            p2_ms: Number(p2.value),
            p2_star_ms: Number(p2s.value),
            margin_ms: Number(margin.value),
            max_response_pending: Number(maxPending.value),
            adopt_server_timing: adopt.input.checked,
            await_nrc_on_suppress: awaitNrc.input.checked,
            validation: validation.value,
          },
          tester_present: {
            enabled: tpOn.input.checked,
            interval_ms: Number(tpInt.value),
            suppress_response: tpSup.input.checked,
            addressing: tpAddr.value,
            s3_server_ms: Number(s3.value),
          },
          log_level: level.value,
          mask_secrets: mask.input.checked,
        });
        replace(err);
        toast(t("cfg.saved"), "success");
        await store.refreshEcus();
      } catch (exc) {
        const lines =
          exc instanceof ApiError ? [exc.message, ...formatErrorDetails(exc.details)] : [String(exc)];
        replace(
          err,
          h(
            "ul",
            { class: "editor-errors" },
            lines.map((l) => h("li", null, l)),
          ),
        );
      }
    };
    replace(
      cfgBox,
      h(
        "fieldset",
        null,
        h("legend", null, t("cfg.timing"), infoIcon("config.timing")),
        h(
          "div",
          { class: "grid" },
          field("P2 [ms]", p2),
          field("P2* [ms]", p2s),
          field(t("cfg.margin"), margin),
          field(t("cfg.maxPending"), maxPending),
          field(t("cfg.validation"), validation),
          adopt.el,
          awaitNrc.el,
        ),
      ),
      h(
        "fieldset",
        null,
        h("legend", null, "TesterPresent"),
        h(
          "div",
          { class: "grid" },
          tpOn.el,
          field(t("cfg.interval"), tpInt),
          tpSup.el,
          field(t("uds.addressing"), tpAddr),
          field("S3 [ms]", s3),
        ),
      ),
      h(
        "fieldset",
        null,
        h("legend", null, t("cfg.logging")),
        h("div", { class: "grid" }, field("Log-Level", level), mask.el),
      ),
      err,
      row(
        button(t("common.save"), saveCfg, { kind: "primary" }),
        button(t("common.reload"), loadConfig, { kind: "ghost" }),
      ),
    );
  };

  const el = h(
    "div",
    { class: "view-grid" },
    createAiConfigCard(ctx),
    card(
      h(
        "span",
        null,
        t("pkg.title"),
        infoIcon("packages.active"),
        " ",
        button(t("pkg.rescan"), rescan, { kind: "ghost" }),
      ),
      listBox,
    ),
    h(
      "div",
      { class: "two-col" },
      card(
        h("span", null, t("pkg.upload"), infoIcon("packages.upload")),
        row(fileIn),
        row(activate.el, overwrite.el),
        row(button(t("pkg.uploadBtn"), upload, { kind: "primary" })),
        uploadResult,
      ),
      card(t("pkg.invalid"), invalidBox),
    ),
    card(t("cfg.title"), cfgBox),
  );

  const off = store.on("packages", () => void load().catch(() => undefined));
  return {
    el,
    show: () => {
      void load().catch(toastError);
      void loadConfig().catch(toastError);
    },
    destroy: off,
  };
}
