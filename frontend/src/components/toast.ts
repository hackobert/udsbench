import { ApiError, formatErrorDetails } from "../api";
import { h } from "../dom";
import { openHelpTopic } from "../help";
import { t } from "../i18n";

export type ToastKind = "info" | "success" | "warning" | "error";

let container: HTMLElement | null = null;

function host(): HTMLElement {
  if (!container || !container.isConnected) {
    container = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.appendChild(container);
  }
  return container;
}

export function toast(
  message: string,
  kind: ToastKind = "info",
  details: string[] = [],
  timeoutMs?: number,
  action?: { label: string; run: () => void },
): void {
  const el = h(
    "div",
    { class: ["toast", `toast-${kind}`] },
    h(
      "button",
      {
        class: "toast-close",
        title: t("common.close"),
        "aria-label": t("common.close"),
        onclick: () => el.remove(),
      },
      "×",
    ),
    h("div", { class: "toast-msg" }, message),
    details.length
      ? h(
          "ul",
          { class: "toast-details" },
          details.slice(0, 12).map((d) => h("li", null, d)),
        )
      : null,
    action
      ? h(
          "button",
          {
            class: "toast-action",
            onclick: () => {
              action.run();
              el.remove();
            },
          },
          action.label,
        )
      : null,
  );
  host().appendChild(el);
  const ms = timeoutMs ?? (kind === "error" ? 9000 : 3500);
  if (ms > 0) setTimeout(() => el.remove(), ms);
}

/** Passendes Hilfe-Thema zu einem API-Fehler. */
export function helpTopicForError(exc: unknown): string {
  if (exc instanceof ApiError) {
    if (exc.status === 401) return "fehlerbehebung";
    if (exc.code === "validation_error" || exc.code === "validation_failed") return "uds-senden";
    if (/nrc|negative/i.test(exc.code)) return "nrc-referenz";
  }
  return "fehlerbehebung";
}

/** Fehler als Toast (error.message + details) mit Link zur passenden Hilfe. */
export function toastError(exc: unknown, prefix?: string): void {
  const help = { label: t("help.whatToDo"), run: () => openHelpTopic(helpTopicForError(exc)) };
  if (exc instanceof ApiError) {
    toast(
      (prefix ? `${prefix}: ` : "") + exc.message,
      "error",
      formatErrorDetails(exc.details),
      undefined,
      help,
    );
  } else {
    toast(
      (prefix ? `${prefix}: ` : "") + String((exc as Error)?.message ?? exc),
      "error",
      [],
      undefined,
      help,
    );
  }
}
