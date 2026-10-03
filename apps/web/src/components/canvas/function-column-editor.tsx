"use client";

/**
 * One function-backed column, configured (Workshop p.221; §770).
 *
 * > "select the 'fx' Functions icon and then choose the desired function …
 * > Next, confirm the function version and then configure the necessary
 * > inputs for the function." (p.221)
 *
 * Function, version, which parameter receives the table's objects (p.221's
 * runtime input), which of the map's fields the column shows, and every other
 * parameter from a module variable or a typed value. What would stop the
 * column drawing is said under it, from `columnProblem`.
 */

import { useQuery } from "@tanstack/react-query";
import { objects as objApi } from "@/lib/api";
import { useCanvasEnv, useCanvasVariables } from "./context";
import type { FunctionColumn } from "./derived-columns";
import { columnProblem, objectParameters, versionOf } from "./function-columns";

export function FunctionColumnEditor({ index, objectTypeId, column, onChange }: {
  index: number;
  objectTypeId: string;
  column: FunctionColumn;
  onChange: (next: FunctionColumn) => void;
}) {
  const { workspaceId } = useCanvasEnv();
  const { declared } = useCanvasVariables();
  const n = index + 1;
  const list = useQuery({
    queryKey: ["functions", workspaceId],
    queryFn: () => objApi.listFunctions(workspaceId),
  });
  const detail = useQuery({
    queryKey: ["function", column.function_id],
    queryFn: () => objApi.getFunction(workspaceId, column.function_id),
    enabled: !!column.function_id,
  });
  const version = versionOf(detail.data, column.version);
  const objects = objectParameters(version, objectTypeId);
  const others = (version?.parameters ?? []).filter((p) => p.api_name !== column.objects_parameter);
  const issue = column.function_id
    ? (detail.data || detail.isError ? columnProblem(column, detail.data, objectTypeId) : null)
    : "Choose the function this column calls.";

  return (
    <div className="row-actions" style={{ gap: 6, flexWrap: "wrap" }}>
      <select
        aria-label={`Derived property ${n} function`}
        value={column.function_id}
        onChange={(e) => onChange({
          ...column, function_id: e.target.value, version: null, objects_parameter: "",
          field: "", inputs: {},
        })}
      >
        <option value="">Choose a function…</option>
        {(list.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.api_name}</option>)}
      </select>
      {detail.data && (
        <select
          aria-label={`Derived property ${n} version`}
          value={column.version ?? ""}
          onChange={(e) => onChange({ ...column, version: e.target.value || null })}
        >
          <option value="">Newest ({detail.data.versions[0]?.version})</option>
          {detail.data.versions.map((v) => <option key={v.id} value={v.version}>{v.version}</option>)}
        </select>
      )}
      {version && (
        <select
          aria-label={`Derived property ${n} objects`}
          value={column.objects_parameter}
          onChange={(e) => onChange({ ...column, objects_parameter: e.target.value })}
        >
          <option value="">The table&apos;s objects go to…</option>
          {objects.map((p) => <option key={p.api_name} value={p.api_name}>{p.api_name}</option>)}
        </select>
      )}
      {version && (
        <input
          aria-label={`Derived property ${n} field`}
          placeholder="field (first if blank)"
          value={column.field}
          onChange={(e) => onChange({ ...column, field: e.target.value.trim() })}
        />
      )}
      {others.map((p) => {
        const source = column.inputs[p.api_name];
        const variable = source && "variable" in source ? source.variable : "";
        const typed = source && "value" in source ? String(source.value ?? "") : "";
        const setSource = (next: FunctionColumn["inputs"][string] | null) => {
          const inputs = { ...column.inputs };
          if (next) inputs[p.api_name] = next;
          else delete inputs[p.api_name];
          onChange({ ...column, inputs });
        };
        return (
          <span key={p.api_name} className="row-actions" style={{ gap: 4 }}>
            <select
              aria-label={`Derived property ${n} ${p.api_name} from`}
              value={variable}
              onChange={(e) => setSource(e.target.value ? { variable: e.target.value } : null)}
            >
              <option value="">{p.api_name}: a value</option>
              {Object.values(declared).map((v) => (
                <option key={v.id} value={v.id}>{p.api_name}: {v.label}</option>
              ))}
            </select>
            {!variable && (
              <input
                aria-label={`Derived property ${n} ${p.api_name} value`}
                placeholder={p.data_type}
                value={typed}
                onChange={(e) => setSource(e.target.value === "" ? null : {
                  value: p.data_type === "integer" || p.data_type === "float"
                    ? Number(e.target.value) : e.target.value,
                })}
              />
            )}
          </span>
        );
      })}
      {issue && (
        <span className="field-hint" data-testid={`derived-problem-${n}`}>{issue}</span>
      )}
    </div>
  );
}
