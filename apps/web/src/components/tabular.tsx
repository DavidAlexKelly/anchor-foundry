"use client";

/** The preview table (§439).
 *
 * **Its own file because two screens draw it**: the dataset application's
 * Preview and Query tabs, and `data-lineage` p.45's Preview tab under the
 * lineage graph. One renderer, imported by both — a second copy would be a
 * second idea of how a null cell looks and of whether the column type goes
 * under the heading, which is exactly the detail that drifts (§292).
 */

import type { TabularResult } from "@/lib/types";

export function Table({ result }: { result: TabularResult }) {
  return (
    <div className="ds-scroll">
      <table className="ds-table">
        <thead>
          <tr>
            {result.columns.map((c) => (
              <th key={c.name} scope="col">
                {c.name}
                <span className="ds-coltype">{c.data_type}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>
                  {cell === null ? <span className="ds-null">null</span> : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
