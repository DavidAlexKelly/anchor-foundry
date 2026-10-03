import { ICONS, ICON_NAMES, type IconName, iconNamed } from "@/lib/icons";
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

/** An icon an author set on a widget (§706): the named icon when the value is
 * one, otherwise the characters they typed, cut to `max` as each setting
 * always cut its own. */
export function IconOrGlyph({ value, max = 2, size }: {
  value: string | null | undefined;
  max?: number;
  size?: number;
}) {
  const trimmed = (value ?? "").trim();
  return iconNamed(trimmed)
    ? <NamedIcon name={trimmed as IconName} size={size} />
    : <>{[...trimmed].slice(0, max).join("")}</>;
}

/** The control for an icon setting (§706): one of the set's icons, or - the
 * first option, and what every setting held before the set existed - one or
 * two typed characters. The typed field keeps its `testId`; the choice of
 * icon is `${testId}-name`. */
export function IconChoice({ value, onChange, testId, max = 2, placeholder }: {
  value: string | null | undefined;
  onChange: (next: string) => void;
  testId: string;
  max?: number;
  placeholder?: string;
}) {
  const trimmed = (value ?? "").trim();
  const named = iconNamed(trimmed) ? (trimmed as IconName) : null;
  return (
    <span className="icon-choice">
      <select
        value={named ?? ""}
        aria-label="Icon"
        data-testid={`${testId}-name`}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Typed characters</option>
        {ICON_NAMES.map((name) => (
          <option key={name} value={name}>{ICONS[name].label}</option>
        ))}
      </select>
      {named ? (
        <NamedIcon name={named} size={16} />
      ) : (
        <input
          type="text"
          value={value ?? ""}
          maxLength={max}
          placeholder={placeholder}
          aria-label="Typed icon"
          data-testid={testId}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </span>
  );
}
