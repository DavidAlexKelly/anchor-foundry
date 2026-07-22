"""Version update manager (spec §7: control-plane/src/updater; §6 "Updates").

Customers can trigger updates from their admin panel; we trigger fleet-wide
updates when a version ships. Enterprise customers pin versions — a pinned
customer is skipped by fleet rollouts and only updates on explicit request.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..provisioner.provisioner import Provisioner
from ..registry.registry import StackRegistry, StackStatus

logger = logging.getLogger("control_plane.updater")


@dataclass(frozen=True)
class UpdateResult:
    org_slug: str
    updated: bool
    reason: str


class Updater:
    def __init__(self, registry: StackRegistry, provisioner: Provisioner) -> None:
        self._registry = registry
        self._provisioner = provisioner

    def update_customer(
        self, org_slug: str, target_tag: str, *, requested_by_customer: bool = False,
        pinned_version: str | None = None,
    ) -> UpdateResult:
        record = self._registry.get(org_slug)
        if record.stack_status not in (StackStatus.READY, StackStatus.FAILED):
            return UpdateResult(org_slug, False, f"stack is {record.stack_status.value}")
        if record.stack_version == target_tag:
            return UpdateResult(org_slug, False, "already at target version")
        if pinned_version is not None and not requested_by_customer:
            # §6: enterprise customers pin and update on their own schedule.
            return UpdateResult(org_slug, False, f"pinned to {pinned_version}")
        self._provisioner.update_stack(org_slug, target_tag)
        return UpdateResult(org_slug, True, f"updated to {target_tag}")
