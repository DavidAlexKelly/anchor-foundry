"use client";

/**
 * The first-run checklist (ROADMAP section 7 item 3).
 *
 * A freshly provisioned deployment hands somebody a blank project with six
 * pillars and no hint which door to open first. This is the hint - and it is
 * *derived*, not stored: every item is true when the thing it names exists, so
 * nothing has to be ticked off, nothing can go stale, and a project set up by
 * somebody else shows the right state to the next person who opens it.
 *
 * It disappears once the project has a canvas app, which is the point at which
 * somebody has been all the way through the pipeline and does not need this
 * any more. Nothing to dismiss and nothing that remembers a dismissal: the
 * project's own contents are the state.
 */

import Link from "next/link";
import type { ResourceCounts } from "@/lib/types";

interface Step {
  label: string;
  done: boolean;
  href: string;
  hint: string;
}

/**
 * `objectSources` rather than `counts.objects`, and the difference matters:
 * **object types are workspace-wide** (the counts query flags this), so a
 * brand-new project in an established workspace would open with "give it a
 * shape" already ticked by somebody else's ontology. What belongs to *this*
 * project is the source that maps one of its datasets onto a type — found by
 * the checklist showing a green tick in an empty project, which is exactly
 * the sort of quiet wrongness this codebase refuses everywhere else.
 */
export function firstRunSteps(counts: ResourceCounts, objectSources: number): Step[] {
  return [
    {
      label: "Bring some data in",
      done: counts.datasets > 0,
      href: "datasets",
      hint: "Upload a CSV, or connect a database under Connections.",
    },
    {
      label: "Transform it",
      done: counts.models > 0,
      href: "models",
      hint: "A model is SQL over your datasets. Its output is another dataset.",
    },
    {
      label: "Give it a shape",
      done: objectSources > 0,
      href: "objects",
      hint: "An object type turns rows into things — sites, orders, customers.",
    },
    {
      label: "Build something on it",
      done: counts.canvas > 0,
      href: "canvas",
      hint: "A canvas app: tables, charts and maps over the data above.",
    },
  ];
}

export function FirstRunChecklist({
  counts,
  objectSources,
  workspaceSlug,
  projectSlug,
}: {
  counts: ResourceCounts;
  objectSources: number;
  workspaceSlug: string;
  projectSlug: string;
}) {
  const steps = firstRunSteps(counts, objectSources);
  // Done means done: an app on the canvas is somebody who has been through the
  // whole pipeline, and a checklist that stays after that is clutter.
  if (steps.every((s) => s.done)) return null;
  const complete = steps.filter((s) => s.done).length;

  return (
    <section className="first-run">
      <div className="first-run-head">
        <h2>Getting started</h2>
        <span className="count">
          {complete} of {steps.length}
        </span>
      </div>
      <p className="sub">
        There&apos;s no forced order — this is just the shortest path from an empty
        project to something worth showing somebody.
      </p>
      <ol>
        {steps.map((step) => (
          <li key={step.href} className={step.done ? "done" : ""}>
            <Link href={`/${workspaceSlug}/${projectSlug}/${step.href}`}>
              <strong>{step.label}</strong>
              <span>{step.hint}</span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
