/**
 * Diagnose on a connection (§646; `data-connection` TOC §6, *Where to start*).
 *
 * The server runs the list (`services/diagnose.py`); this is how its answer
 * reads: each step by the question it asks, and one line saying where it
 * stopped and what to do about it.
 *
 * Pure.
 */

import type { DiagnoseResult, DiagnoseStep } from "./types";

/** Each step by the question it asks, in TOC §6's words where it has them. */
export const STEP_LABELS: Record<string, string> = {
  destination: "Where it connects",
  egress: "Egress policies",
  dns: "Name resolves",
  tcp: "Port accepts a connection",
  tls: "TLS",
  credentials: "Credentials",
};

export function stepLabel(step: DiagnoseStep): string {
  return STEP_LABELS[step.name] ?? step.name;
}

/** The line above the steps: every step passed, or the one that failed and
 * what to do about it. */
export function summary(result: DiagnoseResult): string {
  const failed = result.steps.find((s) => s.status === "failed");
  if (!failed) return "Every step passed.";
  return `Stopped at ${stepLabel(failed).toLowerCase()}: ${failed.hint ?? failed.detail}`;
}
