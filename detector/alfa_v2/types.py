"""Shared, verdict-neutral result types for Alfa v2 forensic modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ForensicFlag:
    code: str
    detail: str
    tier: str = "HARD"
    group: str = ""
    object_number: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ForensicResult:
    flags: list[ForensicFlag] = field(default_factory=list)
    diagnostics: list[ForensicFlag] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def add(
        self,
        code: str,
        detail: str,
        *,
        tier: str = "HARD",
        group: str = "",
        object_number: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        flag = ForensicFlag(
            code=code,
            detail=detail,
            tier=tier,
            group=group,
            object_number=object_number,
            evidence=evidence or {},
        )
        (self.diagnostics if tier == "DIAGNOSTIC" else self.flags).append(flag)


@dataclass
class AlfaFlag:
    """One normalized Alfa v2 observation."""

    code: str
    detail: str
    tier: str = "HARD"
    group: str = ""
    rule_id: str = ""

    def format(self) -> str:
        return f"[{self.code}] {self.detail}"


@dataclass
class PipelineResult:
    """Shared result assembled by the Alfa v2 analysis stages."""

    file_hash: str = ""
    analysis_complete: bool = True
    not_alfa_receipt: bool = False
    cross_document_identity_conflict: bool = False

    hard_flags: list[AlfaFlag] = field(default_factory=list)
    known_fake_flags: list[AlfaFlag] = field(default_factory=list)
    supporting_flags: list[AlfaFlag] = field(default_factory=list)
    manual_review_flags: list[AlfaFlag] = field(default_factory=list)
    ignored_observations: list[str] = field(default_factory=list)
    completed_checks: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    channel: str = ""
    receipt_subtype: str = ""
    generator_path: str = ""
    manual_review_required: bool = False


# A short alias keeps stage code readable and eases migration from generic flags.
V2Flag = AlfaFlag
