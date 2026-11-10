/** Karte „Konfiguration aus Spezifikation (KI)“: Prompt erstellen → Antwort prüfen → importieren. */
import {
  AI_SECTIONS,
  canCheck,
  canImport,
  checkView,
  currentStep,
  defaultPromptForm,
  initialFlow,
  promptQuery,
  withAnswer,
  withCheck,
  withImport,
  withPrompt,
  type AiCheckResult,
  type AiFlowState,
  type AiPromptForm,
  type AiSection,
} from "../ai-flow";
import { h, readFileText, replace, saveText } from "../dom";
import { infoIcon, openHelpTopic } from "../help";
import { t, type MsgKey } from "../i18n";
import type { AppCtx } from "../view";
import { toast, toastError } from "./toast";
import { button, checkbox, field, textInput } from "./ui";

/** Text in die Zwischenablage; Fallback: Textfeld markieren und Hinweis zeigen. */
export async function copyText(text: string, fallback?: HTMLTextAreaElement | null): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      toast(t("ai.copied"), "success");
      return true;
    }
  } catch {
    /* Fallback unten */
  }
  if (fallback) {
    fallback.value = text;
    fallback.closest("details")?.setAttribute("open", "");
    fallback.focus();
    fallback.select();
  }
  toast(t("ai.copyFallback"), "warning", [], 8000);
  return false;
}

export function createAiConfigCard(ctx: AppCtx): HTMLElement {
  const { api, store } = ctx;
  let state: AiFlowState = initialFlow();
  const form: AiPromptForm = defaultPromptForm();

  // --- Schritt 1: Prompt ---------------------------------------------------------------------------
  const idIn = textInput("", { placeholder: "mein_steuergeraet", class: "mono" });
  const nameIn = textInput("", { placeholder: t("ai.namePlaceholder") });
  const sectionBoxes = AI_SECTIONS.filter((s) => s !== "simulation" && s !== "tests").map((s) => ({
    s,
    c: checkbox(t(`ai.sec.${s}` as MsgKey), form.sections.includes(s)),
  }));
  const simBox = checkbox(t("ai.simulation"), form.simulation);
  const testsBox = checkbox(t("ai.tests"), form.tests);
  const notesIn = h("textarea", { rows: "2", placeholder: t("ai.notesPlaceholder") });
  const schemaBox = checkbox(t("ai.jsonSchema"), form.jsonSchema);
  const promptPreview = h("textarea", {
    class: "mono ai-prompt",
    rows: "12",
    readonly: true,
    "aria-label": t("ai.preview"),
  });
  const promptLen = h("span", { class: "muted small" });
  const previewBox = h(
    "details",
    { class: "ai-preview" },
    h("summary", null, t("ai.preview"), " ", promptLen),
    promptPreview,
  );

  const readForm = (): AiPromptForm => {
    form.packageId = idIn.value;
    form.packageName = nameIn.value;
    form.sections = sectionBoxes.filter((b) => b.c.input.checked).map((b) => b.s as AiSection);
    form.simulation = simBox.input.checked;
    form.tests = testsBox.input.checked;
    form.notes = notesIn.value;
    form.jsonSchema = schemaBox.input.checked;
    return form;
  };
  const loadPrompt = async (): Promise<string> => {
    const r = await api.get<{ prompt: string; length: number }>("/config/ai-prompt", promptQuery(readForm()));
    state = withPrompt(state, r.prompt);
    promptPreview.value = r.prompt;
    promptLen.textContent = t("ai.chars", { n: r.length.toLocaleString() });
    render();
    return r.prompt;
  };
  const copyPrompt = async () => copyText(await loadPrompt(), promptPreview);
  const savePrompt = async () => {
    const p = await loadPrompt();
    saveText(p, `udsbench-prompt-${readForm().packageId || "paket"}.md`, "text/markdown");
  };

  // --- Schritt 2: Antwort ---------------------------------------------------------------------------
  const answerIn = h("textarea", {
    class: "mono ai-answer",
    rows: "10",
    spellcheck: "false",
    placeholder: t("ai.answerPlaceholder"),
    "aria-label": t("ai.answer"),
  });
  const fileIn = h("input", { type: "file", accept: ".md,.markdown,.yaml,.yml,.txt,.json" });
  fileIn.addEventListener("change", async () => {
    const f = fileIn.files?.[0];
    if (!f) return;
    answerIn.value = await readFileText(f);
    state = withAnswer(state, answerIn.value);
    render();
  });
  answerIn.addEventListener("input", () => {
    state = withAnswer(state, answerIn.value);
    render();
  });
  const resultBox = h("div", { class: "ai-result", "aria-live": "polite" });
  const checkBtn = button(
    t("ai.check"),
    async () => {
      const content = answerIn.value;
      try {
        const r = await api.post<AiCheckResult>("/config/ai-check", { content, do_import: false });
        state = withCheck(state, content, r);
      } catch (exc) {
        toastError(exc);
      }
      render();
    },
    { kind: "primary" },
  );

  // --- Schritt 3: Import ----------------------------------------------------------------------------
  const activateBox = checkbox(t("ai.activate"), true);
  const overwriteBox = checkbox(t("ai.overwrite"), false);
  const importBox = h("div", { "aria-live": "polite" });
  const importBtn = button(
    t("ai.import"),
    async () => {
      if (!canImport(state)) return;
      try {
        const r = await api.post<AiCheckResult>("/config/ai-check", {
          content: state.answer,
          do_import: true,
          activate: activateBox.input.checked,
          overwrite: overwriteBox.input.checked,
        });
        state = withImport(state, r);
        if (r.ok) {
          toast(t("ai.imported", { id: r.package?.id ?? "" }), "success");
          await store.refreshAll().catch(() => undefined);
        }
      } catch (exc) {
        toastError(exc);
      }
      render();
    },
    { kind: "primary", cls: "ai-import-btn" },
  );

  const stepEls = [1, 2, 3].map((n) =>
    h(
      "li",
      { class: "ai-step-ind" },
      h("span", { class: "ai-step-no" }, String(n)),
      t(`ai.step${n}` as MsgKey),
    ),
  );

  const render = () => {
    const step = currentStep(state);
    stepEls.forEach((el, i) => {
      el.classList.toggle("done", step > i + 1);
      el.classList.toggle("current", step === i + 1);
    });
    checkBtn.disabled = !canCheck(state);
    importBtn.disabled = !canImport(state);
    const v = checkView(state.check);
    if (v.tone === "none") {
      replace(resultBox, state.answer.trim() ? h("p", { class: "muted small" }, t("ai.notChecked")) : null);
    } else if (v.tone === "ok") {
      replace(
        resultBox,
        h(
          "div",
          { class: "ai-ok" },
          h(
            "strong",
            null,
            t("ai.checkOk", {
              id: state.check?.package?.id ?? "",
              version: state.check?.package?.version ?? "",
            }),
          ),
        ),
        h(
          "div",
          { class: "tiles" },
          v.tiles.map((x) =>
            h(
              "div",
              { class: ["tile", x.count ? null : "tile-zero"] },
              h("div", { class: "tile-value" }, String(x.count)),
              h("div", { class: "tile-label" }, t(`ai.count.${x.key}` as MsgKey)),
            ),
          ),
        ),
        v.todos.length
          ? h(
              "div",
              { class: "ai-todos" },
              h(
                "h4",
                { class: "label" },
                t("ai.todos", { n: v.todos.length }),
                infoIcon("packages.ai_todos"),
              ),
              h(
                "ul",
                null,
                v.todos.map((x) => h("li", null, x)),
              ),
            )
          : h("p", { class: "muted small" }, t("ai.noTodos")),
      );
    } else {
      replace(
        resultBox,
        h(
          "div",
          { class: "ai-fail" },
          h("strong", null, state.check?.message ?? t("ai.checkFail")),
          h("span", null, t("ai.checkFailHint")),
        ),
        v.errors.length
          ? h(
              "table",
              { class: "tbl ai-errors" },
              h("thead", null, h("tr", null, h("th", null, t("ai.errPath")), h("th", null, t("ai.errMsg")))),
              h(
                "tbody",
                null,
                v.errors.map((e) =>
                  h("tr", null, h("td", null, h("code", null, e.path)), h("td", { title: e.raw }, e.message)),
                ),
              ),
            )
          : null,
        v.fixPrompt
          ? h(
              "div",
              { class: "row" },
              button(t("ai.copyFix"), () => copyText(v.fixPrompt ?? "", promptPreview), { kind: "primary" }),
              infoIcon("packages.ai_fix"),
              h("span", { class: "muted small" }, t("ai.fixHint")),
            )
          : null,
        v.todos.length
          ? h(
              "div",
              { class: "ai-todos" },
              h("h4", { class: "label" }, t("ai.todos", { n: v.todos.length })),
              h(
                "ul",
                null,
                v.todos.map((x) => h("li", null, x)),
              ),
            )
          : null,
      );
    }
    const imp = state.imported;
    replace(
      importBox,
      imp?.ok
        ? h(
            "div",
            { class: "ai-ok ai-done" },
            h("strong", null, t("ai.importDone", { id: imp.package?.id ?? "" })),
            h("p", null, t("ai.importNext")),
            h(
              "div",
              { class: "row" },
              button(t("ai.toConnection"), () => ctx.navigate("connection")),
              button(t("ai.toTests"), () => ctx.navigate("tests")),
              button(t("ai.toUds"), () => ctx.navigate("uds")),
            ),
          )
        : !canImport(state)
          ? h("p", { class: "muted small" }, t("ai.importLocked"))
          : null,
    );
  };

  const stepHead = (n: number, key: MsgKey, help: string) =>
    h(
      "h4",
      { class: "ai-step-title" },
      h("span", { class: "ai-step-no" }, String(n)),
      t(key),
      infoIcon(help),
    );

  const el = h(
    "section",
    { class: "card ai-card", "aria-labelledby": "ai-title" },
    h(
      "div",
      { class: "card-title ai-head" },
      h("span", { id: "ai-title" }, t("ai.title")),
      h(
        "a",
        {
          href: "#help:ki-konfiguration",
          class: "view-help",
          onclick: (ev: Event) => {
            ev.preventDefault();
            openHelpTopic("ki-konfiguration", "ablauf");
          },
        },
        t("ai.guide"),
      ),
    ),
    h("p", { class: "muted small ai-lead" }, t("ai.lead")),
    h("ol", { class: "ai-steps-ind" }, stepEls),
    h(
      "div",
      { class: "ai-grid" },
      h(
        "div",
        { class: "ai-step" },
        stepHead(1, "ai.step1", "packages.ai_prompt"),
        h("div", { class: "grid" }, field(t("ai.packageId"), idIn), field(t("ai.packageName"), nameIn)),
        h(
          "fieldset",
          null,
          h("legend", null, t("ai.sections"), infoIcon("packages.ai_sections")),
          h(
            "div",
            { class: "inline wrap" },
            sectionBoxes.map((b) => b.c.el),
            testsBox.el,
            simBox.el,
          ),
        ),
        field(t("ai.notes"), notesIn, undefined, "field-wide", "packages.ai_notes"),
        schemaBox.el,
        h(
          "div",
          { class: "row" },
          button(t("ai.copyPrompt"), copyPrompt, { kind: "primary", cls: "ai-copy" }),
          button(t("ai.savePrompt"), savePrompt),
          button(
            t("ai.showPrompt"),
            async () => {
              await loadPrompt();
              previewBox.open = true;
            },
            { kind: "ghost" },
          ),
        ),
        h("p", { class: "ai-privacy" }, t("ai.privacy")),
        previewBox,
      ),
      h(
        "div",
        { class: "ai-step" },
        stepHead(2, "ai.step2", "packages.ai_answer"),
        answerIn,
        h(
          "div",
          { class: "row" },
          checkBtn,
          h("label", { class: "inline small muted" }, t("ai.orFile"), fileIn),
        ),
        resultBox,
      ),
      h(
        "div",
        { class: "ai-step" },
        stepHead(3, "ai.step3", "packages.ai_todos"),
        h("div", { class: "inline wrap" }, activateBox.el, overwriteBox.el),
        h("div", { class: "row" }, importBtn),
        importBox,
      ),
    ),
  );
  render();
  return el;
}
