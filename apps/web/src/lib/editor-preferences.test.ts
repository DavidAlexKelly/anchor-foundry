/** Personal editor preferences (§432; `code-repositories` p.20). */
import { describe, expect, it } from "vitest";
import {
  DEFAULTS,
  bool,
  FONT_SIZES,
  SCOPE_NOTE,
  TAB_SIZES,
  isDefault,
  monacoOptions,
  read,
  write,
} from "./editor-preferences";

describe("the defaults", () => {
  it("are the values the editor already used", () => {
    // **Literals, not `DEFAULTS`.** Comparing the defaults to themselves is a
    // test that cannot fail, and this is the one promise they carry: nobody's
    // editor changes size the day preferences ship, and Reset hands back what
    // `code-editor.tsx` had written into it before it read this module.
    expect(DEFAULTS).toEqual({
      fontSize: 12.5,
      minimap: false,
      wordWrap: false,
      tabSize: 2,
    });
  });
});

describe("bool", () => {
  it("keeps a stored false even when the default is true", () => {
    // The distinction between *false* and *unset*. Both preferences default
    // to `false` today, so through `read` the two are indistinguishable —
    // this is the only place the difference can be made to fail, and it is
    // the day a default flips that it would otherwise bite.
    expect(bool(false, true)).toBe(false);
  });

  it("falls back for anything that is not a boolean", () => {
    expect(bool(undefined, true)).toBe(true);
    expect(bool("false", true)).toBe(true);
    expect(bool(0, true)).toBe(true);
  });
});

describe("read", () => {
  it("answers every field from nothing at all", () => {
    expect(read(null)).toEqual(DEFAULTS);
  });

  it("takes the values that were stored", () => {
    const stored = write({ fontSize: 16, minimap: true, wordWrap: true, tabSize: 4 });
    expect(read(stored)).toEqual({
      fontSize: 16, minimap: true, wordWrap: true, tabSize: 4,
    });
  });

  it("survives a string that is not JSON at all", () => {
    // A truncated write, or a key another application happened to use.
    expect(read("{not json")).toEqual(DEFAULTS);
  });

  it("survives JSON that is not an object", () => {
    expect(read("42")).toEqual(DEFAULTS);
    expect(read("null")).toEqual(DEFAULTS);
    expect(read('"a string"')).toEqual(DEFAULTS);
  });

  it("replaces one unreadable field without losing the others", () => {
    // The failure a blanket try/catch produces: four settings lost because
    // one is a string (§210).
    expect(read('{"fontSize":"huge","minimap":true,"wordWrap":true,"tabSize":4}'))
      .toEqual({ fontSize: DEFAULTS.fontSize, minimap: true, wordWrap: true, tabSize: 4 });
  });

  it("refuses a font size this version does not offer", () => {
    // A value from an older build, or somebody editing storage by hand. 400
    // is a font size that loses the editor.
    expect(read('{"fontSize":400}').fontSize).toBe(DEFAULTS.fontSize);
  });

  it("refuses a tab size this version does not offer", () => {
    expect(read('{"tabSize":3}').tabSize).toBe(DEFAULTS.tabSize);
  });

  it("refuses a boolean that is not one", () => {
    expect(read('{"minimap":"yes"}').minimap).toBe(DEFAULTS.minimap);
    expect(read('{"minimap":1}').minimap).toBe(DEFAULTS.minimap);
  });

  it("keeps a false that was chosen", () => {
    // `false` and "not set" are the same in a careless reader, and only one
    // of them should survive a default that later changes.
    expect(read('{"wordWrap":false}').wordWrap).toBe(false);
  });

  it("ignores keys it does not know", () => {
    expect(read('{"theme":"dark"}')).toEqual(DEFAULTS);
  });

  it("round-trips what it writes", () => {
    const chosen = { fontSize: 18, minimap: true, wordWrap: false, tabSize: 8 };
    expect(read(write(chosen))).toEqual(chosen);
  });
});

describe("write", () => {
  it("stores every field, including the ones left at the default", () => {
    // A partial blob makes "unset" and "set to the default" the same thing,
    // and the day a default changes those two want opposite answers.
    const stored = JSON.parse(write(DEFAULTS));
    expect(Object.keys(stored).sort())
      .toEqual(["fontSize", "minimap", "tabSize", "wordWrap"]);
  });
});

describe("the offered values", () => {
  it("includes the defaults", () => {
    // Otherwise the picker cannot show what is currently in force, and the
    // first render would silently change somebody's editor.
    expect(FONT_SIZES).toContain(DEFAULTS.fontSize);
    expect(TAB_SIZES).toContain(DEFAULTS.tabSize);
  });

  it("offers them smallest first", () => {
    expect([...FONT_SIZES]).toEqual([...FONT_SIZES].sort((a, b) => a - b));
    expect([...TAB_SIZES]).toEqual([...TAB_SIZES].sort((a, b) => a - b));
  });
});

describe("isDefault", () => {
  it("is true for the defaults", () => {
    expect(isDefault(DEFAULTS)).toBe(true);
  });

  it("notices each field on its own", () => {
    // A Reset button that stayed disabled after somebody turned the minimap
    // on would be a control that looks like it works (§214).
    expect(isDefault({ ...DEFAULTS, fontSize: 16 })).toBe(false);
    expect(isDefault({ ...DEFAULTS, minimap: true })).toBe(false);
    expect(isDefault({ ...DEFAULTS, wordWrap: true })).toBe(false);
    expect(isDefault({ ...DEFAULTS, tabSize: 4 })).toBe(false);
  });
});

describe("monacoOptions", () => {
  it("passes the numbers through", () => {
    const options = monacoOptions({ ...DEFAULTS, fontSize: 16, tabSize: 4 });
    expect(options.fontSize).toBe(16);
    expect(options.tabSize).toBe(4);
  });

  it("nests the minimap the way Monaco takes it", () => {
    expect(monacoOptions({ ...DEFAULTS, minimap: true }).minimap)
      .toEqual({ enabled: true });
    expect(monacoOptions({ ...DEFAULTS, minimap: false }).minimap)
      .toEqual({ enabled: false });
  });

  it("turns word wrap into the words Monaco takes", () => {
    // Monaco's `wordWrap` is "on" / "off", not a boolean — a true here is
    // truthy to Monaco and means something else.
    expect(monacoOptions({ ...DEFAULTS, wordWrap: true }).wordWrap).toBe("on");
    expect(monacoOptions({ ...DEFAULTS, wordWrap: false }).wordWrap).toBe("off");
  });
});

describe("the scope note", () => {
  it("says where they are kept and what that costs", () => {
    // Both halves: a note that only said "kept in this browser" leaves
    // somebody to discover the limitation on their second machine.
    expect(SCOPE_NOTE).toContain("browser");
    expect(SCOPE_NOTE.toLowerCase()).toContain("account");
  });
});
