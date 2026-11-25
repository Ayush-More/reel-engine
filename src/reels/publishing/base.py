"""Publisher interface plus the guard that every publish path must pass through."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts.models import PublishPackage, PublishResult


def blocked_reasons(*, qc_verdict: str | None, approved: bool, require_approval: bool = True,
                    already_published: bool = False) -> list[str]:
    reasons: list[str] = []
    if qc_verdict != "pass":
        reasons.append(f"QC verdict is {qc_verdict!r}, not 'pass'")
    if require_approval and not approved:
        reasons.append("no explicit human approval recorded")
    if already_published:
        reasons.append("idempotency key already published (duplicate guard)")
    return reasons


class Publisher(ABC):
    mode = "dry_run"

    @abstractmethod
    def publish(self, package: PublishPackage, reasons: list[str]) -> PublishResult:
        """Implementations MUST return status='blocked' without any network call when reasons is non-empty."""
