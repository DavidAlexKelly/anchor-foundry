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
import { useState } from "react";
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
    sort?: string;
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
    queryKey: ["canvas-object-set", key, pageSize, offset, sort ?? null],
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
