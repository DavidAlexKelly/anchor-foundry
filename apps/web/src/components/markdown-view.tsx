"use client";

/** The Markdown tree, as React elements (§442).
 *
 * The parsing, the syntax and every rule about what Markdown *means* are
 * `canvas/markdown.ts`'s and are tested without a browser. What is here is the
 * part that has to be React: turning the tree into elements.
 *
 * **Its own file because two screens render it**: p.314's Markdown widget in a
 * Workshop module, and `code-repositories` p.67's README in a repository. One
 * renderer, imported by both — a second copy would be a second answer to the
 * question below about where a link opens, and to the one about raw HTML
 * (§292).
 *
 * **There is no `dangerouslySetInnerHTML` in this file, and that is the design
 * rather than an accident.** `parse` returns plain objects, so every string
 * below reaches the DOM as a text child, which React escapes. Raw HTML an
 * author typed is shown as the characters they typed.
 */

import React from "react";

import {
  blockAlignment, columnAlignment,
  type Align, type Block, type Inline,
} from "@/components/canvas/markdown";

/** Whether a link leaves this platform.
 *
 * `safeHref` allows four things through — `http://`, `https://`, `mailto:` and
 * a root-relative path — and the last of those is a page of this application.
 * **A link to another page of the app that opened a new tab would be a
 * navigation nobody asked for**, and one to somebody else's site that did not
 * would hand them the reader's history through `Referer` and leave the app
 * behind. So the two are treated differently, in one place, rather than every
 * caller choosing.
 */
export function leavesTheApp(href: string): boolean {
  return !href.startsWith("/");
}

function renderInline(nodes: Inline[]): React.ReactNode {
  return nodes.map((node, index) => {
    switch (node.kind) {
      case "text":
        return <React.Fragment key={index}>{node.text}</React.Fragment>;
      case "code":
        return <code key={index}>{node.text}</code>;
      case "strong":
        return <strong key={index}>{renderInline(node.children)}</strong>;
      case "em":
        return <em key={index}>{renderInline(node.children)}</em>;
      case "del":
        return <del key={index}>{renderInline(node.children)}</del>;
      case "mark":
        return <mark key={index}>{renderInline(node.children)}</mark>;
      case "break":
        return <br key={index} />;
      case "link":
        // `noreferrer` as well as `noopener`: an app's Markdown is written by
        // one person and read by the workspace, and the reader did not choose
        // to tell the destination where they came from.
        return (
          <a
            key={index}
            href={node.href}
            // `noreferrer` as well as `noopener`: an app's Markdown is written
            // by one person and read by the workspace, and the reader did not
            // choose to tell the destination where they came from. **Only for
            // links that leave** — a link to another page of this application
            // opening a new tab is a navigation nobody asked for, and p.68 is
            // explicit that a `repo://` file "will automatically open when
            // clicked", in place.
            target={leavesTheApp(node.href) ? "_blank" : undefined}
            rel={leavesTheApp(node.href) ? "noreferrer noopener" : undefined}
          >
            {renderInline(node.children)}
          </a>
        );
      case "image":
        return <img key={index} src={node.src} alt={node.alt} />;
    }
  });
}

function renderBlock(block: Block, key: number, widget: Align): React.ReactNode {
  // p.317's "Code blocks remain left-aligned and full-width regardless of the
  // selected alignment", decided in the model rather than here.
  const style = { textAlign: blockAlignment(block, widget) } as React.CSSProperties;
  switch (block.kind) {
    case "heading":
      return React.createElement(
        `h${block.level}`,
        { key, style, className: "canvas-markdown-heading" },
        renderInline(block.children),
      );
    case "paragraph":
      return <p key={key} style={style}>{renderInline(block.children)}</p>;
    case "code":
      // **The style is applied here too, and that is the point.** Leaving it off
      // let the browser compute `start`, which looks left-aligned and is only
      // left-aligned by inheritance - so `blockAlignment`'s answer for the one
      // block kind it exists for was computed and thrown away, and any future
      // rule setting `text-align` on the container would have taken code blocks
      // with it. The browser suite caught it as `start` != `left`.
      return (
        <pre key={key} style={style} className="canvas-markdown-code">
          <code>{block.text}</code>
        </pre>
      );
    case "rule":
      return <hr key={key} />;
    case "quote":
      return (
        <blockquote key={key} className="canvas-markdown-quote">
          {block.blocks.map((b, i) => renderBlock(b, i, widget))}
        </blockquote>
      );
    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag key={key} style={style} className="canvas-markdown-list">
          {block.items.map((item, i) => (
            <li key={i} className={item.done === undefined ? undefined : "canvas-markdown-task"}>
              {item.done !== undefined && (
                // Shown, and not editable: p.318 lists a task list as a
                // *syntax*, so the tick is what the author wrote. A checkbox a
                // viewer could clear would be a control with nowhere to put the
                // answer.
                <input type="checkbox" checked={item.done} readOnly disabled />
              )}
              {renderInline(item.children)}
            </li>
          ))}
        </Tag>
      );
    }
    case "table":
      return (
        <table key={key} className="canvas-markdown-table">
          <thead>
            <tr>
              {block.head.map((cell, i) => (
                <th key={i} style={{ textAlign: columnAlignment(block.align[i] ?? null, widget) }}>
                  {renderInline(cell)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, i) => (
                  <td key={i} style={{ textAlign: columnAlignment(block.align[i] ?? null, widget) }}>
                    {renderInline(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
  }
}

export function MarkdownView({
  blocks,
  align = "left",
}: {
  blocks: Block[];
  /** The widget's own alignment, which p.317 lets some blocks override. */
  align?: Align;
}) {
  return <>{blocks.map((b, i) => renderBlock(b, i, align))}</>;
}
