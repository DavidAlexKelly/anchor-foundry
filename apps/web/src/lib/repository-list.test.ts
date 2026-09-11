import { describe, expect, it } from "vitest";

import { canCreate, emptyReason, openHref, subtitle } from "./repository-list";
import type { Repository } from "./types";

function repository(over: Partial<Repository> = {}): Repository {
  return {
    id: "r-1",
    project_id: "proj",
    name: "Transforms",
    slug: "transforms",
    description: "",
    default_branch: "main",
    resource_id: "res-abc",
    created_at: "",
    updated_at: "",
    ...over,
  };
}

describe("where a repository opens", () => {
  it("**links by resource id, not by slug**", () => {
    // The whole point of the registry's stable ids: a link built from a
    // workspace and project slug stops working the moment somebody renames
    // either, which is exactly when a shared link is most likely to be
    // clicked. This screen produces most of those links.
    expect(openHref(repository())).toBe("/r/res-abc");
    expect(openHref(repository({ slug: "renamed" }))).toBe("/r/res-abc");
  });
});

describe("who is offered the create form", () => {
  it("**not a viewer**, because the server refuses them", () => {
    // Offered-and-refused teaches people the product is unreliable rather
    // than that they are reading rather than writing (§214).
    expect(canCreate("viewer")).toBe(false);
    expect(canCreate("editor")).toBe(true);
    expect(canCreate("owner")).toBe(true);
  });
});

describe("what an empty list says", () => {
  it("says nothing at all when there is something to show", () => {
    expect(emptyReason(2, "editor")).toBeNull();
  });

  it("**tells the two absences apart**, because only one has a remedy here", () => {
    const editor = emptyReason(0, "editor");
    expect(editor).toContain("create one");
    // And what a repository is for, since somebody who has never made one
    // cannot be expected to know why they would.
    expect(editor).toContain("branches, review and history");

    const viewer = emptyReason(0, "viewer");
    expect(viewer).toContain("needs edit access");
    expect(viewer).not.toContain("create one");
  });
});

describe("the line under the name", () => {
  it("**names the default branch**, which is what clicking will open", () => {
    // The one fact about a repository that changes what happens when you
    // click it - and the branch protection applies to (§284).
    expect(subtitle(repository())).toBe("default branch main");
    expect(subtitle(repository({ default_branch: "trunk" }))).toBe("default branch trunk");
  });

  it("shows a description when there is one and invents nothing when there is not", () => {
    expect(subtitle(repository({ description: "Order pipeline" }))).toBe(
      "Order pipeline · default branch main",
    );
  });
});
