"use client";

/** p.95's lookup formatters, where a value is shown (§624; `object-link-types`
 * p.95).
 *
 * > "Foundry ID formatting: Display a Foundry ID as a user's first and last
 * > name or group name. Resource RID formatting: Display a Foundry resource ID
 * > (RID) as an icon and resource name, with a clickable link that routes to
 * > that resource." (p.95)
 *
 * **The id stays reachable**, in the tooltip, as `PropertyValue` keeps a
 * formatted number's raw value: the name is easier to read and the id is what
 * a filter takes. **An id nothing names is shown as itself** rather than as a
 * blank, which would read as an empty value. The people and groups are read
 * once and shared by every cell; a resource is read per id, and only when the
 * value could be one. */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { CSSProperties } from "react";
import { api, resources as resourceApi } from "@/lib/api";
import { directoryName, looksLikeResourceId } from "@/lib/value-format";

export function LookupValue({ kind, value, style }: {
  kind: "user" | "resource";
  value: string;
  style?: CSSProperties;
}) {
  return kind === "user"
    ? <PersonOrGroup id={value} style={style} />
    : <ResourceName id={value} style={style} />;
}

function PersonOrGroup({ id, style }: { id: string; style?: CSSProperties }) {
  const people = useQuery({ queryKey: ["org-members"], queryFn: () => api.orgMembers() });
  const groups = useQuery({ queryKey: ["org-groups"], queryFn: () => api.orgGroups() });
  const name = people.data && groups.data ? directoryName(id, people.data, groups.data) : null;
  return (
    <span title={id} style={style} data-testid="lookup-person">
      {name ?? id}
    </span>
  );
}

function ResourceName({ id, style }: { id: string; style?: CSSProperties }) {
  const askable = looksLikeResourceId(id);
  const resource = useQuery({
    queryKey: ["resource", id.trim()],
    queryFn: () => resourceApi.resolve(id.trim()),
    enabled: askable,
    retry: false,
  });
  if (!resource.data) {
    return <span title={id} style={style} data-testid="lookup-resource">{id}</span>;
  }
  return (
    <Link href={`/r/${resource.data.id}`} title={id} style={style} data-testid="lookup-resource">
      <span className="slug">{resource.data.kind.replace("_", " ")}</span>{" "}
      {resource.data.name}
    </Link>
  );
}
