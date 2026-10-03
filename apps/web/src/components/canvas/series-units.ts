/** p.394's unit conversion on a Time Series Analysis axis (§733).
 *
 * > "Unit: The unit of the Y-axis. Allows unit conversion (for example,
 * > meters to kilometers) or custom label overrides." (`workshop` p.394)
 *
 * **The axis's Unit names the data's unit**, as it did when it was only a
 * label (§656): a time series property records none here, so the reader who
 * knows the readings are metres says so. A **Display as** unit of the same
 * kind then converts the axis's readings, and the label becomes it. A Unit
 * this table does not know is a custom label, p.394's other half, and
 * nothing converts.
 *
 * One table of the units people chart sensors in, each with its factor to
 * its kind's base unit - and temperature, whose scales are offset as well as
 * stretched, as the one kind that needs an offset.
 */

export type UnitKind =
  | "length" | "mass" | "time" | "speed" | "volume" | "pressure" | "energy"
  | "power" | "data" | "temperature";

export interface Unit {
  /** What the axis shows. */
  symbol: string;
  kind: UnitKind;
  /** value_in_base = value * factor + offset. */
  factor: number;
  offset?: number;
  /** Other spellings a reader may type, lower case. */
  names: readonly string[];
}

const U = (symbol: string, kind: UnitKind, factor: number, names: string[], offset = 0): Unit =>
  ({ symbol, kind, factor, offset, names });

export const UNITS: readonly Unit[] = [
  U("mm", "length", 0.001, ["millimeter", "millimetre", "millimeters", "millimetres"]),
  U("cm", "length", 0.01, ["centimeter", "centimetre", "centimeters", "centimetres"]),
  U("m", "length", 1, ["meter", "metre", "meters", "metres"]),
  U("km", "length", 1000, ["kilometer", "kilometre", "kilometers", "kilometres"]),
  U("in", "length", 0.0254, ["inch", "inches"]),
  U("ft", "length", 0.3048, ["foot", "feet"]),
  U("yd", "length", 0.9144, ["yard", "yards"]),
  U("mi", "length", 1609.344, ["mile", "miles"]),
  U("mg", "mass", 0.000001, ["milligram", "milligrams"]),
  U("g", "mass", 0.001, ["gram", "grams"]),
  U("kg", "mass", 1, ["kilogram", "kilograms"]),
  U("t", "mass", 1000, ["tonne", "tonnes", "metric ton"]),
  U("oz", "mass", 0.028349523125, ["ounce", "ounces"]),
  U("lb", "mass", 0.45359237, ["pound", "pounds", "lbs"]),
  U("ms", "time", 0.001, ["millisecond", "milliseconds"]),
  U("s", "time", 1, ["sec", "second", "seconds"]),
  U("min", "time", 60, ["minute", "minutes"]),
  U("h", "time", 3600, ["hr", "hour", "hours"]),
  U("d", "time", 86400, ["day", "days"]),
  U("m/s", "speed", 1, ["meters per second", "metres per second", "mps"]),
  U("km/h", "speed", 1 / 3.6, ["kph", "kilometers per hour", "kilometres per hour"]),
  U("mph", "speed", 0.44704, ["miles per hour"]),
  U("kn", "speed", 1852 / 3600, ["knot", "knots", "kt"]),
  U("ml", "volume", 0.001, ["milliliter", "millilitre", "milliliters", "millilitres"]),
  U("l", "volume", 1, ["liter", "litre", "liters", "litres"]),
  U("m³", "volume", 1000, ["m3", "cubic meter", "cubic metre"]),
  U("gal", "volume", 3.785411784, ["gallon", "gallons", "us gallon"]),
  U("Pa", "pressure", 1, ["pascal", "pascals"]),
  U("kPa", "pressure", 1000, ["kilopascal", "kilopascals"]),
  U("bar", "pressure", 100000, ["bars"]),
  U("psi", "pressure", 6894.757293168, ["pounds per square inch"]),
  U("J", "energy", 1, ["joule", "joules"]),
  U("kJ", "energy", 1000, ["kilojoule", "kilojoules"]),
  U("kWh", "energy", 3600000, ["kilowatt hour", "kilowatt hours", "kilowatt-hour"]),
  U("W", "power", 1, ["watt", "watts"]),
  U("kW", "power", 1000, ["kilowatt", "kilowatts"]),
  U("MW", "power", 1000000, ["megawatt", "megawatts"]),
  U("B", "data", 1, ["byte", "bytes"]),
  U("kB", "data", 1000, ["kilobyte", "kilobytes"]),
  U("MB", "data", 1000000, ["megabyte", "megabytes"]),
  U("GB", "data", 1000000000, ["gigabyte", "gigabytes"]),
  U("°C", "temperature", 1, ["c", "celsius", "degc", "degrees celsius"]),
  U("°F", "temperature", 5 / 9, ["f", "fahrenheit", "degf", "degrees fahrenheit"], -32 * 5 / 9),
  U("K", "temperature", 1, ["kelvin"], -273.15),
];

/** The unit a typed label names, or null when it is a custom label. Exact
 * symbols first, since case can matter there; then symbols and names in any
 * case. */
export function unitOf(text: string | null | undefined): Unit | null {
  const typed = (text ?? "").trim();
  if (!typed) return null;
  const bySymbol = UNITS.find((u) => u.symbol === typed);
  if (bySymbol) return bySymbol;
  const lower = typed.toLowerCase();
  return UNITS.find((u) => u.symbol.toLowerCase() === lower || u.names.includes(lower)) ?? null;
}

/** How a reading in one unit reads in another, or null when they are not
 * the same kind of thing (or either is not one this table knows). */
export function converter(from: string, to: string): ((v: number) => number) | null {
  const a = unitOf(from);
  const b = unitOf(to);
  if (!a || !b || a.kind !== b.kind) return null;
  if (a === b) return (v) => v;
  return (v) => ((v * a.factor + (a.offset ?? 0)) - (b.offset ?? 0)) / b.factor;
}

/** Why an axis's Display as cannot be honoured, or null when it can (or
 * there is none to honour). */
export function conversionProblem(unit: string, display: string): string | null {
  if (!display.trim()) return null;
  if (!unitOf(display)) return `${display.trim()} is not a unit this axis can convert to.`;
  if (!unitOf(unit)) {
    return `Converting needs the readings' own unit: set the axis's Unit to one, such as m or °C.`;
  }
  if (!converter(unit, display)) {
    return `${unitOf(unit)!.symbol} and ${unitOf(display)!.symbol} measure different things.`;
  }
  return null;
}

/** What the axis is labelled: the unit converted to when there is a
 * conversion, otherwise the Unit as typed (p.394's custom label). */
export function shownUnit(unit: string, display: string): string {
  return converter(unit, display) && display.trim() ? unitOf(display)!.symbol : unit;
}

/** Readings as an axis shows them. Untouched without a conversion; a gap
 * stays a gap. */
export function convertReadings<R extends { v: number | null }>(
  readings: readonly R[], unit: string, display: string,
): R[] {
  const f = display.trim() ? converter(unit, display) : null;
  if (!f) return readings as R[];
  return readings.map((r) => (r.v === null ? r : { ...r, v: f(r.v) }));
}
