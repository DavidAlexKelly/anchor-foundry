"use client";

/** Reading a page of an object set, and announcing that one was chosen.
 *
 * Both halves were inside `CanvasObjectTable` until the Card List (roadmap
 * 1.5) needed the same two things, and both are places a second copy would
 * drift rather than merely repeat:
 *
 *   * **Paging resets when the set changes.** Narrowing a filter while on page
 *     3 otherwise leaves a viewer looking at an empty widget that has rows —
 *     a bug that reads as "the filter broke", and one that a second
 *     implementation would have to rediscover.
 *   * **A selected object is announced twice, deliberately**: flattened for
 *     `{{...}}` in an effect's value, and whole for a `single_object`
 *     variable, which needs to know which field is the key and what the id is,
 *     since the id is what the write APIs take. The `object_type_id` comes
 *     from the *widget's* set rather than from the row, because a row does not
 *     carry it — get that wrong and a `run_action` acts on the wrong type.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { objects as objApi } from "@/lib/api";
import type { ObjectInstance } from "@/lib/types";

export interface SetPage {
  rows: ObjectInstance[] | undefined;
  total: number | undefined;
  /** The set's own type id, read from the resolved definition. */
  typeId: string | null;
  /** What narrowed the set, so a widget can say so rather than showing a
   *  filtered count with no sign it was filtered. */
  filters: { property: string; value: unknown }[];
  offset: number;
  setOffset: (next: number) => void;
  isPending: boolean;
  isError: boolean;
  /** True until the variable graph has resolved. Distinct from `isPending`:
   *  nothing has been asked for yet, so "0 objects" is not the answer. */
  unresolved: boolean;
}

export function useSetPage(
  workspaceId: string,
  definition: unknown,
  { pageSize, sort, variablesPending }: {
    pageSize: number;
    sort?: string | string[];
    variablesPending: boolean;
  },
): SetPage {
  const [offset, setOffset] = useState(0);
  const key = JSON.stringify(definition ?? null);
  const [lastKey, setLastKey] = useState(key);
  if (key !== lastKey) {
    setLastKey(key);
    setOffset(0);
  }

  const page = useQuery({
    // The sort is part of the key, and a **list** has to be serialised into
    // it: two different orderings are two different pages, and an array
    // compares by identity in a query key, so a fresh one each render would
    // refetch every time.
    queryKey: ["canvas-object-set", key, pageSize, offset,
               Array.isArray(sort) ? sort.join(",") : sort ?? null],
    queryFn: () =>
      objApi.evaluateObjectSet(workspaceId, definition, { limit: pageSize, offset, sort }),
    // Not until the definition has resolved: asking the server to evaluate
    // `undefined` would render "0 objects", which is an answer this does not
    // have yet.
    enabled: !!definition,
    // The previous page stays on screen while the next loads, rather than the
    // widget emptying and jumping — the rows are about to be replaced, not gone.
    placeholderData: (previous) => previous,
  });

  const resolved = definition as
    | { object_type_id?: string; filters?: { property: string; value: unknown }[] }
    | undefined;
  return {
    rows: page.data?.instances,
    total: page.data?.total,
    typeId: resolved?.object_type_id ?? null,
    filters: resolved?.filters ?? [],
    offset,
    setOffset,
    isPending: page.isPending,
    isError: page.isError,
    unresolved: variablesPending || (!definition && !page.isError),
  };
}

/** How a widget describes the object somebody picked. */
export function selectionOf(instance: ObjectInstance, typeId: string | null) {
  return {
    payload: { primary_key: instance.primary_key, ...instance.properties },
    object: {
      id: instance.id,
      object_type_id: typeId ?? undefined,
      primary_key: instance.primary_key,
      properties: instance.properties,
    },
  };
}

/** "12 Sites where region = north" — the count, and what narrowed it. */
export function describeSet(
  total: number,
  typeName: string | undefined,
  filters: { property: string; value: unknown }[],
): string {
  const noun = `${typeName ?? "object"}${total === 1 ? "" : "s"}`;
  const where = filters.length
    ? ` where ${filters.map((f) => `${f.property} = ${String(f.value)}`).join(" and ")}`
    : "";
  return `${total.toLocaleString()} ${noun}${where}`;
}

/** Whether an element is actually on screen.
 *
 * **p.224's auto-selection "only triggers when the widget is visible"**, and a
 * collapsed section keeps its children *mounted* — deliberately, so a table
 * inside one does not refetch every time somebody folds it away. So a table in
 * a folded section is running, and something has to tell it that nobody can
 * see it.
 *
 * An `IntersectionObserver` rather than a walk up the Craft tree looking for a
 * collapsed ancestor: the question is "is this on screen", and the tree answers
 * a narrower one. A section is only the case p.224 happens to name — a hidden
 * tab and a closed overlay hide a widget just as completely, and each would
 * need its own special case in a tree walk while the observer already covers
 * them. It also reports *changes*, which is what "until the section is
 * expanded" asks for.
 */
export function useOnScreen(): [(node: HTMLElement | null) => void, boolean] {
  const [node, setNode] = useState<HTMLElement | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!node) return;
    // Guarded because the observer does not exist in every runtime a component
    // is rendered in. Absent means *visible*: a widget that never auto-selects
    // is a worse failure than one that does so early, and it would only ever
    // show up somewhere with no layout to hide it in anyway.
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => setVisible(entries.some((e) => e.isIntersecting)),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);

  return [setNode, visible];
}
