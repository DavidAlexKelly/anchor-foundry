/**
 * Ontology resource statuses, as a form needs them (Foundry
 * `object-link-types` p.253–259).
 *
 * The server decides everything that matters and is tested in
 * `apps/api/tests/test_ontology_status.py`. This is the screen's copy, asked
 * for a different reason: what to offer, and what to say before somebody acts.
 *
 * **The propagation warning is why this file exists.** Demoting an object type
 * silently demotes every property on it (p.256), and a form that does not say
 * so is a form where somebody discovers the change by re-reading a page they
 * thought they understood. A warning that *mispredicts* is worse than none, so
 * the ordering it depends on is pinned here even though the server owns the
 * real one.
 */
import { describe, expect, it } from "vitest";

import type { OntologyStatus } from "@/lib/types";
import {
  canDelete, deleteBlockedReason, propagationWarning, statusesFor,
  wantsDeprecationNote, weakest,
} from "./ontology-status";

function props(...pairs: [string, OntologyStatus][]) {
  return pairs.map(([api_name, status]) => ({ api_name, status }));
}

describe("statusesFor", () => {
  it("offers promoted only on object types", () => {
    // p.255: it "applies only to object types. It is not available for
    // properties, link types, action types or interfaces." Offering it
    // elsewhere would be offering a save the server refuses.
    expect(statusesFor("object_type")).toContain("promoted");
    expect(statusesFor("property")).not.toContain("promoted");
    expect(statusesFor("link_type")).not.toContain("promoted");
  });

  it("offers the other four everywhere", () => {
    for (const kind of ["object_type", "property", "link_type"] as const) {
      for (const status of ["active", "experimental", "deprecated", "example"] as const) {
        expect(statusesFor(kind)).toContain(status);
      }
    }
  });
});

describe("canDelete", () => {
  it("allows exactly p.256's two", () => {
    expect(canDelete("experimental")).toBe(true);
    expect(canDelete("deprecated")).toBe(true);
  });

  it("refuses active, promoted and example", () => {
    // `active` is p.256's own case; `promoted` "inherits similar operational
    // protections" (p.255); `example` is simply not on the list.
    expect(canDelete("active")).toBe(false);
    expect(canDelete("promoted")).toBe(false);
    expect(canDelete("example")).toBe(false);
  });

  it("says why, and what to do, in the server's own words", () => {
    // Somebody who reads the tooltip and then somehow reaches the refusal
    // should not be told two different things.
    expect(deleteBlockedReason("active")).toMatch(/mark it deprecated/);
    expect(deleteBlockedReason("experimental")).toBeNull();
  });
});

describe("weakest", () => {
  it("orders the five as the server does", () => {
    expect(weakest("active", "experimental")).toBe("experimental");
    expect(weakest("promoted", "deprecated")).toBe("deprecated");
    expect(weakest("experimental", "example")).toBe("example");
    expect(weakest("example", "deprecated")).toBe("deprecated");
  });

  it("puts deprecated below everything", () => {
    for (const other of ["promoted", "active", "experimental", "example"] as const) {
      expect(weakest("deprecated", other)).toBe("deprecated");
    }
  });

  it("is symmetric", () => {
    // A warning that depended on argument order would fire on one screen and
    // not another for the same change.
    expect(weakest("active", "example")).toBe(weakest("example", "active"));
  });
});

describe("propagationWarning", () => {
  it("names the properties a demotion will take with it", () => {
    // p.256: "if an object type is changed from `active` to `experimental`,
    // all of its properties will be marked `experimental` as well."
    const warning = propagationWarning(
      "experimental",
      props(["name", "active"], ["code", "active"]),
    );
    expect(warning).toMatch(/2 properties/);
    expect(warning).toMatch(/name, code/);
    expect(warning).toMatch(/experimental/);
  });

  it("says nothing when a type is being raised", () => {
    // p.258 makes promoting properties an *option*, not a consequence — so
    // there is nothing to warn about, and a warning here would be a lie.
    expect(
      propagationWarning("active", props(["name", "experimental"])),
    ).toBeNull();
    expect(
      propagationWarning("promoted", props(["name", "experimental"])),
    ).toBeNull();
  });

  it("counts only the properties actually above the new status", () => {
    // A property already at or below it is untouched, and including it would
    // overstate what the change does.
    expect(
      propagationWarning(
        "experimental",
        props(["already", "experimental"], ["lower", "deprecated"]),
      ),
    ).toBeNull();
    expect(
      propagationWarning(
        "experimental",
        props(["above", "active"], ["already", "experimental"]),
      ),
    ).toMatch(/1 property \(above\)/);
  });

  it("truncates a long list rather than naming forty properties", () => {
    const warning = propagationWarning(
      "example",
      props(
        ["a", "active"], ["b", "active"], ["c", "active"],
        ["d", "active"], ["e", "active"],
      ),
    );
    expect(warning).toMatch(/a, b, c, and 2 more/);
    expect(warning).toMatch(/5 properties/);
  });

  it("says nothing for a type with no properties above it", () => {
    expect(propagationWarning("deprecated", [])).toBeNull();
  });
});

describe("wantsDeprecationNote", () => {
  it("is true only for deprecated", () => {
    // p.254's three fields belong to a deprecated resource, and the server
    // refuses them anywhere else — so the form must not offer them anywhere
    // else either.
    expect(wantsDeprecationNote("deprecated")).toBe(true);
    for (const other of ["promoted", "active", "experimental", "example"] as const) {
      expect(wantsDeprecationNote(other)).toBe(false);
    }
  });
});
