import { infoIcon } from "../help";
import { ApiError, formatErrorDetails } from "../api";
import { CONSOLE_HELP, parseCommand, toCurl } from "../console-parser";
import { button, card } from "../components/ui";
import { h } from "../dom";
import { t } from "../i18n";
import * as storage from "../storage";
import type { AppCtx, View } from "../view";

const HISTORY_KEY = "console.history";
const HISTORY_MAX = 200;

export function createConsoleView(ctx: AppCtx): View {
  const { api } = ctx;
  const history: string[] = storage.load<string[]>(HISTORY_KEY, []);
  let pos = history.length;
  let draft = "";
  const out = h("div", { class: "console-out mono", role: "log", "aria-live": "polite" });
  const input = h("input", {
    type: "text",
    class: "console-in mono",
    spellcheck: "false",
    autocomplete: "off",
    placeholder: "GET /info   ·   uds ecu_a 22 F1 00   ·   help",
    "aria-label": t("console.input"),
  });

  const print = (...nodes: HTMLElement[]) => {
    out.append(...nodes);
    while (out.childElementCount > 400) out.firstElementChild?.remove();
    out.scrollTop = out.scrollHeight;
  };

  const exec = async (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    if (history[history.length - 1] !== trimmed) history.push(trimmed);
    if (history.length > HISTORY_MAX) history.splice(0, history.length - HISTORY_MAX);
    storage.save(HISTORY_KEY, history);
    pos = history.length;
    draft = "";

    const cmd = parseCommand(trimmed);
    const entry = h("div", { class: "console-entry" }, h("div", { class: "console-cmd" }, `› ${trimmed}`));
    print(entry);
    if (cmd.kind === "clear") {
      out.replaceChildren();
      return;
    }
    if (cmd.kind === "help") {
      entry.appendChild(h("pre", { class: "console-help" }, CONSOLE_HELP.join("\n")));
      return;
    }
    if (cmd.kind === "error") {
      entry.appendChild(h("div", { class: "console-err" }, cmd.message));
      return;
    }
    const curl = toCurl(cmd, window.location.origin, Boolean(api.token));
    entry.appendChild(
      h(
        "div",
        { class: "console-curl" },
        h("span", { class: "muted" }, "curl: "),
        h("code", null, curl),
        button("⧉", () => void navigator.clipboard?.writeText(curl).catch(() => undefined), {
          kind: "ghost",
          title: t("console.copy"),
        }),
      ),
    );
    const t0 = performance.now();
    try {
      const res = await api.request<unknown>(cmd.method, cmd.path, cmd.body);
      const ms = Math.round(performance.now() - t0);
      entry.appendChild(h("div", { class: "console-status ok" }, `✔ ${cmd.method} ${cmd.path} · ${ms} ms`));
      entry.appendChild(
        h("pre", { class: "json" }, typeof res === "string" ? res : JSON.stringify(res, null, 2)),
      );
    } catch (exc) {
      const e = exc as ApiError;
      entry.appendChild(
        h(
          "div",
          { class: "console-err" },
          `✖ ${e.status ?? ""} ${e.code ?? ""}: ${e.message}`,
          e instanceof ApiError && e.details
            ? h("pre", null, formatErrorDetails(e.details).join("\n"))
            : null,
        ),
      );
    }
    out.scrollTop = out.scrollHeight;
  };

  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      const v = input.value;
      input.value = "";
      void exec(v);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      if (pos === history.length) draft = input.value;
      if (pos > 0) pos--;
      input.value = history[pos] ?? "";
    } else if (ev.key === "ArrowDown") {
      ev.preventDefault();
      if (pos < history.length) pos++;
      input.value = pos === history.length ? draft : (history[pos] ?? "");
    }
  });

  const el = h(
    "div",
    { class: "console-view" },
    card(
      h(
        "span",
        null,
        t("console.title"),
        " ",
        button(t("common.clear"), () => out.replaceChildren(), { kind: "ghost" }),
        button(
          t("console.clearHistory"),
          () => {
            history.splice(0);
            storage.save(HISTORY_KEY, history);
            pos = 0;
          },
          { kind: "ghost" },
        ),
      ),
      h("p", { class: "muted small" }, t("console.hint")),
      out,
      h(
        "div",
        { class: "console-line" },
        h("span", { class: "console-prompt mono" }, "›"),
        input,
        infoIcon("console.input"),
      ),
    ),
  );

  print(h("pre", { class: "console-help" }, CONSOLE_HELP.join("\n")));
  return {
    el,
    show: () => input.focus(),
    submit: () => void exec(input.value).then(() => (input.value = "")),
  };
}
