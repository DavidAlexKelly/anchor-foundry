import { describe, expect, it } from "vitest";

import {
  MAX_DRAGGED_OBJECTS, OBJECT_MEDIA_TYPE, OBJECT_SET_MEDIA_TYPE, OBJECT_TYPE_CLAUSE,
  carriesPayload, collectKeys, droppedClauses, objectPayload, objectSetPayload,
} from "./drag-payload";
import { PRIMARY_KEY } from "./object-table-selection";

/** A `getData` that answers from a plain map, the way a `DataTransfer` does:
 * a type that was not set reads as the empty string, never as undefined. */
const drag = (data: Record<string, string>) => (type: string) => data[type] ?? "";

const clauses = (typeId: string, keys: string[]) => [
  { property: OBJECT_TYPE_CLAUSE, op: "eq", value: typeId },
  { property: PRIMARY_KEY, op: "in", value: keys },
];

describe("droppedClauses", () => {
  it("makes one dragged object into its type and its key", () => {
    // The Object Table's own selection clause, so a set narrowed by the output
    // reads it by the rule it already knows - with the type in front of it.
    expect(droppedClauses(drag({ [OBJECT_MEDIA_TYPE]: objectPayload("t1", "K9") })))
      .toEqual(clauses("t1", ["K9"]));
  });

  it("carries every object of a dragged set", () => {
    const payload = objectSetPayload("t1", ["A", "B", "C"])!;
    expect(droppedClauses(drag({ [OBJECT_SET_MEDIA_TYPE]: payload })))
      .toEqual(clauses("t1", ["A", "B", "C"]));
  });

  it("prefers the set when a drag carries both, because it says more", () => {
    expect(droppedClauses(drag({
      [OBJECT_SET_MEDIA_TYPE]: objectSetPayload("t2", ["X", "Y"])!,
      [OBJECT_MEDIA_TYPE]: objectPayload("t1", "K9"),
    }))).toEqual(clauses("t2", ["X", "Y"]));
  });

  it("reads a numeric primary key as the string a clause holds", () => {
    const got = droppedClauses(drag({
      [OBJECT_MEDIA_TYPE]: JSON.stringify({ object_type_id: "t1", primary_keys: [7] }),
    }));
    expect(got?.[1]?.value).toEqual(["7"]);
  });

  it("refuses a drag with nothing of ours on it", () => {
    expect(droppedClauses(drag({ "text/plain": "hello" }))).toBeNull();
  });

  it("refuses a payload that is not what its type claims", () => {
    // A drag can come from anywhere on the page, so a shape is checked rather
    // than trusted before every downstream widget reads it.
    const bad = [
      "not json",
      "[1,2]",
      '{"primary_keys": ["K"]}',
      '{"object_type_id": "", "primary_keys": ["K"]}',
      '{"object_type_id": 3, "primary_keys": ["K"]}',
      '{"object_type_id": "t"}',
      '{"object_type_id": "t", "primary_keys": "K"}',
      '{"object_type_id": "t", "primary_keys": []}',
      '{"object_type_id": "t", "primary_keys": [{"x": 1}]}',
      '{"object_type_id": "t", "primary_keys": ["K", null]}',
    ];
    for (const raw of bad) {
      expect(droppedClauses(drag({ [OBJECT_MEDIA_TYPE]: raw })), raw).toBeNull();
    }
  });

  it("refuses more objects than p.274 lets a set carry", () => {
    const keys = Array.from({ length: MAX_DRAGGED_OBJECTS + 1 }, (_, i) => `K${i}`);
    const raw = JSON.stringify({ object_type_id: "t", primary_keys: keys });
    expect(droppedClauses(drag({ [OBJECT_SET_MEDIA_TYPE]: raw }))).toBeNull();
    const most = JSON.stringify({ object_type_id: "t", primary_keys: keys.slice(1) });
    expect(droppedClauses(drag({ [OBJECT_SET_MEDIA_TYPE]: most }))?.[1]?.value)
      .toHaveLength(MAX_DRAGGED_OBJECTS);
  });

  it("does not fall back to the object when a set payload is malformed", () => {
    // A drag that *said* it was a set and is not one is a broken drag, and
    // quietly reading its other type instead would drop something the person
    // did not drag - whether the set failed to parse or parsed to nonsense.
    for (const broken of ["not json", '{"primary_keys": []}']) {
      expect(droppedClauses(drag({
        [OBJECT_SET_MEDIA_TYPE]: broken,
        [OBJECT_MEDIA_TYPE]: objectPayload("t1", "K9"),
      })), broken).toBeNull();
    }
  });
});

describe("objectSetPayload", () => {
  it("is p.274's limit: fewer than 500, and not none", () => {
    expect(MAX_DRAGGED_OBJECTS).toBe(499);
    expect(objectSetPayload("t", [])).toBeNull();
    expect(objectSetPayload("t", Array.from({ length: 499 }, (_, i) => `${i}`))).not.toBeNull();
    expect(objectSetPayload("t", Array.from({ length: 500 }, (_, i) => `${i}`))).toBeNull();
  });
});

describe("carriesPayload", () => {
  it("lights up for either of our types", () => {
    expect(carriesPayload([OBJECT_MEDIA_TYPE])).toBe(true);
    expect(carriesPayload(["text/plain", OBJECT_SET_MEDIA_TYPE])).toBe(true);
  });

  it("stays dark for anything else", () => {
    expect(carriesPayload(["text/plain", "Files"])).toBe(false);
    expect(carriesPayload([])).toBe(false);
  });
});

describe("collectKeys", () => {
  /** A set of `n` rows served a page at a time, recording what was asked. */
  const served = (n: number) => {
    const asked: [number, number][] = [];
    const rows = Array.from({ length: n }, (_, i) => ({ primary_key: `K${i}` }));
    const fetchPage = async (offset: number, limit: number) => {
      asked.push([offset, limit]);
      return rows.slice(offset, offset + limit);
    };
    return { asked, fetchPage };
  };

  it("walks every page of a set p.274 lets be dragged", async () => {
    // Store reads are clamped to one page, so 120 keys is three requests.
    const { asked, fetchPage } = served(120);
    const keys = await collectKeys(fetchPage, 120);
    expect(keys).toHaveLength(120);
    expect(keys?.[119]).toBe("K119");
    expect(asked).toEqual([[0, 50], [50, 50], [100, 50]]);
  });

  it("asks for nothing when the set cannot be dragged", async () => {
    for (const total of [0, MAX_DRAGGED_OBJECTS + 1]) {
      const { asked, fetchPage } = served(total);
      expect(await collectKeys(fetchPage, total), String(total)).toBeNull();
      expect(asked).toEqual([]);
    }
  });

  it("stops at a short page rather than asking past the end", async () => {
    // The set shrank between the count and the read.
    const { asked, fetchPage } = served(60);
    expect(await collectKeys(fetchPage, 180)).toHaveLength(60);
    expect(asked).toEqual([[0, 50], [50, 50]]);
  });

  it("carries nothing when the set emptied before the read", async () => {
    const { fetchPage } = served(0);
    expect(await collectKeys(fetchPage, 3)).toBeNull();
  });
});
