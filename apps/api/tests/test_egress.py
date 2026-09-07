"""Which destinations a source may reach (decision 0013; §263).

No database and no socket: `services/egress` is the half where a wrong answer
is a line. The rows are `test_egress_policies.py`; the four call sites that
actually make requests are in the connector and webhook suites.

`data-connection` pages are `p.N`.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import egress  # noqa: E402


def policy(host: str, port: int | None = None, description: str = "") -> dict:
    return {"host": host, "port": port, "description": description}


# ---- what may be saved -----------------------------------------------------------
def test_a_policy_naming_a_host_is_accepted() -> None:
    assert egress.parse({"host": "api.example.com"})["host"] == "api.example.com"


def test_a_host_is_lowercased_rather_than_refused() -> None:
    """A hostname is case-insensitive, so `API.example.com` means the host —
    and a policy that stored it as typed would not match a call to
    `api.example.com`, which is a guard with a one-keystroke bypass."""
    assert egress.parse({"host": "API.Example.COM"})["host"] == "api.example.com"


def test_an_address_is_a_destination_too() -> None:
    """p.103 pushes towards names — "use this ad-hoc domain instead of
    `10.0.0.1`" — but "this one host" is a legitimate thing to say, and
    refusing it would refuse the case p.103 is describing the workaround for."""
    assert egress.parse({"host": "10.0.0.1"})["host"] == "10.0.0.1"


def test_a_range_is_refused_and_the_message_says_what_to_write_instead() -> None:
    """Decision 0013's last exclusion. A range is what somebody writes when
    they do not know the names, and it invites the allowlist to be widened
    until it means nothing — so the refusal has to offer the alternative or it
    is just an obstacle."""
    with pytest.raises(egress.EgressError) as caught:
        egress.parse({"host": "10.0.0.0/8"})
    assert "not a range" in str(caught.value)
    assert "name each host" in str(caught.value)


def test_something_that_is_not_a_host_is_refused() -> None:
    for host in ("", "   ", "http://api.example.com", "api example.com", "-lead"):
        with pytest.raises(egress.EgressError):
            egress.parse({"host": host})


def test_a_policy_may_name_a_port() -> None:
    assert egress.parse({"host": "api.example.com", "port": "443"})["port"] == 443


def test_a_policy_without_a_port_says_nothing_about_ports() -> None:
    """**Not port zero, and not a refusal.** A person who names a host and no
    port has said nothing about ports; reading that silence as a restriction
    would refuse the call they were trying to allow."""
    assert egress.parse({"host": "api.example.com"})["port"] is None
    assert egress.parse({"host": "api.example.com", "port": ""})["port"] is None


def test_something_that_is_not_a_port_is_refused() -> None:
    for port in ("http", 0, 65536, -1):
        with pytest.raises(egress.EgressError):
            egress.parse({"host": "api.example.com", "port": port})


# ---- what is permitted -----------------------------------------------------------
def test_a_policy_allows_the_host_it_names() -> None:
    found = egress.permitted([policy("api.example.com")], "api.example.com", 443)
    assert found is not None and found["host"] == "api.example.com"


def test_a_policy_does_not_allow_another_host() -> None:
    assert egress.permitted([policy("api.example.com")], "evil.example.com", 443) is None


def test_the_host_comparison_ignores_case_on_both_sides() -> None:
    # The store lowercases on the way in, so a stored upper-case host should be
    # impossible — but the comparison is the guard and a guard that depends on
    # another layer having been careful is a guard with a condition on it.
    assert egress.permitted([policy("API.EXAMPLE.COM")], "api.example.com", 443)
    assert egress.permitted([policy("api.example.com")], "API.example.com", 443)


def test_a_policy_with_no_port_allows_any_port() -> None:
    for port in (80, 443, 8443, None):
        assert egress.permitted([policy("api.example.com")], "api.example.com", port)


def test_a_policy_with_a_port_allows_only_that_one() -> None:
    """The whole reason the column exists — and both halves, because the
    refusal alone passes against an implementation that refuses every port."""
    allowed = [policy("api.example.com", 443)]
    assert egress.permitted(allowed, "api.example.com", 443) is not None
    assert egress.permitted(allowed, "api.example.com", 8443) is None


def test_a_port_scoped_policy_refuses_a_call_that_named_no_port() -> None:
    # "Any port" is not one of the ports a policy for 443 allows: a caller that
    # could not say which port it was using has not shown it is using 443.
    assert egress.permitted([policy("api.example.com", 443)], "api.example.com", None) is None


def test_the_first_matching_policy_is_the_one_returned() -> None:
    # It is returned rather than a boolean so a refusal can name what was
    # consulted; which of several equally-matching policies is arbitrary, and
    # that it is *one of them* is the claim.
    allowed = [policy("api.example.com", 443, "the API"), policy("api.example.com")]
    assert egress.permitted(allowed, "api.example.com", 443) in allowed


# ---- what check decides ----------------------------------------------------------
def test_no_policies_means_unrestricted() -> None:
    """Decision 0013 §2, and the one place it is decided.

    Foundry's model is closed; this platform has sources that already exist
    whose authors were never asked for a policy, and no migration can guess
    their destinations without producing a list that is *almost* right.
    """
    egress.check([], "anything.example.com", 443)


def test_one_policy_restricts_everything_else() -> None:
    """The other half, and the pair is the feature: adding a single policy is
    what turns the allowlist on."""
    egress.check([policy("api.example.com")], "api.example.com", 443)
    with pytest.raises(egress.EgressRefused):
        egress.check([policy("api.example.com")], "evil.example.com", 443)


def test_a_refusal_names_the_destination_and_what_is_allowed() -> None:
    """Decision 0013 §4: "could not reach X" sends somebody to check DNS, a
    firewall and the far end's health before they think to look at a list in
    the platform."""
    with pytest.raises(egress.EgressRefused) as caught:
        egress.check(
            [policy("api.example.com", 443, "the vendor API")],
            "evil.example.com", 8080,
        )
    said = str(caught.value)
    assert "evil.example.com:8080" in said
    assert "api.example.com:443" in said
    assert "the vendor API" in said


def test_a_refusal_is_not_a_failure_to_reach() -> None:
    """Its own class, because the four call sites report the two differently —
    nothing was attempted, and saying "could not reach" would start the wrong
    investigation."""
    assert not issubclass(egress.EgressRefused, egress.EgressError)


# ---- the port a URL means --------------------------------------------------------
def test_a_scheme_supplies_the_port_a_url_left_out() -> None:
    """`https://api.example.com/x` and `https://api.example.com:443/x` are the
    same destination. Reading the first as "no port" would make every
    port-scoped policy fail against the ordinary way people write URLs."""
    assert egress.port_for("https", None) == 443
    assert egress.port_for("http", None) == 80


def test_an_explicit_port_wins_over_the_scheme() -> None:
    assert egress.port_for("https", 8443) == 8443


def test_an_unknown_scheme_supplies_nothing() -> None:
    # Which `check` reads as "no port stated", so a port-scoped policy refuses
    # it — the safe direction for a scheme this function has never heard of.
    assert egress.port_for("ftp", None) is None
    assert egress.permitted(
        [policy("api.example.com", 21)], "api.example.com", egress.port_for("ftp", None)
    ) is None


# ---- how the policies reach the guard --------------------------------------------
def test_nothing_in_scope_is_unrestricted() -> None:
    """The failure mode of a forgotten call site, asserted rather than assumed.

    A path that forgets `restricted_to` leaves the platform exactly as it was
    before this feature — which for an opt-in control is the right direction,
    and is why every outbound path has its own test that the policies actually
    arrive.
    """
    assert egress.current() == []
    egress.check_current("anything.example.com", 443)


def test_a_scope_restricts_and_then_lets_go() -> None:
    """Reset on the way out, because the same worker thread serves the next
    operation and a leaked allowlist would refuse a *different* source's
    destinations — a failure that looks like the second source being
    misconfigured."""
    with egress.restricted_to([policy("api.example.com")]):
        egress.check_current("api.example.com", 443)
        with pytest.raises(egress.EgressRefused):
            egress.check_current("evil.example.com", 443)
    egress.check_current("evil.example.com", 443)


def test_a_nested_scope_does_not_leak_outwards() -> None:
    with egress.restricted_to([policy("outer.example.com")]):
        with egress.restricted_to([policy("inner.example.com")]):
            egress.check_current("inner.example.com", 443)
        egress.check_current("outer.example.com", 443)
        with pytest.raises(egress.EgressRefused):
            egress.check_current("inner.example.com", 443)


# ---- the worker's copy -----------------------------------------------------------
def test_the_worker_runs_the_same_egress_rules_byte_for_byte() -> None:
    """**The worker has its own copy of the connectors, deliberately.**

    `anchor_worker/connectors.py` says why in its own docstring: "api and
    worker are independently deployable images with no shared Python package in
    this build", and it already warns to "keep in step with the API's registry".
    So a scheduled sync — the one outbound path with no caller at all — reaches
    external systems through code this suite does not otherwise touch.

    Duplicating a *security* rule is §191's mirror with the worst possible
    stakes: two copies free to be identically wrong, and the one that drifts
    stops refusing without anything failing to compile. So the guard is not
    reimplemented there, it is the **same file**, and this asserts that
    literally rather than asserting the two behave alike.

    Byte-for-byte on purpose. "They agree on the cases I thought of" is what a
    behavioural comparison buys; "they are the same file" is what stops the
    case nobody thought of from differing.
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    api = open(os.path.join(root, "api", "src", "services", "egress.py"), "rb").read()
    worker = open(
        os.path.join(root, "worker", "src", "anchor_worker", "egress.py"), "rb"
    ).read()
    assert api == worker, (
        "apps/worker/src/anchor_worker/egress.py has drifted from "
        "apps/api/src/services/egress.py - copy it across rather than editing "
        "one of them"
    )


def test_every_outbound_path_in_the_worker_is_guarded() -> None:
    """The four chokepoints in the worker's connectors, asserted by name.

    A path added there without a guard is the failure mode
    `egress.restricted_to` fails *open* on — it would reach anything, silently,
    forever. This is the check that a new connector cannot be added to the
    worker without somebody meeting this test.
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source = open(
        os.path.join(root, "worker", "src", "anchor_worker", "connectors.py"),
        encoding="utf-8",
    ).read()
    # One per outbound path: Postgres, MySQL, the REST page fetch, and the
    # OAuth token fetch that is a second destination (p.12).
    assert source.count("egress.check_current(") == 4, (
        "the worker's connectors have a number of egress guards this test does "
        "not expect - a new outbound path needs one, and a removed one needs "
        "this number changed on purpose"
    )
