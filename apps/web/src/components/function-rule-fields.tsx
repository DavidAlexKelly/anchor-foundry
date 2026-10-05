"use client";

/**
 * An action's Function rule, configured (`action-types` p.22, p.78-82; §773).
 *
 * > "add a single rule of type Function. Search for the function you
 * > published … and pick the latest version. Configure the inputs to match up
 * > to the action parameters" (p.78)
 *
 * > "When selecting the function, all inputs of the function will
 * > automatically be created as parameters" (p.79)
 *
 * Choosing a function or a version sets each input to its default source
 * (`defaultInputs`) and adds the action parameters those read
 * (`parametersToCreate`), which the author may then change. What would stop
 * the rule running is said under it, from `functionRuleProblem`.
 */

import { useQuery } from "@tanstack/react-query";
import { objects as objApi } from "@/lib/api";
import {
  batchOf, canAutoUpgrade, defaultInputs, functionRuleProblem, parametersToCreate,
  resolveVersion, slotsOf,
  type CreatedParameter, type FunctionRuleConfig, type FunctionRuleInput,
} from "@/lib/function-rules";

export function FunctionRuleFields({
  workspaceId, index, subjectTypeId, parameters, config, onChange, onCreateParameters,
}: {
  workspaceId: string;
  index: number;
  subjectTypeId: string | null;
  parameters: { api_name: string; display_name?: string }[];
  config: FunctionRuleConfig;
  onChange: (next: FunctionRuleConfig) => void;
  onCreateParameters: (created: CreatedParameter[]) => void;
}) {
  const list = useQuery({
    queryKey: ["functions", workspaceId],
    queryFn: () => objApi.listFunctions(workspaceId),
  });
  const detail = useQuery({
    queryKey: ["function", config.function_id],
    queryFn: () => objApi.getFunction(workspaceId, config.function_id),
    enabled: !!config.function_id,
  });
  const pinned = detail.data?.versions.find((v) => v.version === config.version);
  const runs = resolveVersion(detail.data, config);
  const names = parameters.map((p) => p.api_name);
  const issue = !config.function_id || detail.data || detail.isError
    ? functionRuleProblem(config, detail.data, names, subjectTypeId) : null;

  /** p.79: the version's inputs, each from its default, and the parameters
   * they read created. */
  const choose = (functionId: string, version: string) => {
    const chosen = functionId === config.function_id
      ? detail.data?.versions.find((v) => v.version === version) : undefined;
    const inputs = chosen ? defaultInputs(chosen, subjectTypeId) : {};
    if (chosen) onCreateParameters(parametersToCreate(chosen, inputs, names));
    onChange({ function_id: functionId, version, auto_upgrade: false,
               batched: !!batchOf(chosen), inputs });
  };

  const setInput = (name: string, source: FunctionRuleInput | null) => {
    const inputs = { ...config.inputs };
    if (source) inputs[name] = source;
    else delete inputs[name];
    onChange({ ...config, inputs });
  };

  const n = index + 1;
  return (
    <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
      <label className="field">
        <span className="field-label">Function</span>
        <select
          aria-label={`Rule ${n} function`}
          value={config.function_id}
          onChange={(e) => choose(e.target.value, "")}
        >
          <option value="">Choose a function…</option>
          {(list.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.api_name}</option>)}
        </select>
      </label>
      {detail.data && (
        <label className="field">
          <span className="field-label">Version</span>
          <select
            aria-label={`Rule ${n} version`}
            value={config.version}
            onChange={(e) => choose(config.function_id, e.target.value)}
          >
            <option value="">Choose a version…</option>
            {detail.data.versions.map((v) => (
              <option key={v.id} value={v.version}>{v.version}</option>
            ))}
          </select>
        </label>
      )}
      {pinned && (
        <label className="check" title="action-types p.81-82">
          <input
            type="checkbox"
            aria-label={`Rule ${n} auto upgrade`}
            checked={config.auto_upgrade}
            disabled={!canAutoUpgrade(config.version)}
            onChange={(e) => onChange({ ...config, auto_upgrade: e.target.checked })}
          />
          Auto upgrade
          {config.auto_upgrade && runs && runs.version !== config.version && (
            <span className="field-hint" data-testid={`rule-${n}-runs`}>
              {" "}— runs {runs.version}
            </span>
          )}
        </label>
      )}
      {pinned && config.batched && (
        <span className="field-hint" data-testid={`rule-${n}-batched`}>
          Batched: one call for a whole batch of submissions (action-types p.85)
        </span>
      )}
      {(pinned ? slotsOf(pinned) : []).map((p) => {
        const source = config.inputs[p.api_name];
        const choice = !source ? "" : "subject" in source ? "$subject"
          : "parameter" in source ? `param:${source.parameter}` : "$value";
        return (
          <span key={p.api_name} className="row" style={{ gap: 4, alignItems: "flex-end" }}>
            <label className="field">
              <span className="field-label">{p.api_name}</span>
              <select
                aria-label={`Rule ${n} ${p.api_name} from`}
                value={choice}
                onChange={(e) => {
                  const v = e.target.value;
                  setInput(p.api_name, v === "" ? null : v === "$subject" ? { subject: true }
                    : v === "$value" ? { value: "" } : { parameter: v.slice("param:".length) });
                }}
              >
                <option value="">{p.required ? "Choose…" : "Nothing"}</option>
                {p.data_type === "object" && p.object_type_id === subjectTypeId && (
                  <option value="$subject">This object</option>
                )}
                {parameters.map((a) => (
                  <option key={a.api_name} value={`param:${a.api_name}`}>
                    {a.display_name || a.api_name}
                  </option>
                ))}
                <option value="$value">A value</option>
              </select>
            </label>
            {source && "value" in source && (
              <input
                aria-label={`Rule ${n} ${p.api_name} value`}
                placeholder={p.data_type}
                value={String(source.value ?? "")}
                onChange={(e) => setInput(p.api_name, {
                  value: (p.data_type === "integer" || p.data_type === "float")
                    && e.target.value !== "" && Number.isFinite(Number(e.target.value))
                    ? Number(e.target.value) : e.target.value,
                })}
              />
            )}
          </span>
        );
      })}
      {issue && (
        <p className="field-hint" data-testid={`rule-${n}-problem`}
           style={{ color: "var(--danger)", flexBasis: "100%" }}>
          {issue}
        </p>
      )}
    </div>
  );
}
