"use client";

/** p.309's export options, on hover of a chart (§529): "Download chart as
 * image" and copy to the clipboard. View mode only, as p.309 says; in the
 * builder a click on a chart selects it. The drawing is `chart-image.ts`'s. */

import { useState, type RefObject } from "react";

import { copyProblem, imageFileName, standaloneSvg, toPng } from "./chart-image";

export function ChartExport({ target, title }: {
  /** The element the chart's SVG is inside. */
  target: RefObject<HTMLElement | null>;
  /** What the chart shows, for the file name. */
  title: string;
}) {
  const [said, setSaid] = useState<string | null>(null);

  async function picture(): Promise<Blob> {
    const svg = target.current?.querySelector("svg");
    if (!svg) throw new Error("there is no chart to export yet");
    const box = svg.getBoundingClientRect();
    const background = getComputedStyle(document.body).backgroundColor || "#ffffff";
    return toPng(standaloneSvg(svg as SVGSVGElement), box.width, box.height,
                 background === "rgba(0, 0, 0, 0)" ? "#ffffff" : background);
  }

  async function download() {
    try {
      const blob = await picture();
      const name = imageFileName(title);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = name;
      link.click();
      URL.revokeObjectURL(link.href);
      setSaid(`Downloaded ${name}`);
    } catch (error) {
      setSaid(error instanceof Error ? error.message : String(error));
    }
  }

  async function copy() {
    try {
      const blob = await picture();
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      setSaid("Copied the chart to the clipboard");
    } catch (error) {
      setSaid(copyProblem(error));
    }
  }

  return (
    <div className="chart-export" data-testid="chart-export">
      <button type="button" className="btn quiet" data-testid="chart-export-download" onClick={download}>
        Download chart as image
      </button>
      <button type="button" className="btn quiet" data-testid="chart-export-copy" onClick={copy}>
        Copy chart
      </button>
      {said && <span className="soft" role="status" data-testid="chart-export-status">{said}</span>}
    </div>
  );
}
