"""Every base image is pinned by digest (§818).

STATUS.md §20 found what a mutable tag costs: the migration Lambda's bundling
image resolved to a new digest between two deploys of one commit, which
changed the bundled asset's hash and collided with `AlreadyExists`, for no
change in this repository. A service image built from `python:3.12-slim`
alone is the same risk, quieter: two builds of one commit, two base images.

Read as text, so it needs neither Docker nor the network; whether each pin
is still its tag's latest is `scripts/pin-images.sh --check`'s question.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PINNED = re.compile(r"^FROM\s+(?:--platform=\S+\s+)?[^\s@:]+(?:/[^\s@:]+)*:[^\s@]+@sha256:[0-9a-f]{64}(\s|$)")


def dockerfiles() -> list[Path]:
    return sorted(p for p in ROOT.rglob("Dockerfile*")
                  if "node_modules" not in p.parts and ".git" not in p.parts)


def from_lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line.startswith("FROM ")]


def test_every_base_image_names_its_tag_and_digest() -> None:
    files = dockerfiles()
    # The five this repository builds, so a moved or renamed one is noticed
    # rather than silently leaving the check with nothing to look at.
    assert {str(p.relative_to(ROOT)) for p in files} >= {
        "apps/api/Dockerfile", "apps/worker/Dockerfile", "apps/web/Dockerfile",
        "apps/control-plane/Dockerfile",
        "infra/cdk/src/constructs/migration-bundling/Dockerfile",
    }
    unpinned = [f"{p.relative_to(ROOT)}: {line}" for p in files for line in from_lines(p)
                if not PINNED.match(line)]
    assert unpinned == [], unpinned


def test_one_tag_is_one_digest_everywhere() -> None:
    """Three images build from `python:3.12-slim`; pinned to three different
    builds, "the same base" would not be."""
    seen: dict[str, set[str]] = {}
    for path in dockerfiles():
        for line in from_lines(path):
            m = re.search(r"(\S+:\S+)@(sha256:[0-9a-f]{64})", line)
            if m:
                seen.setdefault(m.group(1), set()).add(m.group(2))
    assert {tag: d for tag, d in seen.items() if len(d) > 1} == {}


def test_the_pattern_refuses_a_tag_alone() -> None:
    assert not PINNED.match("FROM --platform=linux/amd64 python:3.12-slim AS base")
    assert not PINNED.match("FROM python@sha256:" + "a" * 64)
    assert PINNED.match("FROM public.ecr.aws/sam/build-python3.12:latest@sha256:" + "a" * 64)
