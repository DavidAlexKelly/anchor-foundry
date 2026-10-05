"use client";

/**
 * A function-backed export, configured (Workshop p.489-490; §775): which
 * function, which version, its inputs, the file type and the file's name.
 * What would stop it downloading is said under it.
 */

import { useQuery } from "@tanstack/react-query";
import { objects as objApi } from "@/lib/api";
import { EXPORT_FILE_TYPES, isExportFileType } from "@/lib/function-export";
import type { WorkshopVariable } from "@/lib/types";
import { FunctionInputsFields } from "./function-column-editor";
import { versionOf } from "./function-columns";
import { inputsOf, unsetRequired } from "./function-inputs";

export function FunctionExportEditor({ config, variables, workspaceId, readOnly, onChange }: {
  config: Record<string, unknown>;
  variables: WorkshopVariable[];
  workspaceId?: string;
  readOnly: boolean;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const functionId = typeof config.function_id === "string" ? config.function_id : "";
  const version = typeof config.version === "string" && config.version ? config.version : null;
  const inputs = inputsOf(config.inputs);
  const list = useQuery({
    queryKey: ["functions", workspaceId],
    queryFn: () => objApi.listFunctions(workspaceId!),
    enabled: !!workspaceId,
  });
  const detail = useQuery({
    queryKey: ["function", functionId],
    queryFn: () => objApi.getFunction(workspaceId!, functionId),
    enabled: !!functionId && !!workspaceId,
  });
  const chosen = versionOf(detail.data, version);
  const output = chosen?.output;
  const issue = !functionId ? "Choose the function whose output is exported."
    : detail.data && !chosen ? `${detail.data.api_name} has no version ${version}.`
    : output && !(output.kind === "value" && output.data_type === "string")
      ? `${detail.data!.api_name} must return a string to export (Workshop p.490).`
    : chosen ? unsetRequired(chosen, inputs)
    : null;
  return (
    <fieldset className="vars-function" disabled={readOnly}>
      <label className="field">
        <span className="field-label">Function</span>
        <select
          aria-label="Export function"
          value={functionId}
          onChange={(e) => onChange({ ...config, function_id: e.target.value || undefined,
                                      version: null, inputs: {} })}
        >
          <option value="">Choose a function…</option>
          {(list.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.api_name}</option>)}
        </select>
      </label>
      {detail.data && (
        <label className="field">
          <span className="field-label">Version</span>
          <select
            aria-label="Export function version"
            value={version ?? ""}
            onChange={(e) => onChange({ ...config, version: e.target.value || null })}
          >
            <option value="">Newest ({detail.data.versions[0]?.version})</option>
            {detail.data.versions.map((v) => (
              <option key={v.id} value={v.version}>{v.version}</option>
            ))}
          </select>
        </label>
      )}
      <FunctionInputsFields
        label="Export"
        parameters={chosen?.parameters ?? []}
        inputs={inputs}
        choices={variables}
        onChange={(next) => onChange({ ...config, inputs: next })}
      />
      <label className="field">
        <span className="field-label">File type</span>
        <select
          aria-label="Export file type"
          value={isExportFileType(config.file_type) ? config.file_type : "csv"}
          onChange={(e) => onChange({ ...config, file_type: e.target.value })}
        >
          {EXPORT_FILE_TYPES.map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
        </select>
      </label>
      <label className="field">
        <span className="field-label">File name</span>
        <input
          aria-label="Export file name"
          placeholder="export"
          value={typeof config.file_name === "string" ? config.file_name : ""}
          onChange={(e) => onChange({ ...config, file_name: e.target.value || undefined })}
        />
        <span className="field-hint">
          A CSV, TXT, JSON or XML file is the string the function returns; a PDF, DOCX or
          XLSX file is its bytes as base64 (p.490).
        </span>
      </label>
      {issue && <p className="field-hint" data-testid="effect-export-function-problem">{issue}</p>}
    </fieldset>
  );
}
