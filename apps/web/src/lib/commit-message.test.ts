import { describe, expect, it } from "vitest";

import {
  COMMIT_BLOCK, SETTINGS_FILE, messagePlaceholder, messageProblem, messageRequired,
  settingsFrom,
} from "./commit-message";
import { REFERENCES_BLOCK, prefersIds } from "./settings-file";

const required = (extra: Record<string, unknown> = {}) => ({
  [COMMIT_BLOCK]: { required: true, ...extra },
});

describe("settingsFrom", () => {
  it("reads the file at the root of the repository", () => {
    expect(settingsFrom({ [SETTINGS_FILE]: '{"commitMessages":{"required":true}}' }))
      .toEqual({ commitMessages: { required: true } });
  });

  it("answers an empty object when the file is not there", () => {
    expect(settingsFrom({})).toEqual({});
    expect(settingsFrom({ "src/a.sql": "SELECT 1" })).toEqual({});
  });

  it("answers an empty object for a file that will not parse", () => {
    // Somebody may be part-way through typing it, and a half-typed brace must
    // not disable the button they are about to press.
    expect(settingsFrom({ [SETTINGS_FILE]: "{ not json" })).toEqual({});
    expect(settingsFrom({ [SETTINGS_FILE]: "" })).toEqual({});
  });

  it("answers an empty object for JSON that is not an object", () => {
    // `JSON.parse("[1]")` succeeds, and `[]["commitMessages"]` is undefined —
    // so this is about saying so rather than about crashing.
    expect(settingsFrom({ [SETTINGS_FILE]: "[1]" })).toEqual({});
    expect(settingsFrom({ [SETTINGS_FILE]: "null" })).toEqual({});
    expect(settingsFrom({ [SETTINGS_FILE]: '"a string"' })).toEqual({});
  });

  it("is not confused by a settings file somewhere other than the root", () => {
    // p.17 and p.105 both put it at the root. A nested one is somebody else's
    // file that happens to share a name.
    expect(settingsFrom({ [`src/${SETTINGS_FILE}`]: '{"commitMessages":{"required":true}}' }))
      .toEqual({});
  });
});

describe("messageRequired", () => {
  it("reads the key p.114's file actually carries", () => {
    // **Written out rather than built from `COMMIT_BLOCK`.** Every other test
    // here spells the block through the constant, so renaming the constant
    // renames both sides and the sweep walks straight past it — the fixture
    // bug this repository has now hit four times. The server's copy is the
    // other half of the same claim, guarded by
    // `test_the_browser_reads_the_same_settings_file_the_server_does`.
    expect(COMMIT_BLOCK).toBe("commitMessages");
    expect(SETTINGS_FILE).toBe("repoSettings.json");
    expect(messageRequired({ commitMessages: { required: true } })).toBe(true);
  });

  it("is off unless the file says so", () => {
    // The half that has to be true for the other half to be safe: a
    // requirement arriving by default would refuse the next commit in every
    // repository that already exists.
    expect(messageRequired({})).toBe(false);
    expect(messageRequired({ tagNameValidation: { regex: "^v" } })).toBe(false);
  });

  it("is on when the block says required", () => {
    expect(messageRequired(required())).toBe(true);
  });

  it("reads required as `true`, not as truthy", () => {
    // `"required": "no"` would otherwise turn the rule **on**.
    expect(messageRequired({ [COMMIT_BLOCK]: { required: "no" } })).toBe(false);
    expect(messageRequired({ [COMMIT_BLOCK]: { required: 1 } })).toBe(false);
    expect(messageRequired({ [COMMIT_BLOCK]: { required: false } })).toBe(false);
  });

  it("is not fooled by a block of the wrong shape", () => {
    expect(messageRequired({ [COMMIT_BLOCK]: true })).toBe(false);
    expect(messageRequired({ [COMMIT_BLOCK]: "required" })).toBe(false);
    expect(messageRequired({ [COMMIT_BLOCK]: null })).toBe(false);
  });
});

describe("messageProblem", () => {
  it("says nothing when the repository does not ask", () => {
    expect(messageProblem("", {})).toBeNull();
  });

  it("says nothing once something has been typed", () => {
    expect(messageProblem("add the transform", required())).toBeNull();
  });

  it("treats whitespace as empty", () => {
    // The same rule the server applies, and for the same reason.
    expect(messageProblem("   ", required())).not.toBeNull();
    expect(messageProblem("\n\t", required())).not.toBeNull();
  });

  it("uses the repository's own sentence where it wrote one", () => {
    expect(messageProblem("", required({ errorMessage: "Say what changed." })))
      .toBe("Say what changed.");
  });

  it("names the file when nobody wrote a sentence", () => {
    // A rule whose source cannot be found is one nobody can change.
    expect(messageProblem("", required())).toContain(SETTINGS_FILE);
  });

  it("ignores an errorMessage that is not a usable sentence", () => {
    // A blank one would leave the reader with nothing at all.
    expect(messageProblem("", required({ errorMessage: "   " }))).toContain(SETTINGS_FILE);
    expect(messageProblem("", required({ errorMessage: 7 }))).toContain(SETTINGS_FILE);
  });
});

describe("messagePlaceholder", () => {
  it("says the message is required where it is", () => {
    expect(messagePlaceholder(required())).toContain("requires");
  });

  it("is the ordinary invitation otherwise", () => {
    expect(messagePlaceholder({})).toBe("What changed, and why");
  });
});

// ---- p.115's dataset aliases (§444) -----------------------------------------
describe("prefersIds", () => {
  it("is off unless the file asks", () => {
    // Every repository here predates the setting and names datasets by name.
    expect(prefersIds({})).toBe(false);
    expect(prefersIds({ [REFERENCES_BLOCK]: {} })).toBe(false);
  });

  it("is on for p.115's id preference", () => {
    expect(prefersIds({ [REFERENCES_BLOCK]: { prefer: "id" } })).toBe(true);
  });

  it("reads the value written out, so an unknown one changes nothing", () => {
    // p.115's other option is the path form, and a settings file carrying a
    // word nobody here understands should keep the behaviour it had rather
    // than pick one.
    expect(prefersIds({ [REFERENCES_BLOCK]: { prefer: "name" } })).toBe(false);
    expect(prefersIds({ [REFERENCES_BLOCK]: { prefer: "rid" } })).toBe(false);
    expect(prefersIds({ [REFERENCES_BLOCK]: { prefer: true } })).toBe(false);
  });

  it("is not fooled by a block of the wrong shape", () => {
    expect(prefersIds({ [REFERENCES_BLOCK]: "id" })).toBe(false);
    expect(prefersIds({ [REFERENCES_BLOCK]: null })).toBe(false);
  });

  it("reads the key p.115's file actually carries", () => {
    // Written out rather than built from the constant — the fixture bug §441
    // hit and this repository has now met five times.
    expect(REFERENCES_BLOCK).toBe("datasetReferences");
    expect(prefersIds({ datasetReferences: { prefer: "id" } })).toBe(true);
  });

  it("is read out of the same file the commit rule is", () => {
    // One settings file, one parser: a repository declares its conventions in
    // one place, and both rules go through `settingsFrom`.
    const file = { [SETTINGS_FILE]: JSON.stringify({
      commitMessages: { required: true },
      datasetReferences: { prefer: "id" },
    }) };
    expect(messageRequired(settingsFrom(file))).toBe(true);
    expect(prefersIds(settingsFrom(file))).toBe(true);
  });
});
