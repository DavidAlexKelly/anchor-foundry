/**
 * How long something took, in words (§358).
 *
 * **One formatter, because there were two.** `action-metrics` wrote this for
 * an action's P95 (`action-types` p.164) and §358 wrote a second one for a
 * model run's duration, and they
 * disagreed on whole minutes: two minutes rendered as "2m" on an action's
 * metrics and "2m 0s" on a model's runs. Which one a reader saw depended on
 * which page they were on, which is §298's finding in a different corner of
 * the repo — there it was two wordings for one refusal, here two spellings for
 * one number.
 *
 * Measured rather than assumed, before it shipped: the two were run over the
 * same elapsed times and compared, and `test_both_formatters_agree` in
 * `run-logs.test.ts` is that comparison kept.
 *
 * Seconds under a minute, and minutes above — something taking "212.4s" is a
 * duration the reader has to do arithmetic on to know it is nearly four
 * minutes.
 */
export function durationText(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  // "2m", not "2m 0s": the seconds are there to stop a reader doing
  // arithmetic, and there is none to do when they are zero.
  return rest === 0 ? `${mins}m` : `${mins}m ${rest}s`;
}
