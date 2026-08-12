"""Global preflight for ALL banks (including T-Bank) before bank analyzers."""

from __future__ import annotations

from dataclasses import dataclass, field

from .global_rules import run_global_rules


@dataclass
class GlobalPreflightResult:
    hard_fake: bool = False
    flags: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


def run_global_preflight(
    pdf_bytes: bytes,
    *,
    text: str = "",
    bank_key: str = "",
    submethod: str = "",
) -> GlobalPreflightResult:
    out = GlobalPreflightResult()
    gr = run_global_rules(pdf_bytes, text=text, bank_key=bank_key, submethod=submethod)
    out.stats = gr.stats
    out.diagnostics = gr.diagnostics
    for rule_id, code, detail in gr.hard_flags:
        out.hard_fake = True
        out.flags.append(f"[{code}] {detail} (rule={rule_id})")
    return out
