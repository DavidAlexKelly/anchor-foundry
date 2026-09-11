import { describe, expect, it } from "vitest";

import {
  TOAST_DISMISSES_ITSELF,
  appliedMessage,
  undoOffer,
  undoneMessage,
} from "./undo-toast";
import type { ActionExecuteResult } from "./types";

function result(over: Partial<ActionExecuteResult> = {}): ActionExecuteResult {
  return {
    ok: true,
    error: null,
    dataset_version: 3,
    instance: {
      id: "i-1",
      object_type_id: "t-1",
      source_id: "s-1",
      primary_key: "p1",
      properties: {},
      created_at: "",
      updated_at: "",
    } as ActionExecuteResult["instance"],
    touched: [],
    run_id: "r-1",
    can_undo: true,
    undo_refusal: null,
    ...over,
  };
}

describe("what the success message offers", () => {
  it("offers the undo when the server says it can be given", () => {
    expect(undoOffer(result())).toEqual({ kind: "offer", runId: "r-1" });
  });

  it("says why when it cannot", () => {
    // **The whole point.** p.155 calls this "your only opportunity", so a
    // toast that silently omits the button tells somebody nothing at the one
    // moment they could have acted — and two of the six reasons are things
    // they can do something about.
    const said = undoOffer(
      result({ can_undo: false, undo_refusal: "This object has been edited since." }),
    );
    expect(said).toEqual({
      kind: "refused",
      why: "This object has been edited since.",
    });
  });

  it("still says something when the server gave no reason", () => {
    // A blank line where an explanation should be reads as a broken screen.
    const said = undoOffer(result({ can_undo: false, undo_refusal: null }));
    expect(said.kind).toBe("refused");
    expect(said.kind === "refused" && said.why).toBeTruthy();
  });

  it("offers nothing at all when the action did not succeed", () => {
    // There the error is the message; an undo line beside it would be
    // answering a question nobody asked.
    expect(undoOffer(result({ ok: false, error: "the write failed" })).kind).toBe(
      "none",
    );
  });

  it("does not offer an undo it has no run to name", () => {
    // `can_undo` without a `run_id` is a server that contradicted itself, and
    // a button with nothing to send is worse than no button.
    expect(undoOffer(result({ run_id: null })).kind).toBe("refused");
  });
});

describe("what the toast says", () => {
  it("names the action rather than the properties", () => {
    expect(appliedMessage("Fix contact")).toBe("Fix contact applied.");
    expect(undoneMessage("Fix contact")).toBe("Fix contact undone.");
  });

  it("distinguishes the two states", () => {
    // A toast that read the same before and after the undo would leave
    // somebody unsure whether the press worked.
    expect(appliedMessage("Fix contact")).not.toBe(undoneMessage("Fix contact"));
  });
});

describe("how long it stays", () => {
  it("does not dismiss itself", () => {
    // A deliberate divergence, asserted so it is a decision rather than an
    // absence of code: p.156's remediations for a missed toast — migrate to a
    // new object type, or drop all edits on it — do not exist here, so a timer
    // would leave somebody with no route at all.
    expect(TOAST_DISMISSES_ITSELF).toBe(false);
  });
});
