import { describe, expect, it } from "vitest";

import {
  addItem, buttonTypeOf, duplicateItem, itemsOf, newItemId, removeItem, renameItem,
} from "./button-items";

const two = [{ id: "i_1", label: "CSV" }, { id: "i_2", label: "Copy" }];

describe("buttonTypeOf", () => {
  it("is p.483's three types, and inline for anything else", () => {
    expect(buttonTypeOf("menu")).toBe("menu");
    expect(buttonTypeOf("twoPart")).toBe("twoPart");
    expect(buttonTypeOf("inline")).toBe("inline");
    expect(buttonTypeOf(undefined)).toBe("inline");
    expect(buttonTypeOf("dropdown")).toBe("inline");
  });
});

describe("itemsOf", () => {
  it("keeps what has an id and a label, and drops the rest", () => {
    expect(itemsOf([
      ...two, { label: "no id" }, { id: "", label: "empty id" }, { id: "i_9" }, "junk", null,
    ])).toEqual(two);
    expect(itemsOf("nope")).toEqual([]);
  });
});

describe("newItemId", () => {
  it("is the first i_N not taken", () => {
    expect(newItemId([])).toBe("i_1");
    expect(newItemId(two)).toBe("i_3");
    expect(newItemId([{ id: "i_2", label: "" }])).toBe("i_3");
    expect(newItemId([{ id: "i_2", label: "" }, { id: "i_3", label: "" }])).toBe("i_4");
  });
});

describe("addItem and duplicateItem (p.486)", () => {
  it("adds a named item at the end", () => {
    expect(addItem(two)).toEqual([...two, { id: "i_3", label: "Option 3" }]);
  });

  it("duplicates right after the original, with an id of its own", () => {
    // A copy sharing the id would fire the original's events.
    const withIcon = [{ id: "i_1", label: "CSV", leftIcon: "⤓" }, two[1]!];
    expect(duplicateItem(withIcon, "i_1")).toEqual([
      withIcon[0], { id: "i_3", label: "CSV", leftIcon: "⤓" }, withIcon[1],
    ]);
  });

  it("duplicates nothing for an id it does not have", () => {
    expect(duplicateItem(two, "i_9")).toEqual(two);
  });
});

describe("removeItem and renameItem", () => {
  it("removes by id and renames by id, leaving the rest", () => {
    expect(removeItem(two, "i_1")).toEqual([two[1]]);
    expect(renameItem(two, "i_2", "Clipboard")).toEqual([two[0], { id: "i_2", label: "Clipboard" }]);
  });
});
