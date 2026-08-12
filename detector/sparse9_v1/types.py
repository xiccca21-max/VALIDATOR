from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MbFlag:
    code: str
    detail: str
    tier: str = "HARD"
    rule_id: str = ""
    group: str = ""
    expected: str = ""
    actual: str = ""
    raw_evidence: str = ""

    def format(self) -> str:
        return f"[{self.code}] {self.detail}"


@dataclass
class PipelineResult:
    file_hash: str = ""
    bank_key: str = ""
    analysis_complete: bool = True
    not_bank_receipt: bool = False
    cross_document_identity_conflict: bool = False
    new_coherent_profile: bool = False

    hard_flags: list[MbFlag] = field(default_factory=list)
    known_fake_flags: list[MbFlag] = field(default_factory=list)
    diagnostics: list[MbFlag] = field(default_factory=list)
    completed_checks: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    method: str = ""
    generator_path: str = ""
