"""What an inviter is told when Cognito refuses an invitation (§866)."""
from __future__ import annotations

import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib.errors import ConflictError  # noqa: E402
from src.services import orgs  # noqa: E402


def refused(code: str, message: str = "said Cognito") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "AdminCreateUser")


class Pool:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def admin_create_user(self, **_):
        raise self.error


def invite(error: Exception) -> Exception:
    gateway = orgs.Boto3CognitoGateway.__new__(orgs.Boto3CognitoGateway)
    gateway._client = Pool(error)
    gateway._user_pool_id = "pool"
    with pytest.raises(Exception) as caught:
        gateway.admin_create_user("new@example.com", "New")
    return caught.value


def test_the_daily_email_limit_says_so_and_what_fixes_it() -> None:
    raised = invite(refused("LimitExceededException"))
    assert isinstance(raised, orgs.InviteRefused) and raised.status_code == 503
    assert "daily limit" in raised.detail and "inviteFromEmail" in raised.detail


def test_an_email_that_already_signs_in_is_a_conflict() -> None:
    assert isinstance(invite(refused("UsernameExistsException")), ConflictError)


def test_a_refused_address_is_the_inviters_to_fix() -> None:
    raised = invite(refused("InvalidParameterException", "Invalid email address format."))
    assert raised.status_code == 422 and "Invalid email address format." in raised.detail


def test_anything_else_is_still_a_fault() -> None:
    raised = invite(refused("InternalErrorException"))
    assert isinstance(raised, ClientError)
