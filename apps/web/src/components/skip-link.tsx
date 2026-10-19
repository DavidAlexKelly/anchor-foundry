"use client";

/** "Skip to content" (§1013, WCAG 2.4.1): the first thing a keyboard reaches
 * on a page, and hidden until it is reached.
 *
 * Without it, every page begins with the top bar's links, the workspace
 * search, the notification bell and sign out - and a project's pages with
 * its sidebar's ten sections after those - before the page itself. It goes
 * to the page's `main`, which every page has (§1008) as `#main`, and focuses
 * it, so the next Tab is the page's own first control rather than the top
 * bar's again. */
export function SkipLink() {
  return (
    <a
      href="#main"
      className="skip-link"
      onClick={(e) => {
        const main = document.getElementById("main");
        if (!main) return;
        e.preventDefault();
        // Focusable from here only, not by Tab: it is a landmark, not a control.
        if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
        main.focus();
      }}
    >
      Skip to content
    </a>
  );
}
