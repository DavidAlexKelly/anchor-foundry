import { describe, expect, it } from "vitest";

import { emptyReason } from "./saved-searches";

describe("what the empty saved-searches list says", () => {
  it("tells an editor how to fill it", () => {
    expect(emptyReason(true)).toContain("Save this search");
  });

  it("does not point a viewer at a button they do not have", () => {
    // The two absences have two remedies and only one is the reader's to
    // apply. "Save this search" to somebody who cannot is an instruction that
    // fails when followed.
    expect(emptyReason(false)).not.toContain("Save this search");
    expect(emptyReason(false)).toContain("An editor can save one");
  });

  it("says there are none, either way", () => {
    expect(emptyReason(true)).toContain("None yet");
    expect(emptyReason(false)).toContain("None yet");
  });

  it("tells a viewer the list is shared, so an empty one is not a private one", () => {
    expect(emptyReason(false)).toContain("everybody");
  });
});
