/** p.12's "Export graph to SVG" (§423). */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  FALLBACK, clipped, escaped, resolved, svgFilename, svgFor, tokenValue,
  type DrawableNode,
} from "./graph-svg";
import { NODE_W, layoutOf } from "./graph-layout";

/** A node and where the level layout puts it — the pair, because the export
 *  draws a node only where it has been told one goes (§424). */
const node = (
  id: string, layer: number, position: number, over: Partial<DrawableNode> = {},
) => ({
  node: { id, kind: "dataset", name: id, ...over } as DrawableNode,
  at: { id, layer, position },
});

const PAIRS = [
  node("raw", 0, 0),
  node("clean", 1, 0, { kind: "model", name: "Clean orders" }),
  node("out", 2, 0),
];
const NODES = PAIRS.map((p) => p.node);
const PLACES = layoutOf(PAIRS.map((p) => p.at), "level").at;
const EDGES = [{ from: "raw", to: "clean" }, { from: "clean", to: "out" }];

/** `svgFor` with the level layout applied, which is what every test here
 *  means by "the picture". */
const drawn = (
  nodes: readonly DrawableNode[],
  at: Map<string, { x: number; y: number }>,
  edges: { from: string; to: string }[] = [],
  options: Parameters<typeof svgFor>[2] = {},
) => svgFor(nodes, edges, { ...options, at });

describe("resolving the palette", () => {
  it("falls back to what globals.css actually declares", () => {
    // **The mirror, pinned** (§420's shape). These constants stand in for the
    // document when there is none, and a drifted one is a wrong colour that
    // never appears in the app and always appears in the export — the kind of
    // difference nobody finds by looking at either file.
    const css = readFileSync(
      join(__dirname, "..", "app", "globals.css"), "utf8",
    );
    const root = css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {")));
    for (const [token, expected] of Object.entries(FALLBACK)) {
      const declared = new RegExp(`${token}:\\s*([^;]+);`).exec(root);
      expect(declared?.[1]?.trim(), token).toBe(expected);
    }
  });


  it("falls back when there is no document to ask", () => {
    // Every unit test is this case, and so is a render on a server.
    expect(tokenValue("--ink")).toBe(FALLBACK["--ink"]);
  });

  it("prefers a live value and trims it", () => {
    // `getPropertyValue` returns the declaration including the space after
    // the colon, and " #fff" is not a colour an SVG renderer accepts.
    const styles = { getPropertyValue: () => " #123456 " } as unknown as CSSStyleDeclaration;
    expect(tokenValue("--ink", styles)).toBe("#123456");
  });

  it("treats an empty live value as no value", () => {
    // A token the document does not declare comes back as "", which is not a
    // colour — falling through is the only useful answer.
    const styles = { getPropertyValue: () => "" } as unknown as CSSStyleDeclaration;
    expect(tokenValue("--ink", styles)).toBe(FALLBACK["--ink"]);
  });

  it("replaces every var() in a value, not just the first", () => {
    // **Two of them**, which is the only input that can tell a global replace
    // from a single one — and a value with two is an ordinary shorthand.
    expect(resolved("var(--ink)")).toBe(FALLBACK["--ink"]);
    expect(resolved("1px solid var(--line)"))
      .toBe(`1px solid ${FALLBACK["--line"]}`);
    expect(resolved("var(--ink) var(--line)"))
      .toBe(`${FALLBACK["--ink"]} ${FALLBACK["--line"]}`);
  });

  it("gives a token nobody declares a visible colour rather than leaving var()", () => {
    // A `var()` in a standalone SVG makes the renderer drop the attribute, so
    // the shape disappears; black is wrong and visible, which is better.
    expect(resolved("var(--invented)")).toBe("#000000");
  });

  it("leaves a plain colour alone", () => {
    expect(resolved("#aabbcc")).toBe("#aabbcc");
  });
});

describe("text that cannot break the file", () => {
  it("escapes the three characters that matter", () => {
    expect(escaped("<a> & </a>")).toBe("&lt;a&gt; &amp; &lt;/a&gt;");
  });

  it("escapes the ampersand first, so an escape is not escaped twice", () => {
    // `&lt;` written out as `&amp;lt;` is the classic ordering bug, and the
    // only input that shows it is one with both characters in it.
    expect(escaped("&<")).toBe("&amp;&lt;");
  });

  it("clips a long name and says it clipped", () => {
    expect(clipped("abcdefgh", 4)).toBe("abc…");
    expect(clipped("abc", 4)).toBe("abc");
    expect(clipped("abcd", 4)).toBe("abcd");
  });

  it("clips to nothing rather than to an ellipsis alone", () => {
    expect(clipped("abc", 0)).toBe("");
    expect(clipped("abc", 1)).toBe("…");
  });
});

describe("the picture", () => {
  it("is a standalone document", () => {
    const svg = drawn(NODES, PLACES, EDGES);
    expect(svg.startsWith("<svg xmlns=\"http://www.w3.org/2000/svg\"")).toBe(true);
    expect(svg.endsWith("</svg>")).toBe(true);
  });

  it("carries every node's name", () => {
    const svg = drawn(NODES, PLACES, EDGES);
    for (const n of NODES) expect(svg).toContain(n.name);
  });

  it("puts a card where the screen puts it", () => {
    // **The same geometry, imported rather than restated** — an export that
    // laid the cards out with its own arithmetic would be a second picture of
    // the same graph, with nothing to say which copy was wrong.
    const one = node("mid", 2, 1);
    const at = layoutOf([one.at], "level").at;
    const place = at.get("mid")!;
    expect(drawn([one.node], at)).toContain(`x="${place.x}" y="${place.y}"`);
  });

  it("draws one path per edge", () => {
    expect(drawn(NODES, PLACES, EDGES).match(/<path /g)).toHaveLength(2);
  });

  it("does not draw an edge to a node it is not drawing", () => {
    // A line reaching off the picture reads as a node the export lost.
    const svg = drawn(NODES, PLACES, [...EDGES, { from: "clean", to: "elsewhere" }]);
    expect(svg.match(/<path /g)).toHaveLength(2);
  });

  it("carries the colouring that was on screen", () => {
    const svg = drawn(NODES, PLACES, EDGES, { colours: { raw: "var(--line-strong)" } });
    expect(svg).toContain(`fill="${FALLBACK["--line-strong"]}"`);
    // And `var()` never reaches the file, which is the whole point of
    // resolving: a standalone SVG resolves it against nothing.
    expect(svg).not.toContain("var(--");
  });

  it("leaves an uncoloured node without a bar rather than with a black one", () => {
    // §419's "No colour" has to export as no colour; a bar filled with the
    // fallback would be a reading nobody chose.
    const one = node("raw", 0, 0);
    const plain = drawn([one.node], layoutOf([one.at], "level").at);
    expect(plain.match(/width="4"/g)).toBeNull();
  });

  it("draws the selection, because that is how the graph looked", () => {
    const svg = drawn(NODES, PLACES, EDGES, { selected: ["clean"] });
    expect(svg).toContain('stroke-width="2"');
  });

  it("escapes a name that would otherwise close the document", () => {
    const one = node("x", 0, 0, { name: "<script>" });
    const svg = drawn([one.node], layoutOf([one.at], "level").at);
    expect(svg).toContain("&lt;script&gt;");
    expect(svg).not.toContain("<script>");
  });

  it("names the two kinds whose word is not their column", () => {
    const pair = [node("o", 0, 0, { kind: "object_type" }),
                  node("c", 0, 1, { kind: "connection" })];
    const svg = drawn(pair.map((p) => p.node), layoutOf(pair.map((p) => p.at), "level").at);
    expect(svg).toContain(">object type<");
    expect(svg).toContain(">data source<");
  });

  it("is still a document when the graph is empty", () => {
    // §214: a zero-by-zero file no viewer will open reads as a broken export
    // rather than as a picture of an empty project.
    const svg = drawn([], new Map());
    expect(svg).toContain("<svg ");
    expect(svg).toMatch(/width="([4-9]\d\d|\d{4,})"/);
  });

  it("is wide enough for the layers it drew", () => {
    const one = node("far", 6, 0);
    const at = layoutOf([one.at], "level").at;
    const width = Number(drawn([one.node], at).match(/ width="(\d+)"/)![1]);
    expect(width).toBeGreaterThanOrEqual(at.get("far")!.x + NODE_W);
  });

  it("carries a title, and escapes it too", () => {
    expect(drawn([], new Map(), [], { title: "A & B" }))
      .toContain("<title>A &amp; B</title>");
  });
});

describe("the filename", () => {
  it("carries the project and the day", () => {
    expect(svgFilename("Sales Ops", new Date("2026-03-04T12:00:00Z")))
      .toBe("sales-ops-2026-03-04.svg");
  });

  it("has nothing in it a filesystem refuses", () => {
    expect(svgFilename("A/B: “quoted”", new Date("2026-03-04T12:00:00Z")))
      .toBe("a-b-quoted-2026-03-04.svg");
  });

  it("still has a name when the project's is unusable", () => {
    expect(svgFilename("///", new Date("2026-03-04T12:00:00Z")))
      .toBe("lineage-2026-03-04.svg");
  });
});
