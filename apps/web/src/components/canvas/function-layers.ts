/**
 * Chart XY's function-backed layers (Workshop p.280, p.284; §771).
 *
 * > "The Function aggregation option allows a function that returns a 2D
 * > Aggregation or 3D Aggregation to be used as input." (p.280)
 *
 * A layer names a function, a version (or the newest), and where each of its
 * parameters comes from. The function's buckets are the layer's categories,
 * met with the chart's own by their labels as any layer's are (§625). A 3D
 * aggregation's segments stack the layer's bars, as p.282's Segment by does.
 */

import type { ChartPoint } from "./charts";
import type { Segmented } from "./chart-segments";
import { inputsOf, unsetRequired, type FunctionInputs } from "./function-inputs";
import type { FunctionDetail, FunctionResult } from "@/lib/types";

export interface FunctionLayer {
  function_id: string;
  /** Null calls the newest (`functions` p.49). */
  version: string | null;
  inputs: FunctionInputs;
}

/** A saved layer's function, or null when it reads an object set. */
export function functionLayerOf(raw: unknown): FunctionLayer | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const it = raw as Record<string, unknown>;
  if (typeof it.function_id !== "string") return null;
  return {
    function_id: it.function_id,
    version: typeof it.version === "string" && it.version ? it.version : null,
    inputs: inputsOf(it.inputs),
  };
}

/** A 2D aggregation's buckets as a layer's points. */
export function pointsFrom(result: FunctionResult | undefined): ChartPoint[] | null {
  if (!result || result.kind !== "aggregation" || result.dimensions !== 2) return null;
  return (result.buckets ?? []).map((b) => ({ label: b.key, value: Number(b.value) }));
}

/** A 3D aggregation's buckets as a layer's segmented grid: categories in the
 * order their first bucket came, segments likewise, and a zero where the
 * function gave no bucket for a pair. */
export function gridFrom(result: FunctionResult | undefined): Segmented | null {
  if (!result || result.kind !== "aggregation" || result.dimensions !== 3) return null;
  const buckets = result.buckets ?? [];
  const categories = [...new Set(buckets.map((b) => b.key))];
  const segments = [...new Set(buckets.map((b) => b.segment ?? ""))];
  const values = categories.map(() => segments.map(() => 0));
  for (const b of buckets) {
    values[categories.indexOf(b.key)]![segments.indexOf(b.segment ?? "")] = Number(b.value);
  }
  return { categories, segments, values };
}

/** Why the layer cannot be drawn, or null: what the panel says under it. */
export function layerProblem(layer: FunctionLayer, fn: FunctionDetail | undefined): string | null {
  if (!layer.function_id) return "Choose the function this layer draws.";
  if (!fn) return "The function this layer draws does not exist.";
  const version = layer.version ? fn.versions.find((v) => v.version === layer.version)
    : fn.versions[0];
  if (!version) return `${fn.api_name} has no version ${layer.version}.`;
  if (version.output.kind !== "aggregation") {
    return `${fn.api_name} does not return an aggregation (Workshop p.284).`;
  }
  return unsetRequired(version, layer.inputs);
}
