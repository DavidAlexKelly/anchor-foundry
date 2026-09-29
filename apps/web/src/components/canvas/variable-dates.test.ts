/** §565: p.140-141's date and time operations, as the panel offers them. */
import { describe, expect, it } from "vitest";

import { DATE_ARITY, dateSlotLabels, isDateMath, takesDirection, unitsFor } from "./variable-dates";

describe("the panel's date and time operations", () => {
  it("knows each of p.140-141's", () => {
    expect(Object.keys(DATE_ARITY)).toHaveLength(15);
    expect(DATE_ARITY.current_date).toBe(0);
    expect(isDateMath("time_is_before")).toBe(true);
    expect(isDateMath("add")).toBe(false);
  });

  it("offers each its own units", () => {
    expect(unitsFor("relative_date")).toEqual(["days", "weeks", "months", "years"]);
    expect(unitsFor("between_dates")).toEqual(["days", "weeks", "months", "years"]);
    expect(unitsFor("relative_time")).toContain("seconds");
    expect(unitsFor("between_times")).toContain("seconds");
    expect(unitsFor("date_is_before")).toBeNull();
  });

  it("offers add or subtract where a date or time moves", () => {
    expect(takesDirection("relative_date")).toBe(true);
    expect(takesDirection("relative_time")).toBe(true);
    expect(takesDirection("between_dates")).toBe(false);
  });

  it("names the inputs", () => {
    expect(dateSlotLabels("relative_date")).toEqual(["Date", "By"]);
    expect(dateSlotLabels("relative_time")).toEqual(["Time", "By"]);
    expect(dateSlotLabels("between_times")).toEqual(["From", "To"]);
    expect(dateSlotLabels("date_is_after")).toEqual(["First", "Second"]);
  });
});
