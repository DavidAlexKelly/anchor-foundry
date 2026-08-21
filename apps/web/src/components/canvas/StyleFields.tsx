"use client";

/** The style block, as controls (Foundry `workshop` p.57-62).
 *
 * > "These options are available at the page, section, and widget levels."
 * > (p.57)
 *
 * One component for all three, because the alternative is the same four
 * controls written out three times and drifting - and p.57's sentence is
 * itself the argument that they are one thing appearing in three places.
 *
 * **Which options appear where is p.57-62's own asymmetry, not a
 * simplification.** Backgrounds are offered on all three (p.58); border styles
 * "can be configured on sections and widgets" (p.60); padding is "for pages and
 * sections" (p.62). Offering all four everywhere would be easier to write and
 * would put a padding control on a widget that has nothing to pad.
 */

import {
  BACKGROUND_LABELS, BACKGROUND_PRESETS, BORDERS, BORDER_LABELS,
  PADDINGS, PADDING_LABELS, paddingFor, resolveBackground,
  type BorderName, type PaddingName, type StyleProps,
} from "./style";

const PRESET_NAMES = Object.keys(BACKGROUND_PRESETS) as (keyof typeof BACKGROUND_PRESETS)[];
const PADDING_NAMES = [...Object.keys(PADDINGS), "custom"] as PaddingName[];

export function StyleFields({
  props,
  set,
  padding = false,
  border = false,
}: {
  props: StyleProps;
  /** Writes one style prop. Craft's `setProp` is per-node, so the caller owns
   * it and this component stays free of `useNode`, which is what lets it be
   * tested by rendering rather than only inside a builder. */
  set: (key: keyof StyleProps, value: unknown) => void;
  /** p.62: pages and sections. */
  padding?: boolean;
  /** p.60: sections and widgets. */
  border?: boolean;
}) {
  const background = props.background ?? "";
  const custom = !(background in BACKGROUND_PRESETS) && background !== "";
  const [block, inline] = paddingFor(props);

  return (
    <>
      <label className="field">
        <span className="field-label">Background</span>
        <select
          data-testid="style-background"
          value={custom ? "custom" : background || "transparent"}
          onChange={(e) =>
            set(
              "background",
              // Switching *to* custom seeds the picker with the colour that is
              // already showing, so the swatch does not blank the moment
              // somebody reaches for a shade of it. Switching to a preset
              // replaces it outright, which is what picking a preset means.
              e.target.value === "custom"
                ? resolveBackground(background) ?? "#ffffff"
                : e.target.value,
            )
          }
        >
          {PRESET_NAMES.map((name) => (
            <option key={name} value={name}>{BACKGROUND_LABELS[name]}</option>
          ))}
          <option value="custom">Custom…</option>
        </select>
      </label>
      {custom && (
        <label className="field">
          <span className="field-label">Custom colour</span>
          <input
            type="text"
            data-testid="style-background-hex"
            value={background}
            placeholder="#16232f"
            onChange={(e) => set("background", e.target.value)}
          />
          <span className="field-hint">
            {/* p.59-60's rule, said rather than left to be discovered: it is
                the one setting here whose effect lands on things the builder
                did not select. */}
            A dark colour switches the widgets inside to light text
          </span>
        </label>
      )}

      {padding && (
        <label className="field">
          <span className="field-label">Padding</span>
          <select
            data-testid="style-padding"
            value={props.padding ?? "none"}
            onChange={(e) => set("padding", e.target.value)}
          >
            {PADDING_NAMES.map((name) => (
              <option key={name} value={name}>{PADDING_LABELS[name]}</option>
            ))}
          </select>
        </label>
      )}
      {padding && props.padding === "custom" && (
        <div className="field">
          <span className="field-label">Custom padding (px)</span>
          <div className="style-padding-pair">
            <input
              type="number" min={0} aria-label="Top and bottom padding"
              data-testid="style-padding-block"
              value={block}
              onChange={(e) => set("customPadding", [Number(e.target.value) || 0, inline])}
            />
            <input
              type="number" min={0} aria-label="Left and right padding"
              data-testid="style-padding-inline"
              value={inline}
              onChange={(e) => set("customPadding", [block, Number(e.target.value) || 0])}
            />
          </div>
          <span className="field-hint">Top and bottom, then left and right</span>
        </div>
      )}

      {border && (
        <label className="field">
          <span className="field-label">Border</span>
          <select
            data-testid="style-border"
            value={props.border ?? "borderless"}
            onChange={(e) => set("border", e.target.value as BorderName)}
          >
            {BORDERS.map((name) => (
              <option key={name} value={name}>{BORDER_LABELS[name]}</option>
            ))}
          </select>
        </label>
      )}
    </>
  );
}
