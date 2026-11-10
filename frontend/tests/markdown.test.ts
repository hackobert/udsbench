import { describe, expect, it, vi } from "vitest";
import {
  extractSteps,
  highlight,
  parseHelpHref,
  renderInline,
  renderMarkdown,
  safeHref,
  slugify,
} from "../src/markdown";

const html = (nodes: Node[]) => {
  const d = document.createElement("div");
  d.append(...nodes);
  return d.innerHTML;
};

describe("markdown renderer", () => {
  it("escapes HTML and never creates script/img elements", () => {
    const el = renderMarkdown('# Titel <script>alert(1)</script>\n\nText <img src=x onerror=alert(1)> & "q"');
    expect(el.querySelector("script")).toBeNull();
    expect(el.querySelector("img")).toBeNull();
    expect(el.querySelector("h1")?.textContent).toBe("Titel <script>alert(1)</script>");
    expect(el.innerHTML).toContain("&lt;img");
  });

  it("renders inline formatting", () => {
    expect(html(renderInline("**fett** und *kursiv* und _auch_ und `22 F1 00`"))).toBe(
      "<strong>fett</strong> und <em>kursiv</em> und <em>auch</em> und <code>22 F1 00</code>",
    );
    expect(html(renderInline("snake_case_name bleibt"))).toBe("snake_case_name bleibt");
    expect(html(renderInline("`<b>`"))).toBe("<code>&lt;b&gt;</code>");
  });

  it("renders headings with anchors from topic sections", () => {
    const el = renderMarkdown(
      "# Erste Schritte\n\n## In fünf Minuten zur ersten Antwort\n\nx\n\n## Begriffe\n",
      {
        sections: [
          { anchor: "fuenf-minuten", title: "In fünf Minuten zur ersten Antwort", level: 2 },
          { anchor: "begriffe", title: "Begriffe", level: 2 },
        ],
        idPrefix: "help-",
      },
    );
    const h2 = el.querySelectorAll("h2");
    expect(h2[0]?.id).toBe("help-fuenf-minuten");
    expect(h2[1]?.id).toBe("help-begriffe");
    expect(renderMarkdown("## Ohne Abschnitt {#eigener}").querySelector("h2")?.id).toBe("eigener");
    expect(renderMarkdown("## Über Größe").querySelector("h2")?.id).toBe("ueber-groesse");
  });

  it("renders lists with continuation lines", () => {
    const el = renderMarkdown("1. **Verbinden**: Öffnen Sie\n   *Verbindung*.\n2. Zweitens\n\n* a\n* b");
    expect(el.querySelectorAll("ol > li")).toHaveLength(2);
    expect(el.querySelector("ol li")?.textContent).toBe("Verbinden: Öffnen Sie Verbindung.");
    expect(el.querySelectorAll("ul > li")).toHaveLength(2);
  });

  it("renders tables", () => {
    const el = renderMarkdown("| NRC | Name |\n|---|---:|\n| 0x31 | requestOutOfRange |\n| 0x7F | `x|y` |");
    expect(el.querySelectorAll("thead th")).toHaveLength(2);
    expect(el.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(el.querySelector("tbody td")?.textContent).toBe("0x31");
    expect((el.querySelector("th:nth-child(2)") as HTMLElement).style.textAlign).toBe("right");
  });

  it("renders code blocks verbatim", () => {
    const el = renderMarkdown("```bash\ncurl -s 'x' <y>\n**kein fett**\n```");
    const code = el.querySelector("pre code");
    expect(code?.textContent).toBe("curl -s 'x' <y>\n**kein fett**");
    expect(el.querySelector("strong")).toBeNull();
  });

  it("handles help links, external links and rejects unsafe links", () => {
    const onHelpLink = vi.fn();
    const el = renderMarkdown(
      "Siehe [Padding](help:adressierung-padding#padding), [Web](https://example.org) und [böse](javascript:alert(1))",
      {
        onHelpLink,
      },
    );
    const links = el.querySelectorAll("a");
    expect(links).toHaveLength(2);
    (links[0] as HTMLAnchorElement).click();
    expect(onHelpLink).toHaveBeenCalledWith("adressierung-padding", "padding");
    expect(links[1]?.getAttribute("target")).toBe("_blank");
    expect(links[1]?.getAttribute("rel")).toContain("noopener");
    expect(el.textContent).toContain("böse");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,x")).toBeNull();
    expect(parseHelpHref("help:tests")).toEqual({ topic: "tests", anchor: null });
    expect(parseHelpHref("help:bad topic")).toBeNull();
  });

  it("highlights search terms safely", () => {
    const out = html(highlight("Padding-Byte <x> und padding", "padding"));
    expect(out).toBe("<mark>Padding</mark>-Byte &lt;x&gt; und <mark>padding</mark>");
    expect(html(highlight("a.b", "."))).toBe("a.b");
  });

  it("extracts onboarding steps and slugs", () => {
    const steps = extractSteps(
      "1. **Verbinden**: Öffnen Sie\n   *Verbindung*.\n2. **Live-Trace ansehen**: Frames.\n",
    );
    expect(steps).toEqual([
      { title: "Verbinden", text: "Öffnen Sie *Verbindung*." },
      { title: "Live-Trace ansehen", text: "Frames." },
    ]);
    expect(slugify("Byte- und Frame-Vorschau")).toBe("byte-und-frame-vorschau");
  });
});
