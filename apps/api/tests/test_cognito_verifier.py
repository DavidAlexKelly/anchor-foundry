"""The production token verifier, tested as itself (§839).

Every other test signs in through `test_api.LocalVerifier`, a copy of these
checks keyed to a test keypair - so `CognitoTokenVerifier` had no test of its
own, and an ID-token branch in it that could never run went unseen. Here the
real class verifies, with only Cognito's key set swapped for a local one.
"""
from __future__ import annotations

import os
import sys
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib.config import Settings  # noqa: E402
from src.lib.errors import UnauthorizedError  # noqa: E402
from src.middleware.auth import CognitoTokenVerifier  # noqa: E402

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CLIENT = "the-app-client"


class Keys:
    """Stands in for `PyJWKClient`: one signing key, whatever the token says."""

    class _Key:
        key = KEY.public_key()

    def get_signing_key_from_jwt(self, token: str):
        return self._Key()


@pytest.fixture
def verifier() -> CognitoTokenVerifier:
    settings = Settings(database_url="postgresql+psycopg://x/y", cognito_region="eu-west-2",
                        cognito_user_pool_id="eu-west-2_pool", cognito_client_id=CLIENT)
    made = CognitoTokenVerifier(settings)
    made._jwks = Keys()
    return made


def token(verifier: CognitoTokenVerifier, *, key=KEY, algorithm="RS256", **overrides) -> str:
    claims = {"sub": "someone", "iss": verifier._settings.issuer, "token_use": "access",
              "client_id": CLIENT, "exp": int(time.time()) + 600, **overrides}
    claims = {k: v for k, v in claims.items() if v is not None}
    return pyjwt.encode(claims, key, algorithm=algorithm)


def refused(verifier: CognitoTokenVerifier, raw: str) -> str:
    with pytest.raises(UnauthorizedError) as caught:
        verifier.verify(raw)
    return str(caught.value)


def test_an_access_token_for_this_client_is_accepted(verifier) -> None:
    assert verifier.verify(token(verifier))["sub"] == "someone"


def test_another_clients_access_token_is_refused(verifier) -> None:
    assert "client mismatch" in refused(verifier, token(verifier, client_id="someone-else"))


def test_an_id_token_is_refused_even_for_this_client(verifier) -> None:
    """What the removed branch would have accepted, had it been reachable."""
    raw = token(verifier, token_use="id", client_id=None, aud=CLIENT)
    assert "invalid token" in refused(verifier, raw)
    # And one without an `aud` to trip on is refused by its kind.
    assert "unrecognised token_use" in refused(
        verifier, token(verifier, token_use="id", client_id=None))


def test_a_token_of_no_kind_is_refused(verifier) -> None:
    assert "unrecognised token_use" in refused(verifier, token(verifier, token_use=None))


def test_what_the_signature_and_claims_must_say(verifier) -> None:
    assert "ExpiredSignature" in refused(verifier, token(verifier, exp=int(time.time()) - 5))
    assert "InvalidIssuer" in refused(verifier, token(verifier, iss="https://elsewhere"))
    assert "InvalidSignature" in refused(verifier, token(verifier, key=OTHER_KEY))
    assert "invalid token" in refused(verifier, token(verifier, sub=None))


def test_only_rs256_is_accepted(verifier) -> None:
    """A token signed with a shared secret is not a Cognito token, whatever
    secret it names - the algorithm list is the guard against that."""
    raw = pyjwt.encode({"sub": "x", "iss": verifier._settings.issuer, "token_use": "access",
                        "client_id": CLIENT, "exp": int(time.time()) + 60},
                       "a" * 32, algorithm="HS256")
    assert "invalid token" in refused(verifier, raw)
