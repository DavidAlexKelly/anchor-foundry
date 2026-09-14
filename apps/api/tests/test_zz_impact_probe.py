from __future__ import annotations
import os, sys, uuid
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_probe(client: TestClient, fx: Fixture) -> None:
    auth_mw.clear_identity_cache()
    base = f"/api/workspaces/{fx.workspace}"
    tag = uuid.uuid4().hex[:6]
    made = client.post(f"{base}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"imp_{tag}", "display_name": "Imp",
              "properties": [{"api_name": "code", "data_type": "string"},
                             {"api_name": "labels", "data_type": "string"}],
              "title_property": "code"})
    assert made.status_code == 201, made.text
    r = client.post(f"{base}/object-types/{made.json()['id']}/impact",
        headers=hdr(fx.editor_sub),
        json={"display_name": "Imp",
              "properties": [{"api_name": "code", "data_type": "string"},
                             {"api_name": "labels", "data_type": "array",
                              "array_of": "integer"}]})
    print("IMPACT:", r.status_code, r.text[:500])
    assert r.status_code == 200, r.text
