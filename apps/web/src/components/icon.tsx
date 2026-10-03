import { ICONS, type IconName } from "@/lib/icons";
import { type Marked, glyph, iconName } from "@/lib/object-type-icon";

/** A named icon from `lib/icons.ts` (§705), drawn in the ink of whatever it
 * sits in. Decoration beside words that say the same thing, so hidden from a
 * screen reader. Typed to the set's names: a value that may not be one is
 * asked with `iconNamed` first, which is where that question belongs. */
export function NamedIcon({ name, size = 14 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="named-icon"
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      data-icon={name}
      aria-hidden="true"
    >
      {ICONS[name].paths.map((d) => <path key={d} d={d} />)}
    </svg>
  );
}

/** What an object type's coloured mark holds (§705; `object-link-types`
 * p.15): its named icon, or the glyph `object-type-icon.glyph` falls back
 * to. */
export function TypeGlyph({ type, size = 12 }: { type: Marked; size?: number }) {
  const name = iconName(type);
  return name ? <NamedIcon name={name} size={size} /> : <>{glyph(type)}</>;
}
