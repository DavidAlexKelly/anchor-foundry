"""The Iframe's Bidirectional mode (`workshop` p.552-553; decision 0023; §756).

> "This enables the embedded application to act as if it were any other
> Workshop widget, with the ability to read from and write to Workshop
> variables, as well as execute Workshop events." (p.552)

The framed application is a page served from **another origin** (127.0.0.1
against the app's localhost), so what crosses is `postMessage` and nothing
else, as it would for a real one. It speaks decision 0023's messages: it sends
its definition, shows the value it is sent, writes one field and fires one
event. What each message means is `frame-protocol.test.ts`'; what needs a
browser is the round trip through a real frame.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import (
    eventually, open_builder, open_module, publish, save, select_node, settled, stays, viewer_url,
)

TOOL = """<!doctype html><meta charset=utf-8><title>Tool</title>
<p>Query: <b id=shown>(nothing yet)</b></p>
<button id=write>Write</button> <button id=ping>Ping</button> <button id=sneak>Sneak</button>
<iframe id=child src="/stranger" style="height:40px"></iframe>
<script>
const DEF = {type: "anchor-widget//definition", version: 1,
  fields: [{id: "query", label: "Query", type: "string", access: "read"},
           {id: "echo", label: "Echo", type: "string", access: "write"}],
  events: [{id: "ping", label: "Ping"}]};
function send(m) { parent.postMessage(Object.assign({version: 1}, m), "*"); }
window.addEventListener("message", (e) => {
  if (e.source !== parent) return;
  const d = e.data || {};
  if (d.type === "anchor-widget//request-definition") send(DEF);
  if (d.type === "anchor-widget//values") {
    const q = d.values.query;
    document.getElementById("shown").textContent = q ? String(q.value) : "(unbound)";
  }
});
send(DEF);
document.getElementById("write").onclick = () =>
  send({type: "anchor-widget//set-value", fieldId: "echo", value: "from the frame"});
document.getElementById("ping").onclick = () =>
  send({type: "anchor-widget//execute-event", eventId: "ping"});
// A read-only field written anyway: ignored.
document.getElementById("sneak").onclick = () =>
  send({type: "anchor-widget//set-value", fieldId: "query", value: "sneaky"});
</script>"""

#: A page inside the tool, on the tool's own origin, that is not the tool:
#: it writes as if it were (decision 0023 §2: read only from the frame's own
#: window).
STRANGER = """<!doctype html><meta charset=utf-8><button id=stranger>Stranger</button>
<script>
document.getElementById("stranger").onclick = () => top.postMessage(
  {type: "anchor-widget//set-value", version: 1, fieldId: "echo", value: "from a stranger"}, "*");
</script>"""


@pytest.fixture(scope="module")
def tool():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:
            body = (STRANGER if self.path.startswith("/stranger") else TOOL).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/tool"
    server.shutdown()


VARIABLES = {
    "v_query": {"id": "v_query", "kind": "string", "label": "Query", "default": "first"},
    "v_echo": {"id": "v_echo", "kind": "string", "label": "Echo", "default": ""},
    "v_pinged": {"id": "v_pinged", "kind": "string", "label": "Pinged", "default": ""},
}

DEFINITION = {
    "fields": [{"id": "query", "label": "Query", "type": "string", "access": "read"},
               {"id": "echo", "label": "Echo", "type": "string", "access": "write"}],
    "events": [{"id": "ping", "label": "Ping"}],
}


def bidirectional_module(api, name: str, url: str, *, wired: bool,
                         definition: dict | None = None) -> Module:
    mod = Module(api, name)
    frame_props = {"url": url, "title": "Tool", "frameMode": "bidirectional"}
    if wired:
        frame_props["frameDefinition"] = definition or DEFINITION
        frame_props["frameBindings"] = {"query": "v_query", "echo": "v_echo"}
    mod.define({
        "format": 2,
        "layout": layout({
            "input": {"resolvedName": "CanvasTextInput",
                      "props": {"name": "v_query", "label": "Query box"}},
            "frame": {"resolvedName": "CanvasIframe", "props": frame_props},
            "echo": {"resolvedName": "CanvasMarkdown", "props": {"source": "variable", "textVariable": "v_echo"}},
            "pinged": {"resolvedName": "CanvasMarkdown", "props": {"source": "variable", "textVariable": "v_pinged"}},
        }),
        "variables": VARIABLES,
        "events": {"e_ping": {
            "id": "e_ping", "trigger": {"node": "frame", "on": "click", "item": "ping"},
            "effects": [{"type": "set_variable",
                         "config": {"variable": "v_pinged", "value": "pinged by the tool"}}],
        }} if wired else {},
    })
    return mod


def test_the_builder_learns_the_definition_from_the_frame(page, api, tool) -> None:
    """p.553: the panel waits for the definition, then offers a variable
    picker per field; the definition and the bindings save with the module."""
    mod = bidirectional_module(api, "Iframe bidirectional builder", tool, wired=False)
    open_builder(page, mod)
    select_node(page, "Iframe")
    # The frame answers on load, so the panel moves past waiting by itself.
    expect(page.get_by_test_id("iframe-bind-query")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("iframe-waiting")).to_have_count(0)
    expect(page.get_by_test_id("iframe-events")).to_contain_text("It can fire Ping")
    # A written field is offered no derived variable; there are none here, so
    # the string variables are the options.
    page.get_by_test_id("iframe-bind-query").select_option("v_query")
    page.get_by_test_id("iframe-bind-echo").select_option("v_echo")
    save(page)

    stored = mod.definition()["layout"]["frame"]["props"]
    assert stored["frameDefinition"] == DEFINITION
    assert stored["frameBindings"] == {"query": "v_query", "echo": "v_echo"}

    # p.553's "event selectors": each event the application asks for is an
    # item of the widget in the Events panel, as a Menu button's are.
    page.get_by_role("button", name="Events (0)").click()
    page.get_by_role("button", name="New event").click()
    page.locator(".canvas-event-body select").first.select_option("frame")
    expect(page.get_by_test_id("event-item").locator("option")).to_have_text(["Ping"])
    save(page)
    eventually(lambda: [e["trigger"] for e in mod.definition()["events"].values()],
               lambda got: got == [{"node": "frame", "on": "click", "item": "ping"}],
               what="the event aimed at the application's Ping")

    # Decision 0023 §3: in the builder the frame's writes are not acted on.
    # Pressed from inside it, since the builder's frame takes no clicks.
    tool_frame = next(f for f in page.frames if f.url.startswith(tool))
    tool_frame.evaluate("document.getElementById('write').click()")
    stays(lambda: page.get_by_text("from the frame").count(), lambda n: n == 0,
          what="a write from the frame while building", for_ms=3000)


def test_values_go_in_and_writes_and_events_come_out(page, api, tool) -> None:
    mod = bidirectional_module(api, "Iframe bidirectional run", tool, wired=True)
    open_module(page, mod)
    settled(page)
    frame = page.frame_locator('[data-testid="iframe"]')

    # p.553: the bound value is sent, and sent again when it changes.
    expect(frame.locator("#shown")).to_have_text("first", timeout=30000)
    page.get_by_label("Query box").fill("second")
    expect(frame.locator("#shown")).to_have_text("second", timeout=15000)

    # A write lands on the bound variable, which the module shows.
    frame.locator("#write").click()
    expect(page.get_by_text("from the frame")).to_be_visible(timeout=15000)

    # An event the application asks for runs what the module wired to it.
    frame.locator("#ping").click()
    expect(page.get_by_text("pinged by the tool")).to_be_visible(timeout=15000)

    # A read-only field is not written, whatever the frame sends.
    frame.locator("#sneak").click()
    expect(page.get_by_label("Query box")).to_have_value("second")
    expect(frame.locator("#shown")).to_have_text("second")


def test_only_the_frame_itself_is_listened_to(page, api, tool) -> None:
    """A page inside the tool shares its origin and is not it: what it sends
    is ignored."""
    mod = bidirectional_module(api, "Iframe bidirectional stranger", tool, wired=True)
    open_module(page, mod)
    settled(page)
    frame = page.frame_locator('[data-testid="iframe"]')
    expect(frame.locator("#shown")).to_have_text("first", timeout=30000)
    frame.frame_locator("#child").locator("#stranger").click()
    # The tool's own event after it: once that has run, the stranger's write
    # has had its turn, and nothing else writes Echo meanwhile.
    frame.locator("#ping").click()
    expect(page.get_by_text("pinged by the tool")).to_be_visible(timeout=15000)
    expect(page.get_by_text("from a stranger")).to_have_count(0)


def test_a_viewers_frame_does_not_rewrite_the_saved_definition(page, api, tool) -> None:
    """Decision 0023 §4: the definition the module saved is the one read at
    run time. Here it says Echo is read-only, and the frame says otherwise,
    so the frame's write is refused."""
    saved = {**DEFINITION, "fields": [DEFINITION["fields"][0],
                                     {**DEFINITION["fields"][1], "access": "read"}]}
    mod = bidirectional_module(api, "Iframe bidirectional saved", tool, wired=True,
                               definition=saved)
    # Viewed, not opened: the builder learns the frame's definition, which is
    # its job, so only a viewer's page can ask this.
    publish(mod)
    page.goto(viewer_url(mod))
    settled(page)
    frame = page.frame_locator('[data-testid="iframe"]')
    expect(frame.locator("#shown")).to_have_text("first", timeout=30000)
    frame.locator("#write").click()
    frame.locator("#ping").click()
    # The event still runs, so the write has had its chance to land first.
    expect(page.get_by_text("pinged by the tool")).to_be_visible(timeout=15000)
    expect(page.get_by_text("from the frame")).to_have_count(0)


def test_an_event_wired_to_something_the_application_does_not_ask_for_is_refused(
    api, tool
) -> None:
    mod = bidirectional_module(api, "Iframe bidirectional refused", tool, wired=True)
    document = mod.definition()
    document["events"]["e_ping"]["trigger"]["item"] = "pong"
    with pytest.raises(Exception, match="does not have"):
        mod.define(document)
