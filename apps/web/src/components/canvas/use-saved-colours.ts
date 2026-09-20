"use client";

/** The module's palette, as a widget sees it (§414; `workshop` p.214).
 *
 * Two contexts and one `paletteOf`, in one place rather than at each of the
 * half-dozen sites that style something. The palette is module-level state
 * (`CanvasEnv`) and the scheme is module-level runtime state
 * (`CanvasPageState`), and p.214's "set separate colors for light and dark
 * modes" needs both — so the first widget to assemble this by hand would be
 * the first to forget the second half and render light colours in dark mode.
 */

import { useMemo } from "react";

import { useCanvasEnv, useCanvasPage } from "./context";
import { type SavedColour, paletteOf } from "./saved-colours";

export interface Saved {
  palette: readonly SavedColour[];
  scheme: "light" | "dark";
}

export function useSavedColours(): Saved {
  const { savedColours } = useCanvasEnv();
  const { scheme } = useCanvasPage();
  // Memoised on the stored value rather than on the parsed one: `paletteOf`
  // builds a fresh array every call, and a style object rebuilt on every
  // render is a widget that re-renders on every render.
  return useMemo(() => ({ palette: paletteOf(savedColours), scheme }), [savedColours, scheme]);
}
