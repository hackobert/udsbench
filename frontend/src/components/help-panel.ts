/** Hilfe als rechte Seitenleiste: Suche, Inhaltsverzeichnis, Themenansicht mit Verlauf. */
import type { ApiClient } from "../api";
import { debounce, h, replace } from "../dom";
import { helpBus, setTooltips, type HelpRequest, type Tooltip } from "../help";
import { t } from "../i18n";
import { highlight, renderMarkdown, type MdSection } from "../markdown";

export interface HelpTopicMeta {
  id: string;
  title: string;
  category?: string;
  intro?: string;
  keywords?: string[];
  contexts?: string[];
  sections: MdSection[];
}

export interface HelpTopic extends HelpTopicMeta {
  markdown: string;
  related?: HelpTopicMeta[];
}

export interface HelpIndex {
  categories: { name: string; topics: HelpTopicMeta[] }[];
  contexts: Record<string, string[]>;
}

interface SearchHit {
  topic: string;
  topic_title: string;
  category: string;
  anchor: string | null;
  section: string;
  snippet: string;
  score: number;
}

type Page =
  | { kind: "home" }
  | { kind: "topic"; topic: string; anchor: string | null }
  | { kind: "search"; query: string }
  | { kind: "context"; view: string; field: string | null };

export interface HelpPanel {
  el: HTMLElement;
  open: (req?: HelpRequest) => void;
  close: () => void;
  toggle: () => void;
  isOpen: () => boolean;
  focusSearch: () => void;
  dispose: () => void;
}

export function createHelpPanel(api: ApiClient, onVisibility: (open: boolean) => void): HelpPanel {
  let index: HelpIndex | null = null;
  const topicCache = new Map<string, HelpTopic>();
  const history: Page[] = [];
  let pos = -1;
  let opened = false;

  const searchIn = h("input", {
    type: "search",
    class: "help-search",
    placeholder: t("help.searchPlaceholder"),
    "aria-label": t("help.search"),
    spellcheck: "false",
  });
  const backBtn = h(
    "button",
    { class: "btn btn-ghost btn-icon", title: t("help.back"), "aria-label": t("help.back") },
    "‹",
  );
  const fwdBtn = h(
    "button",
    { class: "btn btn-ghost btn-icon", title: t("help.forward"), "aria-label": t("help.forward") },
    "›",
  );
  const homeBtn = h("button", { class: "btn btn-ghost", title: t("help.contents") }, t("help.contents"));
  const closeBtn = h(
    "button",
    { class: "btn btn-ghost btn-icon", title: t("help.close"), "aria-label": t("help.close") },
    "×",
  );
  const body = h("div", { class: "help-body", tabindex: "-1" });
  const el = h(
    "aside",
    { class: "help-panel", "aria-label": t("help.title"), hidden: true },
    h(
      "div",
      { class: "help-head" },
      h(
        "div",
        { class: "help-head-row" },
        h("strong", { class: "help-title" }, t("help.title")),
        backBtn,
        fwdBtn,
        homeBtn,
        closeBtn,
      ),
      searchIn,
    ),
    body,
  );

  const loadIndex = async (): Promise<HelpIndex> => {
    if (!index) {
      const [idx, tips] = await Promise.all([
        api.get<HelpIndex>("/help"),
        api.get<Record<string, Tooltip>>("/help/tooltips").catch(() => ({})),
      ]);
      index = idx;
      setTooltips(tips);
    }
    return index;
  };
  const loadTopic = async (id: string): Promise<HelpTopic> => {
    const c = topicCache.get(id);
    if (c) return c;
    const tp = await api.get<HelpTopic>(`/help/topics/${encodeURIComponent(id)}`);
    topicCache.set(id, tp);
    return tp;
  };

  const go = (p: Page, push = true) => {
    if (push) {
      history.splice(pos + 1);
      history.push(p);
      pos = history.length - 1;
    }
    backBtn.disabled = pos <= 0;
    fwdBtn.disabled = pos >= history.length - 1;
    void render(p);
  };

  const topicLink = (id: string, title: string, anchor: string | null = null, cls = "help-toc-link") =>
    h(
      "a",
      {
        href: `#help:${id}`,
        class: cls,
        onclick: (ev: Event) => {
          ev.preventDefault();
          go({ kind: "topic", topic: id, anchor });
        },
      },
      title,
    );

  const renderHome = async () => {
    const idx = await loadIndex();
    replace(
      body,
      h("p", { class: "help-lead" }, t("help.homeLead")),
      ...idx.categories.map((c) =>
        h(
          "section",
          { class: "help-cat" },
          h("h4", { class: "label" }, c.name),
          h(
            "ul",
            { class: "help-toc" },
            c.topics.map((tp) => h("li", null, topicLink(tp.id, tp.title))),
          ),
        ),
      ),
    );
  };

  const renderTopicInto = (tp: HelpTopic, anchor: string | null, prefix: HelpTopicMeta[] = []) => {
    const md = renderMarkdown(tp.markdown, {
      sections: tp.sections,
      idPrefix: "help-",
      onHelpLink: (topic, a) => go({ kind: "topic", topic, anchor: a }),
    });
    const nav = tp.sections.length
      ? h(
          "nav",
          { class: "help-sections", "aria-label": t("help.sections") },
          tp.sections.map((s) =>
            h(
              "a",
              {
                href: `#help-${s.anchor}`,
                class: ["chip", s.level > 2 ? "chip-sub" : null],
                onclick: (ev: Event) => {
                  ev.preventDefault();
                  scrollTo(s.anchor);
                },
              },
              s.title,
            ),
          ),
        )
      : null;
    const related = [...prefix, ...(tp.related ?? [])].filter((r) => r.id !== tp.id);
    replace(
      body,
      h("div", { class: "help-crumb label" }, tp.category ?? ""),
      nav,
      md,
      related.length
        ? h(
            "section",
            { class: "help-related" },
            h("h4", { class: "label" }, t("help.related")),
            h(
              "ul",
              { class: "help-toc" },
              related.map((r) => h("li", null, topicLink(r.id, r.title))),
            ),
          )
        : null,
    );
    body.scrollTop = 0;
    if (anchor) requestAnimationFrame(() => scrollTo(anchor));
  };

  const scrollTo = (anchor: string) => {
    const target = body.querySelector<HTMLElement>(`#help-${CSS.escape(anchor)}`);
    if (!target) return;
    target.scrollIntoView({ block: "start" });
    target.classList.add("flash");
    setTimeout(() => target.classList.remove("flash"), 1400);
  };

  const renderSearch = async (q: string) => {
    if (q.trim().length < 2) {
      await renderHome();
      return;
    }
    const r = await api.get<{ results: SearchHit[] }>("/help/search", { q, limit: 30 });
    if (searchIn.value !== q && document.activeElement === searchIn) return;
    replace(
      body,
      h("p", { class: "muted small" }, t("help.hits", { n: r.results.length, q })),
      r.results.length
        ? h(
            "ul",
            { class: "help-hits" },
            r.results.map((hit) =>
              h(
                "li",
                null,
                h(
                  "a",
                  {
                    href: `#help:${hit.topic}`,
                    class: "help-hit",
                    onclick: (ev: Event) => {
                      ev.preventDefault();
                      go({ kind: "topic", topic: hit.topic, anchor: hit.anchor });
                    },
                  },
                  h("span", { class: "help-hit-title" }, ...highlight(hit.section || hit.topic_title, q)),
                  h("span", { class: "help-hit-meta label" }, `${hit.category} · ${hit.topic_title}`),
                  h("span", { class: "help-hit-snippet" }, ...highlight(hit.snippet, q)),
                ),
              ),
            ),
          )
        : h("div", { class: "empty" }, t("help.noHits")),
    );
  };

  const renderContext = async (view: string, field: string | null) => {
    const r = await api.get<{ primary: HelpTopic | null; topics: HelpTopicMeta[]; tooltip?: Tooltip }>(
      `/help/context/${encodeURIComponent(view)}`,
      { field: field ?? undefined },
    );
    if (!r.primary) {
      await renderHome();
      return;
    }
    topicCache.set(r.primary.id, r.primary);
    const anchor = r.tooltip?.topic?.split("#")[1] ?? null;
    renderTopicInto(
      r.primary,
      anchor,
      r.topics.filter((x) => x.id !== r.primary?.id),
    );
  };

  const render = async (p: Page) => {
    try {
      if (p.kind === "home") await renderHome();
      else if (p.kind === "search") await renderSearch(p.query);
      else if (p.kind === "context") await renderContext(p.view, p.field);
      else renderTopicInto(await loadTopic(p.topic), p.anchor);
    } catch (exc) {
      replace(body, h("div", { class: "error-box" }, t("help.loadError", { msg: (exc as Error).message })));
    }
  };

  const doSearch = debounce(() => {
    const q = searchIn.value;
    const cur = history[pos];
    if (cur?.kind === "search") {
      history[pos] = { kind: "search", query: q };
      void render(history[pos] as Page);
    } else go({ kind: "search", query: q });
  }, 200);
  searchIn.addEventListener("input", doSearch);
  searchIn.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      body.querySelector<HTMLElement>(".help-hit")?.focus();
    }
  });
  backBtn.addEventListener("click", () => {
    if (pos > 0) go(history[--pos] as Page, false);
  });
  fwdBtn.addEventListener("click", () => {
    if (pos < history.length - 1) go(history[++pos] as Page, false);
  });
  homeBtn.addEventListener("click", () => go({ kind: "home" }));
  closeBtn.addEventListener("click", () => close());
  el.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      ev.stopPropagation();
      close();
    }
  });

  const show = () => {
    if (!opened) {
      opened = true;
      el.hidden = false;
      onVisibility(true);
    }
  };
  const close = () => {
    if (!opened) return;
    opened = false;
    el.hidden = true;
    onVisibility(false);
  };
  const open = (req?: HelpRequest) => {
    show();
    if (!req || req.kind === "toggle") {
      if (pos < 0) go({ kind: "home" });
      return;
    }
    if (req.kind === "topic") go({ kind: "topic", topic: req.topic, anchor: req.anchor ?? null });
    else if (req.kind === "context") go({ kind: "context", view: req.view, field: req.field ?? null });
    else {
      if (req.query !== undefined) searchIn.value = req.query;
      if (searchIn.value.trim().length >= 2) go({ kind: "search", query: searchIn.value });
      else if (pos < 0) go({ kind: "home" });
      searchIn.focus();
      searchIn.select();
    }
  };

  const off = helpBus.on((req) => {
    if (req.kind === "toggle") {
      if (opened) close();
      else open();
    } else open(req);
  });
  // Tooltips früh laden (Feldhilfe)
  void loadIndex().catch(() => undefined);

  return {
    el,
    open,
    close,
    toggle: () => (opened ? close() : open()),
    isOpen: () => opened,
    focusSearch: () => open({ kind: "search" }),
    dispose: off,
  };
}
