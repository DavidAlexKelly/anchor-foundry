"use client";

/**
 * p.11's in-app walkthrough, on the screen (§431; `code-repositories` p.11).
 *
 * The arithmetic — which steps have something to point at, where the counter
 * is, where the card goes — is in `lib/walkthrough.ts`, because vitest cannot
 * parse `.tsx` and that is the part that is wrong in most tours. What is left
 * here is what only a browser can answer: that the highlighted element is the
 * one the step names, that a step on another tab takes you there first, and
 * that Escape ends it.
 *
 * **Which steps there are is a question about the project, not about the
 * document.** Asking `querySelector` was written first and cannot work: a step
 * about the Publish tab is never in the document while you are on Files, so
 * every step the walk exists to take you to would be dropped before it could.
 * `holds` is answered by the caller from what it already knows.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Step } from "@/lib/walkthrough";
import {
  at,
  centred,
  move,
  nextLabel,
  placeCard,
  progressLabel,
  stepsFor,
} from "@/lib/walkthrough";

/** Where a step's element is, or null when it is not in the document. */
function anchorOf(anchor: string): Element | null {
  return document.querySelector(`[data-tour="${anchor}"]`);
}

export function Walkthrough({
  steps,
  holds,
  tab,
  onTab,
}: {
  steps: readonly Step[];
  /** Whether a step's named condition is true of this project. */
  holds: (need: string) => boolean;
  /** The tab the application is showing. **A dependency, not decoration**: a
   *  step's element does not exist until its tab has rendered, so the card is
   *  placed again when this changes or it would stay where it was put before
   *  the thing it points at existed. */
  tab: string;
  /** Called when a step names a tab. */
  onTab: (tab: string) => void;
}) {
  const [walking, setWalking] = useState(false);
  const [index, setIndex] = useState(0);
  /** The same number, readable synchronously. **Two clicks on Next inside one
   *  render frame both read the same `index` from their closure and both
   *  advance to the same step**, so a reader who clicks quickly walks half as
   *  far as they pressed. The ref is what the handlers count from. */
  const cursor = useRef(0);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  const card = useRef<HTMLDivElement>(null);


  const shown = walking ? stepsFor(steps, holds) : [];
  const step = at(shown, index);

  /** Go to a step, and to its tab.
   *
   * **The tab is asked for here, in the click, and not in an effect.** Both
   * were written and only this one works: a `router.replace` issued from an
   * effect during the render cascade the walk sets off is swallowed — the
   * application re-rendered on the new tab and the address bar went on naming
   * the old one, so a shared link pointed somewhere the reader had left. A
   * browser test found it by checking the URL rather than the screen, which is
   * the only way that difference is visible.
   */
  function goTo(next: number) {
    cursor.current = next;
    setIndex(next);
    const arriving = at(shown, next);
    if (arriving?.tab) onTab(arriving.tab);
  }

  useLayoutEffect(() => {
    if (!step) {
      setPlace(null);
      return;
    }
    let outlined: Element | null = null;
    let placedBlind = false;

    /** Put the card where it belongs, if the thing it belongs to is here. */
    function put(): boolean {
      if (!card.current) return false;
      const size = {
        width: card.current.offsetWidth,
        height: card.current.offsetHeight,
      };
      const view = { width: window.innerWidth, height: window.innerHeight };
      const element = anchorOf(step!.anchor);
      if (!element) {
        // Centred once, not on every mutation: the words are readable while
        // the panel loads, and re-placing it each time would be a render per
        // DOM change for a card that has not moved.
        if (!placedBlind) {
          placedBlind = true;
          setPlace(centred(size, view));
        }
        return false;
      }
      outlined = element;
      element.setAttribute("data-tour-on", "true");
      const box = element.getBoundingClientRect();
      setPlace(placeCard(
        { top: box.top, left: box.left, width: box.width, height: box.height },
        size,
        view,
      ));
      element.scrollIntoView({ block: "nearest" });
      return true;
    }

    if (put()) {
      return () => outlined?.removeAttribute("data-tour-on");
    }

    // **The anchor can arrive after the tab does**, and that is the ordinary
    // case rather than an edge: a tab's panel is a query away, so switching to
    // Publish renders "Reading main…" first and the thing this step describes
    // a moment later. Waiting for the tab prop to change is not enough — it
    // already has. A browser test caught this as a step with no outline, which
    // is a walkthrough pointing at nothing while sounding certain.
    const watch = new MutationObserver(() => {
      if (put()) watch.disconnect();
    });
    watch.observe(document.body, { childList: true, subtree: true });
    return () => {
      watch.disconnect();
      outlined?.removeAttribute("data-tour-on");
    };
  }, [step, tab]);

  useEffect(() => {
    if (!walking) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setWalking(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [walking]);

  function start() {
    cursor.current = 0;
    setIndex(0);
    setPlace(null);
    setWalking(true);
    // The first step's tab, if it names one. `shown` is empty until `walking`
    // is true, so this reads the unfiltered list's first showable step - which
    // is the same step, because the walk always starts at its beginning.
    const first = at(stepsFor(steps, holds), 0);
    if (first?.tab) onTab(first.tab);
  }

  function forward() {
    // **The end closes rather than stopping on the last card.** A "Done" that
    // left the card on screen would make the reader dismiss it twice.
    if (cursor.current >= shown.length - 1) {
      setWalking(false);
      return;
    }
    goTo(move(shown, cursor.current, 1));
  }

  if (!walking) {
    return (
      <button
        type="button"
        className="btn quiet walkthrough-open"
        data-testid="open-walkthrough"
        aria-label="Start the walkthrough"
        title="Start the walkthrough"
        onClick={start}
      >
        ?
      </button>
    );
  }

  return (
    <>
      {/* Not a click-to-dismiss scrim: the walk describes controls, and a
          layer over them would make the thing being described unreachable
          the moment somebody tried it. Escape and Done are the ways out. */}
      <div className="walkthrough-dim" data-testid="walkthrough-dim" />
      <div
        ref={card}
        className="walkthrough-card"
        role="dialog"
        aria-label="Walkthrough"
        data-testid="walkthrough-card"
        data-step={step?.id}
        style={place ? { top: place.top, left: place.left } : { visibility: "hidden" }}
      >
        {step ? (
          <>
            <p className="walkthrough-count" data-testid="walkthrough-count">
              {progressLabel(shown, index)}
            </p>
            <h4>{step.title}</h4>
            <p className="walkthrough-body">{step.body}</p>
          </>
        ) : (
          /* Every step's control is off the screen — possible in principle,
             and a blank card is the one thing worse than no walkthrough. */
          <p className="walkthrough-body" data-testid="walkthrough-none">
            There is nothing to walk through on this screen yet.
          </p>
        )}
        <div className="walkthrough-controls">
          <button
            type="button"
            className="btn quiet"
            data-testid="walkthrough-back"
            disabled={index === 0}
            onClick={() => goTo(move(shown, cursor.current, -1))}
          >
            Back
          </button>
          <button
            type="button"
            className="btn quiet"
            data-testid="walkthrough-close"
            onClick={() => setWalking(false)}
          >
            Close
          </button>
          <button
            type="button"
            className="btn"
            data-testid="walkthrough-next"
            onClick={forward}
          >
            {step ? nextLabel(shown, index) : "Done"}
          </button>
        </div>
      </div>
    </>
  );
}
