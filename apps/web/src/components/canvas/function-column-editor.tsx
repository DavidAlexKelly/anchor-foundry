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
import type { FunctionInputs } from "./function-inputs";
import type { FunctionParameter } from "@/lib/types";
import { columnProblem, objectParameters, versionOf } from "./function-columns";
import { layerProblem, type FunctionLayer } from "./function-layers";
import { functionVariableProblem, type FunctionCall } from "./function-variables";
import type { WorkshopVariableKind } from "@/lib/types";

export function FunctionColumnEditor({ index, objectTypeId, column, onChange }: {
  index: number;
  objectTypeId: string;
  column: FunctionColumn;
  onChange: (next: FunctionColumn) => void;
}) {
  const { workspaceId } = useCanvasEnv();
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
      <FunctionInputsFields
        label={`Derived property ${n}`}
        parameters={others}
        inputs={column.inputs}
        onChange={(inputs) => onChange({ ...column, inputs })}
      />
      {issue && (
        <span className="field-hint" data-testid={`derived-problem-${n}`}>{issue}</span>
      )}
    </div>
  );
}

/** Where each parameter's value comes from: a module variable, or a value
 * typed here (§770, §771). `label` prefixes each control's accessible name. */
export function FunctionInputsFields({ label, parameters, inputs, onChange, choices }: {
  label: string;
  parameters: FunctionParameter[];
  inputs: FunctionInputs;
  onChange: (next: FunctionInputs) => void;
  /** The variables offered, when not the module's declared ones: the
   * Variables panel's own unsaved list, less the variable being edited. */
  choices?: { id: string; label: string }[];
}) {
  const { declared } = useCanvasVariables();
  const offered = choices ?? Object.values(declared);
  return (
    <>
      {parameters.map((p) => {
        const source = inputs[p.api_name];
        const variable = source && "variable" in source ? source.variable : "";
        const typed = source && "value" in source ? String(source.value ?? "") : "";
        const setSource = (next: FunctionInputs[string] | null) => {
          const all = { ...inputs };
          if (next) all[p.api_name] = next;
          else delete all[p.api_name];
          onChange(all);
        };
        return (
          <span key={p.api_name} className="row-actions" style={{ gap: 4 }}>
            <select
              aria-label={`${label} ${p.api_name} from`}
              value={variable}
              onChange={(e) => setSource(e.target.value ? { variable: e.target.value } : null)}
            >
              <option value="">{p.api_name}: a value</option>
              {offered.map((v) => (
                <option key={v.id} value={v.id}>{p.api_name}: {v.label}</option>
              ))}
            </select>
            {!variable && (
              <input
                aria-label={`${label} ${p.api_name} value`}
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
    </>
  );
}

/**
 * A Chart XY layer's function (Workshop p.280, p.284; §771): which function,
 * which version, and where its parameters come from. What would stop the
 * layer drawing is said under it, from `layerProblem`.
 */
export function FunctionLayerEditor({ label, layer, onChange }: {
  label: string;
  layer: FunctionLayer;
  onChange: (next: FunctionLayer) => void;
}) {
  const { workspaceId } = useCanvasEnv();
  const list = useQuery({
    queryKey: ["functions", workspaceId],
    queryFn: () => objApi.listFunctions(workspaceId),
  });
  const detail = useQuery({
    queryKey: ["function", layer.function_id],
    queryFn: () => objApi.getFunction(workspaceId, layer.function_id),
    enabled: !!layer.function_id,
  });
  const version = versionOf(detail.data, layer.version);
  const issue = !layer.function_id || detail.data || detail.isError
    ? layerProblem(layer, detail.data) : null;
  return (
    <>
      <select
        aria-label={`${label} function`}
        value={layer.function_id}
        onChange={(e) => onChange({ function_id: e.target.value, version: null, inputs: {} })}
      >
        <option value="">Choose a function…</option>
        {(list.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.api_name}</option>)}
      </select>
      {detail.data && (
        <select
          aria-label={`${label} version`}
          value={layer.version ?? ""}
          onChange={(e) => onChange({ ...layer, version: e.target.value || null })}
        >
          <option value="">Newest ({detail.data.versions[0]?.version})</option>
          {detail.data.versions.map((v) => <option key={v.id} value={v.version}>{v.version}</option>)}
        </select>
      )}
      <FunctionInputsFields
        label={label}
        parameters={version?.parameters ?? []}
        inputs={layer.inputs}
        onChange={(inputs) => onChange({ ...layer, inputs })}
      />
      {issue && <span className="field-hint" data-testid="chart-series-problem">{issue}</span>}
    </>
  );
}

/**
 * A function-backed variable (Workshop p.73; §772): which function, which
 * version, and each parameter from another variable or a fixed value. What
 * would stop it resolving is said under it, from `functionVariableProblem`.
 * The panel is outside the module's variable context, so it passes its own
 * workspace and the variables it is editing.
 */
export function FunctionVariableEditor({ workspaceId, kind, call, choices, readOnly, onChange }: {
  workspaceId: string;
  kind: WorkshopVariableKind;
  call: FunctionCall;
  choices: { id: string; label: string }[];
  readOnly: boolean;
  onChange: (next: FunctionCall) => void;
}) {
  const list = useQuery({
    queryKey: ["functions", workspaceId],
    queryFn: () => objApi.listFunctions(workspaceId),
  });
  const detail = useQuery({
    queryKey: ["function", call.function_id],
    queryFn: () => objApi.getFunction(workspaceId, call.function_id),
    enabled: !!call.function_id,
  });
  const version = versionOf(detail.data, call.version);
  const issue = !call.function_id || detail.data || detail.isError
    ? functionVariableProblem(kind, call, detail.data) : null;
  return (
    <fieldset className="vars-function" disabled={readOnly}>
      <label>
        Function
        <select
          data-testid="variable-function"
          value={call.function_id}
          onChange={(e) => onChange({ function_id: e.target.value, version: null, inputs: {} })}
        >
          <option value="">Choose a function…</option>
          {(list.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.api_name}</option>)}
        </select>
      </label>
      {detail.data && (
        <label>
          Version
          <select
            data-testid="variable-function-version"
            value={call.version ?? ""}
            onChange={(e) => onChange({ ...call, version: e.target.value || null })}
          >
            <option value="">Newest ({detail.data.versions[0]?.version})</option>
            {detail.data.versions.map((v) => (
              <option key={v.id} value={v.version}>{v.version}</option>
            ))}
          </select>
        </label>
      )}
      <FunctionInputsFields
        label="Function"
        parameters={version?.parameters ?? []}
        inputs={call.inputs}
        choices={choices}
        onChange={(inputs) => onChange({ ...call, inputs })}
      />
      {issue && <span className="field-hint" data-testid="variable-function-problem">{issue}</span>}
    </fieldset>
  );
}
