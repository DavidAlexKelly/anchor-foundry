/** p.63-64's interface link rules in the action editor (§762; decision 0024).
 *
 * > "If the link constraint is between two interfaces, both the source and
 * > destination parameters will be automatically generated as interface
 * > reference parameters." (action-types p.63)
 *
 * The source is the action's own object. The destination is generated when
 * no parameter of the right kind exists yet, named after the link. */

/** A parameter name for the link's other end: the link's own name, or that
 * name with the first free number after it. */
export function generatedName(base: string, taken: readonly string[]): string {
  if (!taken.includes(base)) return base;
  let n = 2;
  while (taken.includes(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}
