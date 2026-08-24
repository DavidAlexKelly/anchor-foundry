import { describe, expect, it } from "vitest";

import {
  applyTemplate, DEFAULT_TEMPLATE, distribute, pageGroups, TEMPLATES, templateFor,
} from "./layout-template";
import type { LayoutNodes } from "../../lib/workshop-module";

/** p.52's layout template picker (Foundry `workshop` p.52-53).
 *
 * The claim worth testing hardest is the one p.53 does not make: **applying a
 * template never loses a widget**. Everything else here is shape.
 */

const section = (id: string, parent: string, kids: string[] = []) => ({
  [id]: {
    type: { resolvedName: "CanvasSection" },
    isCanvas: true,
    props: { direction: "columns" },
    parent,
    nodes: kids,
    linkedNodes: {},
  },
});

const widget = (id: string, parent: string) => ({
  [id]: { type: { resolvedName: "CanvasText" }, props: { text: id }, parent, nodes: [] },
});

/** A page with the sections and widgets named, as a serialised layout. */
function doc(pageKids: string[], extra: object = {}): LayoutNodes {
  return {
    ROOT: {
      type: { resolvedName: "CanvasContainer" }, isCanvas: true, props: {},
      nodes: ["p1"], linkedNodes: {},
    },
    p1: {
      type: { resolvedName: "CanvasPage" }, isCanvas: true, props: { title: "Page" },
      parent: "ROOT", nodes: pageKids, linkedNodes: {},
    },
    ...extra,
  } as unknown as LayoutNodes;
}

/** Deterministic ids, so a transform can be asserted against names. */
function minter(prefix = "n") {
  let n = 0;
  return () => `${prefix}${++n}`;
}

const idsIn = (layout: LayoutNodes, id: string) =>
  ((layout[id] as { nodes?: string[] })?.nodes ?? []);

describe("the catalogue", () => {
  it("offers a template for p.52's default", () => {
    // The constant and the catalogue have to agree, or a new page would be
    // built from a template the picker cannot show as selected.
    expect(templateFor(DEFAULT_TEMPLATE)).toBeDefined();
  });

  it("gives every template a unique key", () => {
    const keys = TEMPLATES.map((t) => t.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("gives every template at least one section", () => {
    // A template with no sections is a picker entry that empties the page and
    // offers nowhere to put anything back.
    for (const t of TEMPLATES) expect(t.sections.length).toBeGreaterThan(0);
  });

  it("only uses directions CanvasSection understands", () => {
    // **The list checked against its subject, not against a copy of itself**
    // (§191's rule). A template naming a direction the section does not
    // implement would render as the default and silently be a different
    // layout from its own preview.
    const known = new Set(["columns", "rows", "flow", "toolbar"]);
    for (const t of TEMPLATES) {
      for (const s of t.sections) expect(known.has(s.direction)).toBe(true);
    }
  });
});

describe("pageGroups", () => {
  it("groups each section's widgets", () => {
    const layout = doc(["s1", "s2"], {
      ...section("s1", "p1", ["w1", "w2"]), ...section("s2", "p1", ["w3"]),
      ...widget("w1", "s1"), ...widget("w2", "s1"), ...widget("w3", "s2"),
    });
    expect(pageGroups(layout, "p1")).toEqual([["w1", "w2"], ["w3"]]);
  });

  it("puts a widget sitting straight on the page in front", () => {
    // A bare widget is at the top of the page far more often than the bottom,
    // and this is what keeps it there.
    const layout = doc(["w0", "s1"], {
      ...widget("w0", "p1"), ...section("s1", "p1", ["w1"]), ...widget("w1", "s1"),
    });
    expect(pageGroups(layout, "p1")).toEqual([["w0"], ["w1"]]);
  });

  it("is empty for a page with nothing on it", () => {
    expect(pageGroups(doc([]), "p1")).toEqual([]);
  });

  it("is empty for a page that is not there", () => {
    expect(pageGroups(doc([]), "nope")).toEqual([]);
  });

  it("keeps an empty section as an empty group", () => {
    // Not the same as having no section: it is a position, and the widgets of
    // the section *after* it must not slide up into it.
    const layout = doc(["s1", "s2"], {
      ...section("s1", "p1", []), ...section("s2", "p1", ["w1"]), ...widget("w1", "s2"),
    });
    expect(pageGroups(layout, "p1")).toEqual([[], ["w1"]]);
  });
});

describe("distribute", () => {
  it("lines groups up with sections one for one", () => {
    expect(distribute([["a"], ["b"]], 2)).toEqual([["a"], ["b"]]);
  });

  it("pours everything past the last section into it", () => {
    // **Narrowing three regions to two.** The surplus has to land somewhere
    // visible; the alternative is a widget with no parent, which is a widget
    // nobody can find and nobody deleted.
    expect(distribute([["a"], ["b"], ["c"], ["d"]], 2)).toEqual([["a"], ["b", "c", "d"]]);
  });

  it("leaves spare sections empty rather than spreading to fill them", () => {
    expect(distribute([["a"]], 3)).toEqual([["a"], [], []]);
  });

  it("keeps order within a merged section", () => {
    expect(distribute([["a", "b"], ["c"]], 1)).toEqual([["a", "b", "c"]]);
  });

  it("returns nothing for a template with no sections", () => {
    expect(distribute([["a"]], 0)).toEqual([]);
  });
});

describe("applyTemplate", () => {
  const twoRows = templateFor("two-rows")!;
  const single = templateFor("single")!;

  it("lays a template down on an empty page", () => {
    const { layout, sections } = applyTemplate(doc([]), "p1", twoRows, minter());
    expect(sections).toEqual(["n1", "n2"]);
    expect(idsIn(layout, "p1")).toEqual(["n1", "n2"]);
    expect((layout.n1 as { props: Record<string, unknown> }).props.direction).toBe("columns");
  });

  it("carries every widget across when the counts match", () => {
    const before = doc(["s1", "s2"], {
      ...section("s1", "p1", ["w1"]), ...section("s2", "p1", ["w2"]),
      ...widget("w1", "s1"), ...widget("w2", "s2"),
    });
    const { layout } = applyTemplate(before, "p1", twoRows, minter());
    expect(idsIn(layout, "n1")).toEqual(["w1"]);
    expect(idsIn(layout, "n2")).toEqual(["w2"]);
  });

  it("loses no widget when the page narrows", () => {
    // **The claim the feature stands on.** Asserted as a set over the whole
    // document rather than by naming the section each landed in, so it stays
    // true if the distribution rule is ever tuned - the rule that must not
    // change is that nothing goes missing.
    const before = doc(["s1", "s2", "s3"], {
      ...section("s1", "p1", ["w1"]), ...section("s2", "p1", ["w2"]),
      ...section("s3", "p1", ["w3"]),
      ...widget("w1", "s1"), ...widget("w2", "s2"), ...widget("w3", "s3"),
    });
    const { layout } = applyTemplate(before, "p1", single, minter());
    for (const w of ["w1", "w2", "w3"]) expect(layout[w]).toBeDefined();
    expect(idsIn(layout, "n1")).toEqual(["w1", "w2", "w3"]);
  });

  it("rehomes a widget that was sitting straight on the page", () => {
    const before = doc(["w0"], { ...widget("w0", "p1") });
    const { layout } = applyTemplate(before, "p1", single, minter());
    expect(idsIn(layout, "n1")).toEqual(["w0"]);
    // And the page lists the section, not the widget - listing both would
    // draw it twice.
    expect(idsIn(layout, "p1")).toEqual(["n1"]);
  });

  it("repoints every carried widget's parent", () => {
    // Craft believes the parent pointer, so a document whose child list and
    // parent pointer disagree is one that renders differently from what it
    // says. Invisible in any test that only reads `nodes`.
    const before = doc(["s1"], { ...section("s1", "p1", ["w1"]), ...widget("w1", "s1") });
    const { layout } = applyTemplate(before, "p1", single, minter());
    expect((layout.w1 as { parent: string }).parent).toBe("n1");
  });

  it("drops the old section nodes", () => {
    const before = doc(["s1"], { ...section("s1", "p1", ["w1"]), ...widget("w1", "s1") });
    const { layout } = applyTemplate(before, "p1", single, minter());
    expect(layout.s1).toBeUndefined();
  });

  it("does not carry the old section's own configuration", () => {
    // A template lays down sections as it describes them. Keeping a previous
    // section's `collapsible` would produce a page that does not match the
    // picture the author clicked.
    const before = doc(["s1"], {
      s1: {
        type: { resolvedName: "CanvasSection" }, isCanvas: true,
        props: { direction: "rows", collapsible: true, title: "Old" },
        parent: "p1", nodes: [], linkedNodes: {},
      },
    } as unknown as object);
    const { layout } = applyTemplate(before, "p1", single, minter());
    const props = (layout.n1 as { props: Record<string, unknown> }).props;
    expect(props.collapsible).toBeUndefined();
    expect(props.direction).toBe("columns");
  });

  it("leaves other pages alone", () => {
    // A template is applied to one page. Touching another is the kind of
    // damage nobody looks for, because they were not on that page.
    const before = {
      ...doc(["s1"], { ...section("s1", "p1", ["w1"]), ...widget("w1", "s1") }),
      p2: {
        type: { resolvedName: "CanvasPage" }, isCanvas: true, props: { title: "Two" },
        parent: "ROOT", nodes: ["s9"], linkedNodes: {},
      },
      ...section("s9", "p2", ["w9"]),
      ...widget("w9", "s9"),
    } as unknown as LayoutNodes;
    const { layout } = applyTemplate(before, "p1", single, minter());
    expect(layout.s9).toBeDefined();
    expect(idsIn(layout, "p2")).toEqual(["s9"]);
    expect(idsIn(layout, "s9")).toEqual(["w9"]);
  });

  it("returns the layout untouched for a page that is not there", () => {
    const before = doc(["s1"], { ...section("s1", "p1") });
    const result = applyTemplate(before, "nope", single, minter());
    expect(result.layout).toBe(before);
    expect(result.sections).toEqual([]);
  });

  it("carries the template's weights and title through", () => {
    const sidebar = templateFor("sidebar")!;
    const { layout } = applyTemplate(doc([]), "p1", sidebar, minter());
    expect((layout.n1 as { props: Record<string, unknown> }).props.weights).toBe("1,3");
  });

  it("sets a title only where the template asks for one", () => {
    // An untitled section draws no header; seeding "" everywhere would give
    // every fresh page a row of blank headers.
    const { layout } = applyTemplate(doc([]), "p1", twoRows, minter());
    expect((layout.n1 as { props: Record<string, unknown> }).props.title).toBeUndefined();
    const toolbar = templateFor("toolbar-and-body")!;
    const applied = applyTemplate(doc([]), "p1", toolbar, minter()).layout;
    expect((applied.n1 as { props: Record<string, unknown> }).props.title).toBe("Toolbar");
  });
});
