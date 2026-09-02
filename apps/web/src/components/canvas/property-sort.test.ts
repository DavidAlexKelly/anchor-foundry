import { describe, expect, it } from "vitest";

import {
  FIXED_SORTS, ORDERABLE_HINT, ORDERABLE_TYPES,
  entryOf, isOrderable, orderableProperties, requestSort,
} from "./property-sort";

/** §231's one answer to "which properties can a page be ordered by", after
 * `STATUS.md` §230 found six places guessing at it. */

/** What the ontology says in most of these. `title` is text — refused
 * permanently — and `site` is a geopoint, which nobody would order. */
const DECLARED = [
  { api_name: "title", data_type: "string" },
  { api_name: "capacity", data_type: "integer" },
  { api_name: "ratio", data_type: "float" },
  { api_name: "opened", data_type: "date" },
  { api_name: "seen_at", data_type: "timestamp" },
  { api_name: "site", data_type: "geopoint" },
  { api_name: "live", data_type: "boolean" },
];

describe("which declared types carry an ordering", () => {
  it("mirrors the server's list exactly", () => {
    // **Not a copy for convenience.** `object_sets.ORDERABLE_TYPES` is the
    // authority; a browser list that drifted wider would offer a setting the
    // server answers with a sentence about property types, and one that
    // drifted narrower would hide a sort that works. Both went unnoticed for
    // ten units, which is what this file exists to stop.
    expect([...ORDERABLE_TYPES].sort()).toEqual(["date", "float", "integer", "timestamp"]);
  });

  it("refuses text permanently rather than pending", () => {
    // decision 0006 §2: Postgres orders by the database collation and
    // OpenSearch by byte order, so 'Z' < 'a' differs between them. A list
    // sorted one way on one deployment and another on the next is the
    // invisible kind of wrong, and no amount of typing fixes it.
    expect(isOrderable({ api_name: "title", data_type: "string" })).toBe(false);
    expect(ORDERABLE_HINT).toMatch(/permanently/);
  });

  it("refuses a property whose type nobody declared", () => {
    // §221's rule: absence is a refusal, not a permission. A property with no
    // declared type has been checked by nobody, and an ordering over it is the
    // untyped comparison this whole decision exists to prevent.
    expect(isOrderable({ api_name: "mystery" })).toBe(false);
    expect(isOrderable({ api_name: "mystery", data_type: null })).toBe(false);
    expect(isOrderable({ api_name: "mystery", data_type: "" })).toBe(false);
  });

  it("keeps the type's own order and drops the rest", () => {
    // The declaration order is the order the panel shows, because that is the
    // order somebody arranged their ontology in.
    expect(orderableProperties(DECLARED).map((p) => p.api_name))
      .toEqual(["capacity", "ratio", "opened", "seen_at"]);
    expect(orderableProperties([])).toEqual([]);
  });

  it("names every type it excludes, not only text", () => {
    // A `geopoint` is a pair and a `boolean` has two values; neither has an
    // ordering anybody would agree on, and both are easy to leave in a filter
    // written as "not string".
    expect(isOrderable({ api_name: "site", data_type: "geopoint" })).toBe(false);
    expect(isOrderable({ api_name: "live", data_type: "boolean" })).toBe(false);
    expect(isOrderable({ api_name: "blob", data_type: "json" })).toBe(false);
    expect(isOrderable({ api_name: "file", data_type: "attachment" })).toBe(false);
  });
});

describe("reading one written sort", () => {
  it("reads the four fixed ones with their direction already in the key", () => {
    expect(Object.keys(FIXED_SORTS).sort()).toEqual(["-key", "key", "oldest", "recent"]);
    expect(entryOf("recent")).toEqual({
      key: "recent", property: "", descending: false, fixed: true,
    });
    expect(entryOf("-key")).toEqual({
      key: "-key", property: "", descending: true, fixed: true,
    });
  });

  it("reads a property sort in both directions", () => {
    expect(entryOf("capacity")).toEqual({
      key: "capacity", property: "capacity", descending: false, fixed: false,
    });
    expect(entryOf("-capacity")).toEqual({
      key: "-capacity", property: "capacity", descending: true, fixed: false,
    });
  });

  it("names nothing for a direction with no property under it", () => {
    // A bare `-` would go to the server as an unknown sort, and the author
    // would read a sentence about property types for what is a blank field.
    expect(entryOf("-")).toBeNull();
    expect(entryOf("- ")).toBeNull();
    expect(entryOf("")).toBeNull();
    expect(entryOf("   ")).toBeNull();
    expect(entryOf(null)).toBeNull();
    expect(entryOf(7)).toBeNull();
  });
});

describe("what a widget sends, given what the type declares", () => {
  it("sends a fixed sort without consulting the ontology at all", () => {
    // **The check is ordered on purpose.** Every unconfigured widget holds one
    // of these four; making them wait for a type read would evaluate the set
    // twice on every load, for a sort that never needed a type.
    expect(requestSort("recent", undefined, "key")).toBe("recent");
    expect(requestSort("-key", undefined, "key")).toBe("-key");
  });

  it("sends a property sort the type declares as orderable", () => {
    expect(requestSort("capacity", DECLARED, "key")).toBe("capacity");
    expect(requestSort("-seen_at", DECLARED, "key")).toBe("-seen_at");
  });

  it("falls back where the property is declared but has no order", () => {
    expect(requestSort("title", DECLARED, "key")).toBe("key");
    expect(requestSort("-site", DECLARED, "key")).toBe("key");
  });

  it("falls back where the property is gone from the type", () => {
    // The stale-document case. §214's rule: read a value the document holds
    // but the platform refuses back to the default, rather than sending it on
    // and showing a load error where a small control should be.
    expect(requestSort("capacity", [], "key")).toBe("key");
    expect(requestSort("removed", DECLARED, "key")).toBe("key");
  });

  it("falls back for a blank sort and for one that names nothing", () => {
    expect(requestSort("", DECLARED, "key")).toBe("key");
    expect(requestSort(undefined, DECLARED, "key")).toBe("key");
    expect(requestSort("-", DECLARED, "key")).toBe("key");
  });

  it("waits rather than guessing while the ontology is unresolved", () => {
    // **`undefined` is a third answer and the widget needs all three.**
    // Sending the fallback here would order the first page one way and the
    // second another once the type landed, which reads as a broken widget
    // rather than as loading. An *empty* list is not the same state: it says
    // the type declares nothing orderable, and the fallback is correct then.
    expect(requestSort("capacity", undefined, "key")).toBeUndefined();
    expect(requestSort("capacity", [], "key")).toBe("key");
  });

  it("takes the caller's own fallback, which is not always a sort at all", () => {
    // The Loop's is `""` — p.132's unconfigured order is the set's own, and
    // `useSetPage` sends no `sort` key for an empty string. The Dropdown's is
    // `key`, because a picker with no predictable order is a worse picker.
    expect(requestSort("title", DECLARED, "")).toBe("");
    expect(requestSort(undefined, DECLARED, "")).toBe("");
    expect(requestSort("capacity", DECLARED, "")).toBe("capacity");
  });

  it("does not read a sort off the prototype chain", () => {
    // `entryOf` checks `FIXED_SORTS` with `Object.hasOwn`, and the property
    // lookup is a scan of the declared list rather than an index — so neither
    // half can be satisfied by a name every object has.
    expect(requestSort("constructor", DECLARED, "key")).toBe("key");
    expect(requestSort("toString", DECLARED, "key")).toBe("key");
    expect(requestSort("__proto__", DECLARED, "key")).toBe("key");
  });
});
