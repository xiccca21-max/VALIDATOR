from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AlfaFlag:
    code: str
    detail: str
    tier: str = "HARD"
    rule_id: str = ""
    group: str = ""

    def format(self) -> str:
        return f"[{self.code}] {self.detail}"


@dataclass
class PipelineResult:
    file_hash: str = ""
    analysis_complete: bool = True
    not_alfa_receipt: bool = False
    cross_document_identity_conflict: bool = False
    new_coherent_profile: bool = False

    hard_flags: list[AlfaFlag] = field(default_factory=list)
    known_fake_flags: list[AlfaFlag] = field(default_factory=list)
    diagnostics: list[AlfaFlag] = field(default_factory=list)
    completed_checks: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    channel: str = ""
    receipt_subtype: str = ""
    generator_path: str = ""
