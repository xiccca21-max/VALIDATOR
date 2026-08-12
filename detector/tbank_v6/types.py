from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class V6Flag:
    code: str
    detail: str
    tier: str = "A"
    group: str = ""
    rule_id: str = ""

    def format(self) -> str:
        return f"[{self.code}] {self.detail}"


@dataclass
class PipelineResult:
    file_hash: str = ""
    analysis_complete: bool = True
    not_a_tbank_receipt: bool = False
    cross_document_identity_conflict: bool = False

    hard_flags: list[V6Flag] = field(default_factory=list)
    known_fake_flags: list[V6Flag] = field(default_factory=list)
    supporting_flags: list[V6Flag] = field(default_factory=list)
    ignored_observations: list[str] = field(default_factory=list)
    completed_checks: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    channel: str = ""
    receipt_subtype: str = ""
