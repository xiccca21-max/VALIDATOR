"""Shared result types for VTB v2."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VtbFlag:
    code: str
    detail: str
    tier: str = "HARD"  # HARD | KNOWN | B | DIAGNOSTIC | IGNORE
    group: str = ""
    rule_id: str = ""

    def format(self) -> str:
        return f"[{self.code}] {self.detail}"


@dataclass
class PipelineResult:
    file_hash: str = ""
    analysis_complete: bool = True
    not_vtb_receipt: bool = False
    cross_document_identity_conflict: bool = False
    new_coherent_profile: bool = False

    hard_flags: list[VtbFlag] = field(default_factory=list)
    known_fake_flags: list[VtbFlag] = field(default_factory=list)
    supporting_flags: list[VtbFlag] = field(default_factory=list)
    ignored_observations: list[str] = field(default_factory=list)
    completed_checks: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    subtype: str = ""
    generator_path: str = ""
    profile_version: str = "vtb_openhtml_v1"
