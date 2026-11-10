/**
 * Kleiner, sicherer Markdown-Renderer für die Hilfe.
 * Baut DOM-Knoten direkt (kein innerHTML) – Text wird dadurch immer escaped.
 * Unterstützt: Überschriften (#–###), Absätze, Listen (ungeordnet/geordnet), Tabellen,
 * Code-Blöcke (```), Zitate (>), **fett**, *kursiv* bzw. _kursiv_, `code`, Links (help:, http(s):, #anker).
 */

export interface MdSection {
  anchor: string;
  title: string;
  level: number;
}

export interface MdOptions {
  /** Abschnitte des Themas (Reihenfolge = Überschriften ab Ebene 2) → Anker-IDs. */
  sections?: MdSection[];
  /** Präfix für Element-IDs (vermeidet Kollisionen im Dokument). */
  idPrefix?: string;
  /** Klick auf einen help:-Link. */
  onHelpLink?: (topic: string, anchor: string | null) => void;
}

export interface HelpHref {
  topic: string;
  anchor: string | null;
}

/** "help:topic#anchor" → {topic, anchor}; sonst null. */
export function parseHelpHref(href: string): HelpHref | null {
  const m = /^help:([\w.-]+)(?:#([\w.-]+))?$/.exec(href.trim());
  if (!m || !m[1]) return null;
  return { topic: m[1], anchor: m[2] ?? null };
}

/** Nur sichere Ziele erlauben. */
export function safeHref(href: string): string | null {
  const h = href.trim();
  if (/^https?:\/\//i.test(h)) return h;
  if (/^#[\w.-]+$/.test(h)) return h;
  if (/^help:/.test(h)) return parseHelpHref(h) ? h : null;
  return null;
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

const INLINE =
  /(`+)([^`]+?)\1|\*\*([^*]+?)\*\*|__([^_]+?)__|\*([^*\s][^*]*?)\*|(?<![\w])_([^_\s][^_]*?)_(?![\w])|\[([^\]]+)\]\(([^)\s]+)\)/g;

/** Inline-Markdown → Knoten. */
export function renderInline(text: string, opts: MdOptions = {}): Node[] {
  const out: Node[] = [];
  let last = 0;
  // eigene RegExp-Instanz je Aufruf (rekursive Aufrufe dürfen lastIndex nicht teilen)
  const re = new RegExp(INLINE.source, "g");
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push(document.createTextNode(text.slice(last, m.index)));
    if (m[2] !== undefined) {
      const c = document.createElement("code");
      c.textContent = m[2];
      out.push(c);
    } else if (m[3] !== undefined || m[4] !== undefined) {
      const b = document.createElement("strong");
      b.append(...renderInline(m[3] ?? m[4] ?? "", opts));
      out.push(b);
    } else if (m[5] !== undefined || m[6] !== undefined) {
      const i = document.createElement("em");
      i.append(...renderInline(m[5] ?? m[6] ?? "", opts));
      out.push(i);
    } else if (m[7] !== undefined && m[8] !== undefined) {
      out.push(renderLink(m[7], m[8], opts));
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}

function renderLink(label: string, href: string, opts: MdOptions): Node {
  const safe = safeHref(href);
  if (!safe) return document.createTextNode(label);
  const a = document.createElement("a");
  a.append(...renderInline(label, opts));
  const help = parseHelpHref(safe);
  if (help) {
    a.href = `#help:${help.topic}${help.anchor ? `#${help.anchor}` : ""}`;
    a.className = "help-link";
    a.dataset["topic"] = help.topic;
    if (help.anchor) a.dataset["anchor"] = help.anchor;
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      opts.onHelpLink?.(help.topic, help.anchor);
    });
  } else if (safe.startsWith("#")) {
    a.href = `#${opts.idPrefix ?? ""}${safe.slice(1)}`;
  } else {
    a.href = safe;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  }
  return a;
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
}

const isTableSep = (l: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

/** Markdown-Text → Container-Element. */
export function renderMarkdown(md: string, opts: MdOptions = {}): HTMLElement {
  const root = document.createElement("div");
  root.className = "md";
  const lines = md.replace(/\r\n?/g, "\n").split("\n");
  const sections = (opts.sections ?? []).filter((s) => s.level > 1);
  let secIdx = 0;
  const used = new Set<string>();
  let i = 0;

  const para: string[] = [];
  const flushPara = () => {
    if (!para.length) return;
    const p = document.createElement("p");
    p.append(...renderInline(para.join(" "), opts));
    root.appendChild(p);
    para.length = 0;
  };

  while (i < lines.length) {
    const line = lines[i] ?? "";
    // Code-Block
    const fence = /^\s*```\s*([\w-]*)\s*$/.exec(line);
    if (fence) {
      flushPara();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i] ?? "")) buf.push(lines[i++] ?? "");
      i++;
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      if (fence[1]) code.dataset["lang"] = fence[1];
      code.textContent = buf.join("\n");
      pre.appendChild(code);
      root.appendChild(pre);
      continue;
    }
    if (!line.trim()) {
      flushPara();
      i++;
      continue;
    }
    // Überschrift
    const hm = /^(#{1,6})\s+(.+?)\s*(?:\{#([\w-]+)\})?\s*#*\s*$/.exec(line);
    if (hm) {
      flushPara();
      const level = Math.min(hm[1]?.length ?? 1, 4);
      const text = hm[2] ?? "";
      const el = document.createElement(`h${level}` as "h1");
      el.append(...renderInline(text, opts));
      let anchor = hm[3] ?? null;
      if (!anchor && level > 1) {
        const s = sections[secIdx];
        if (s && (s.title === text || slugify(s.title) === slugify(text))) {
          anchor = s.anchor;
          secIdx++;
        } else {
          const found = sections.findIndex(
            (x, k) => k >= secIdx && (x.title === text || slugify(x.title) === slugify(text)),
          );
          if (found >= 0) {
            anchor = sections[found]?.anchor ?? null;
            secIdx = found + 1;
          }
        }
      }
      anchor = anchor ?? slugify(text);
      let id = anchor;
      for (let n = 2; used.has(id); n++) id = `${anchor}-${n}`;
      used.add(id);
      el.id = `${opts.idPrefix ?? ""}${id}`;
      el.dataset["anchor"] = id;
      root.appendChild(el);
      i++;
      continue;
    }
    // Tabelle
    if (line.includes("|") && isTableSep(lines[i + 1] ?? "")) {
      flushPara();
      const head = splitRow(line);
      const align = splitRow(lines[i + 1] ?? "").map((c) =>
        /^:-+:$/.test(c) ? "center" : /-:$/.test(c) ? "right" : "",
      );
      i += 2;
      const wrap = document.createElement("div");
      wrap.className = "md-table";
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const tr = document.createElement("tr");
      head.forEach((c, k) => {
        const th = document.createElement("th");
        if (align[k]) th.style.textAlign = align[k] ?? "";
        th.append(...renderInline(c, opts));
        tr.appendChild(th);
      });
      thead.appendChild(tr);
      const tbody = document.createElement("tbody");
      while (i < lines.length && (lines[i] ?? "").includes("|") && (lines[i] ?? "").trim()) {
        const row = document.createElement("tr");
        splitRow(lines[i] ?? "").forEach((c, k) => {
          const td = document.createElement("td");
          if (align[k]) td.style.textAlign = align[k] ?? "";
          td.append(...renderInline(c, opts));
          row.appendChild(td);
        });
        tbody.appendChild(row);
        i++;
      }
      table.append(thead, tbody);
      wrap.appendChild(table);
      root.appendChild(wrap);
      continue;
    }
    // Liste
    const lm = LIST_RE.exec(line);
    if (lm) {
      flushPara();
      const ordered = /\d/.test(lm[2] ?? "");
      const list = document.createElement(ordered ? "ol" : "ul");
      const baseIndent = (lm[1] ?? "").length;
      while (i < lines.length) {
        const m = LIST_RE.exec(lines[i] ?? "");
        if (!m || (m[1] ?? "").length > baseIndent + 1 || /\d/.test(m[2] ?? "") !== ordered) break;
        const parts = [m[3] ?? ""];
        i++;
        // Fortsetzungszeilen (eingerückt, kein neuer Listenpunkt)
        while (i < lines.length && /^\s{2,}\S/.test(lines[i] ?? "") && !LIST_RE.exec(lines[i] ?? "")) {
          parts.push((lines[i] ?? "").trim());
          i++;
        }
        const li = document.createElement("li");
        li.append(...renderInline(parts.join(" "), opts));
        list.appendChild(li);
      }
      root.appendChild(list);
      continue;
    }
    // Zitat
    if (/^\s*>/.test(line)) {
      flushPara();
      const buf: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i] ?? ""))
        buf.push((lines[i++] ?? "").replace(/^\s*>\s?/, ""));
      const bq = document.createElement("blockquote");
      bq.append(...renderInline(buf.join(" "), opts));
      root.appendChild(bq);
      continue;
    }
    // Trennlinie
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      flushPara();
      root.appendChild(document.createElement("hr"));
      i++;
      continue;
    }
    para.push(line.trim());
    i++;
  }
  flushPara();
  return root;
}

/** Suchbegriffe im Text hervorheben (<mark>), sicher als DOM-Knoten. */
export function highlight(text: string, query: string): Node[] {
  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length > 1)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!terms.length) return [document.createTextNode(text)];
  const re = new RegExp(`(${terms.join("|")})`, "gi");
  const out: Node[] = [];
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push(document.createTextNode(text.slice(last, m.index)));
    const mark = document.createElement("mark");
    mark.textContent = m[0];
    out.push(mark);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}

/** Nummerierte Schritte (1. **Titel**: Text) aus Markdown extrahieren – für das Onboarding. */
export function extractSteps(md: string): { title: string; text: string }[] {
  const out: { title: string; text: string }[] = [];
  const lines = md.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const m = /^\s*\d+[.)]\s+\*\*(.+?)\*\*:?\s*(.*)$/.exec(lines[i] ?? "");
    if (!m) continue;
    const parts = [m[2] ?? ""];
    while (i + 1 < lines.length && /^\s{2,}\S/.test(lines[i + 1] ?? "") && !LIST_RE.test(lines[i + 1] ?? ""))
      parts.push((lines[++i] ?? "").trim());
    out.push({ title: (m[1] ?? "").replace(/:$/, ""), text: parts.join(" ").trim() });
  }
  return out;
}
