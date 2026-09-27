"""An S3 source that authenticates with OpenID Connect (§599; `data-connection`
p.391).

> "When using OIDC, you do not need to configure credentials for a source
>  system in Foundry. ... Instead, you will configure a trust relationship
>  between Foundry and the source system. Foundry acts as the OIDC identity
>  provider" (p.391)

What needs a browser: the discovery document is reachable at the issuer this
platform names (through the web tier, which is the address a source system is
given), the form asks for no key once a role is named, and the saved source
says what its trust policy has to name.
"""
from __future__ import annotations

import json
import urllib.request
import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def fetch(url: str) -> dict:
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


def test_the_issuer_serves_its_discovery_document_and_keys() -> None:
    document = fetch(f"{WEB_BASE}/api/oidc/.well-known/openid-configuration")
    assert document["issuer"] == f"{WEB_BASE}/api/oidc"
    [key] = fetch(document["jwks_uri"])["keys"]
    assert (key["kty"], key["alg"]) == ("RSA", "RS256")


def test_p391_an_s3_source_names_a_role_and_stores_no_key(page, api) -> None:
    mod = Module(api, "OIDC source")
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
    # The header's button, and an empty project's own once the list has loaded.
    page.get_by_role("button", name="Add connection").first.click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="S3 / object storage").click()
    name = f"Landing {uuid.uuid4().hex[:6]}"
    dialog.get_by_label("Connection name").fill(name)
    dialog.get_by_label("Bucket").fill("oidc-landing")
    # Nowhere that answers, so the saved source's test fails fast rather than
    # reaching out.
    dialog.get_by_label("Endpoint Url").fill("http://127.0.0.1:9")
    expect(dialog.get_by_label("access_key_id")).to_be_visible()
    dialog.get_by_label("OpenID Connect role ARN").fill(
        "arn:aws:iam::123456789012:role/anchor-reader")
    expect(dialog.get_by_test_id("connection-oidc-note")).to_be_visible()
    expect(dialog.get_by_label("access_key_id")).to_have_count(0)
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_contain_text("was saved, but the test failed", timeout=60000)
    expect(dialog).to_contain_text("could not trade the OpenID Connect token")
    dialog.get_by_role("button", name="Done").click()

    row = page.locator("tr", has_text=name)
    trust = row.get_by_test_id("connection-oidc")
    expect(trust).to_contain_text(f"{WEB_BASE}/api/oidc")
    expect(trust).to_contain_text("sts.amazonaws.com")
    expect(trust).to_contain_text("connection.")
