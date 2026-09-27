/** A chart as a picture: p.309's "Download chart as image" and copy to the
 * clipboard (§529).
 *
 * > "The Pie Chart widget supports exporting of the current chart
 * > visualization as a PNG … The current chart visualization can also be
 * > copied as an image to the clipboard. Export and copy to clipboard options
 * > appear on hover of the widget." (p.309)
 *
 * **The drawing is the chart's own SVG**, rasterised in the browser: nothing
 * is re-rendered and nothing goes to the server. What an SVG loses when it
 * leaves the page is its stylesheet, since its colours are CSS variables and
 * class rules, so each element's computed paint is written onto a copy
 * before it is drawn.
 */

/** A file name from what the chart shows: its words, lower-cased and joined,
 * or "chart" when it has none. */
export function imageFileName(title: string | null | undefined): string {
  const words = (title ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${(words || "chart").slice(0, 80).replace(/-+$/, "")}.png`;
}

/** The paint an SVG takes from its stylesheet, which a copy outside the page
 * has to carry itself. */
export const PAINT = [
  "fill", "fill-opacity", "stroke", "stroke-width", "stroke-dasharray", "opacity",
  "font-family", "font-size", "font-weight", "text-anchor", "dominant-baseline",
] as const;

/** An SVG as standalone markup: every element's computed paint inlined, and
 * its size written down, so it draws the same with no page around it. */
export function standaloneSvg(svg: SVGSVGElement, view: Window = window): string {
  const copy = svg.cloneNode(true) as SVGSVGElement;
  const from = [svg, ...Array.from(svg.querySelectorAll("*"))];
  const to = [copy, ...Array.from(copy.querySelectorAll("*"))];
  from.forEach((element, i) => {
    const computed = view.getComputedStyle(element);
    const target = to[i] as SVGElement | undefined;
    if (!target) return;
    for (const name of PAINT) {
      const value = computed.getPropertyValue(name);
      if (value) target.style.setProperty(name, value);
    }
  });
  const box = svg.getBoundingClientRect();
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("width", String(Math.max(1, Math.round(box.width))));
  copy.setAttribute("height", String(Math.max(1, Math.round(box.height))));
  return new XMLSerializer().serializeToString(copy);
}

/** Standalone SVG markup drawn onto a canvas at `scale`, as a PNG. The page
 * background under it, since a transparent PNG pasted into a dark document
 * loses its dark text. */
export function toPng(markup: string, width: number, height: number, background: string,
                      scale = 2): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      const context = canvas.getContext("2d");
      if (!context) { reject(new Error("this browser cannot draw the chart")); return; }
      context.fillStyle = background;
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.scale(scale, scale);
      context.drawImage(image, 0, 0, width, height);
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("the chart could not be drawn"))),
                    "image/png");
    };
    image.onerror = () => reject(new Error("the chart could not be drawn"));
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
  });
}

/** What a failed copy says. A browser without image clipboards is common
 * enough to name, rather than leaving a button that seems to do nothing. */
export function copyProblem(error: unknown): string {
  if (typeof ClipboardItem === "undefined") return "This browser cannot copy images. Download the chart instead.";
  const message = error instanceof Error ? error.message : String(error);
  return `Couldn't copy the chart: ${message}`;
}
