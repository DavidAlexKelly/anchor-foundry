import { describe, expect, it } from "vitest";

import {
  afterBatch, batchable, batchProblem, rowsTouched, csvEntries, csvPlan, csvValue, nextCell, parseCsv, pendingRows, rowFor, rowProblems, tableColumns,
  type TableRow,
} from "./action-table";

/** `workshop` p.511's Action table (§702): what a row holds and what is wrong
 * with one before anything is sent. */

const status = { api_name: "status", display_name: "Status", data_type: "string", required: true };
const note = { api_name: "note", display_name: "Note", data_type: "string" };
const secret = { api_name: "was", data_type: "string", hidden: true };

const row = (key: number, subjectId: string, values: Record<string, unknown> = { status: "open" },
  over: Partial<TableRow> = {}): TableRow => ({ key, subjectId, values, status: "draft", ...over });

describe("tableColumns", () => {
  it("draws every parameter but the hidden ones", () => {
    expect(tableColumns([status, secret, note]).map((p) => p.api_name)).toEqual(["status", "note"]);
  });
});

describe("rowFor", () => {
  it("seeds a row from its object, then the widget's default, then the parameter's", () => {
    const made = rowFor(
      7, [status, note, { ...secret, default_value: "d" }],
      { id: "o1", properties: { status: "closed", was: "before" } },
      { note: "local" },
    );
    expect(made).toEqual({
      key: 7, subjectId: "o1", status: "draft",
      values: { status: "closed", note: "local", was: "before" },
    });
  });

  it("starts empty without an object", () => {
    const made = rowFor(1, [status], null, {});
    expect(made.subjectId).toBe("");
    expect(made.values).toEqual({ status: "" });
  });
});

describe("rowProblems", () => {
  it("passes rows that each have an object and every required value", () => {
    expect(rowProblems([row(1, "a"), row(2, "b")], [status, note]).size).toBe(0);
  });

  it("asks for an object", () => {
    expect(rowProblems([row(1, "")], [status]).get(1)).toBe("Choose an object for this row.");
  });

  it("names a required value left empty", () => {
    expect(rowProblems([row(1, "a", { status: "" })], [status, note]).get(1))
      .toBe("Status is required.");
    expect(rowProblems([row(1, "a", { status: null })], [status]).get(1))
      .toBe("Status is required.");
  });

  it("refuses the same object twice, naming the row it is already in", () => {
    const problems = rowProblems([row(1, "a"), row(2, "b"), row(3, "a")], [status]);
    expect([...problems.keys()]).toEqual([3]);
    expect(problems.get(3)).toBe(
      "This object is also in row 1, and two edits to one object would conflict.");
  });

  it("does not check rows already submitted", () => {
    const done = row(1, "", {}, { status: "done" });
    expect(rowProblems([done, row(2, "a")], [status]).size).toBe(0);
  });

  it("counts a submitted row's object as taken by nothing", () => {
    // A row that went through is not an edit still to send, so the same object
    // in a new row is a second, later submission rather than a conflict.
    const done = row(1, "a", {}, { status: "done" });
    expect(rowProblems([done, row(2, "a")], [status]).size).toBe(0);
  });
});

describe("nextCell", () => {
  it("moves down and up a column", () => {
    expect(nextCell(0, 2, 3, "down")).toEqual({ row: 1, column: 2 });
    expect(nextCell(2, 1, 3, "up")).toEqual({ row: 1, column: 1 });
  });

  it("stops at either end", () => {
    expect(nextCell(2, 0, 3, "down")).toBeNull();
    expect(nextCell(0, 0, 3, "up")).toBeNull();
  });
});

describe("pendingRows", () => {
  it("is everything not already done", () => {
    const rows = [row(1, "a", {}, { status: "done" }), row(2, "b"), row(3, "c", {}, { status: "refused" })];
    expect(pendingRows(rows).map((r) => r.key)).toEqual([2, 3]);
  });
});


describe("parseCsv", () => {
  it("reads quoted fields with commas, newlines and doubled quotes", () => {
    const text = 'key,note\r\nT1,"a, b"\nT2,"line\nbreak"\nT3,"say ""hi"""\n';
    expect(parseCsv(text)).toEqual([
      ["key", "note"], ["T1", "a, b"], ["T2", "line\nbreak"], ["T3", 'say "hi"'],
    ]);
  });

  it("drops blank lines and a byte-order mark", () => {
    expect(parseCsv("\uFEFFa,b\n\n1,2\n\n")).toEqual([["a", "b"], ["1", "2"]]);
  });

  it("keeps an empty field inside a row", () => {
    expect(parseCsv("a,,c")).toEqual([["a", "", "c"]]);
  });
});

describe("csvPlan", () => {
  const columns = [status, note, { api_name: "done", display_name: "Done?", data_type: "boolean" }];

  it("finds the object's column and each parameter by api or display name", () => {
    const plan = csvPlan([" Object ", "STATUS", "Done?", "colour"], columns);
    expect(plan.keyColumn).toBe(0);
    expect(plan.cells.map((c) => [c.column, c.parameter.api_name])).toEqual([[1, "status"], [2, "done"]]);
    expect(plan.ignored).toEqual(["colour"]);
  });

  it("takes the first of two columns naming one parameter and reports the second", () => {
    const plan = csvPlan(["key", "status", "Status"], columns);
    expect(plan.cells.map((c) => c.column)).toEqual([1]);
    expect(plan.ignored).toEqual(["Status"]);
  });

  it("takes the first column that names the object, and reports a second", () => {
    const plan = csvPlan(["Object", "Key", "status"], columns);
    expect(plan.keyColumn).toBe(0);
    expect(plan.ignored).toEqual(["Key"]);
  });

  it("says when there is no object column", () => {
    expect(csvPlan(["status"], columns).keyColumn).toBe(-1);
  });
});

describe("csvValue", () => {
  it("leaves text for the server to coerce, and empty as no value", () => {
    expect(csvValue(" 42 ", "integer")).toBe("42");
    expect(csvValue("  ", "string")).toBe("");
  });

  it("turns a yes/no into one", () => {
    expect(csvValue("Yes", "boolean")).toBe(true);
    expect(csvValue("0", "boolean")).toBe(false);
    expect(csvValue("maybe", "boolean")).toBe("maybe");
  });
});

describe("csvEntries", () => {
  it("gives each row's key and only the values the file has columns for", () => {
    const plan = csvPlan(["key", "status"], [status, note]);
    expect(csvEntries([[" T1 ", "closed"], ["T2"]], plan)).toEqual([
      { key: "T1", values: { status: "closed" } },
      { key: "T2", values: { status: "" } },
    ]);
  });
});

describe("one batch call (§796)", () => {
  const rows = [{ subjectId: "i1" }, { subjectId: "i2" }];
  it("is for an action the Object Table's batch takes, with every row about an object", () => {
    expect(batchable({ inline_edit_refusals: [], object_type_id: "t" }, rows)).toBe(true);
    // One that creates, deletes or links goes a row at a time.
    expect(batchable({ inline_edit_refusals: ["has a 'create_object' rule"],
                       object_type_id: "t" }, rows)).toBe(false);
    // An action on an interface has no one type.
    expect(batchable({ inline_edit_refusals: [], object_type_id: null }, rows)).toBe(false);
    expect(batchable({ inline_edit_refusals: [], object_type_id: "t" },
                     [...rows, { subjectId: "" }])).toBe(false);
  });
});

describe("a batch's limit and answer (§796)", () => {
  it("is p.131's row limit", () => {
    expect(batchProblem(200, 200)).toBeNull();
    expect(batchProblem(201, 200)).toBe("One submission takes at most 200 rows (action-types p.131).");
  });

  it("marks every row done, or every row refused with the batch's reason", () => {
    expect(afterBatch({ ok: true })).toEqual({ status: "done" });
    expect(afterBatch({ ok: false, error: "no" })).toEqual({ status: "refused", message: "no" });
    expect(afterBatch({ ok: false })).toEqual({ status: "refused", message: "Refused." });
  });
});

describe("what a batch call of rows produced (§800)", () => {
  const made = (key: string, change = "created") => ({ object_type_id: "t", primary_key: key, change });

  it("is every row's own output, in order", () => {
    expect(rowsTouched({ ok: true, results: [
      { touched: [made("a"), made("p1", "modified")] }, { touched: [] }, {}, { touched: [made("b")] },
    ] })).toEqual([made("a"), made("p1", "modified"), made("b")]);
  });

  it("is nothing when the batch did not land", () => {
    expect(rowsTouched({ ok: false, results: [{ touched: [made("a")] }] })).toEqual([]);
    expect(rowsTouched({ ok: true })).toEqual([]);
  });
});

