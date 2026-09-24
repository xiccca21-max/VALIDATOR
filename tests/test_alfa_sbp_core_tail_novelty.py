"""Unknown SBP core/tail/channel/combination never counts towards a verdict.

Live Alfa moved to core 00118 in July 2026 and keeps adding tails while the
atlas corpus is frozen at 2026-06-29 (core∈{00116,00117}).  Novelty in those
slots is an emitter change, not forgery evidence: it must be DIAGNOSTIC only.
Unknown marker/control (tiny categorical fields) stay Tier-B.
"""

from datetime import datetime

from detector.alfa_v2.rules import IGNORED_CODES, SUPPORTING_GROUPS, classify_code
from detector.alfa_v2.sbp import SbpAtlas, validate_sbp_id
from detector.alfa_v2.types import AlfaFlag, PipelineResult
from detector.alfa_v2.verdict import compute_verdict, ingest_flag

# Corpus-shaped atlas: only the old cores/tails and one combination.
ATLAS = SbpAtlas(
    markers=frozenset({"A", "B"}),
    controls=frozenset({"0", "B", "G"}),
    routes=frozenset({"1003"}),
    cores=frozenset({"00116", "00117"}),
    tails=frozenset({"60501"}),
    combinations=frozenset({("A", "B", "1003", "60501")}),
)

# 2026-09-18 = day 261 → calendar 6261, 13:13:06 UTC, reference ends in '0'.
COMPLETION = datetime(2026, 9, 18, 16, 15, 0)


def _opid(marker="A", control="B", route="1003", core="00118", tail="40301"):
    return f"{marker}6261131306ABCDE0{control}{route}{core}{tail}"


def _run(opid):
    res = validate_sbp_id(opid, completion_datetime=COMPLETION, atlas=ATLAS)
    return {f.code: f for f in res.flags}


def _verdict_for(flags):
    result = PipelineResult()
    for f in flags.values():
        ingest_flag(result, AlfaFlag(code=f.code, detail=f.detail, tier=f.tier, group=f.group))
    return compute_verdict(result), result


def test_novelty_code_is_ignored_by_policy():
    assert "ALFA_SBP_PROFILE_NOVELTY" in IGNORED_CODES
    assert classify_code("ALFA_SBP_PROFILE_NOVELTY") == "IGNORE"
    assert "ALFA_SBP_PROFILE_NOVELTY" not in SUPPORTING_GROUPS


def test_unknown_core_tail_combination_is_diagnostic_only():
    flags = _run(_opid())
    assert "ALFA_SBP_EMPIRICAL_PROFILE" not in flags
    novelty = flags["ALFA_SBP_PROFILE_NOVELTY"]
    assert novelty.tier == "DIAGNOSTIC"
    assert "unknown core 00118" in novelty.detail
    assert "unknown tail 40301" in novelty.detail
    assert "combination A/B/1003/40301" in novelty.detail
    # No HARD flags: the id itself is structurally valid.
    assert all(f.tier != "HARD" for f in flags.values()), flags

    (verdict, _, _, evidence), result = _verdict_for(flags)
    assert verdict == "ЧИСТО", evidence
    assert result.supporting_flags == []
    assert any("ALFA_SBP_PROFILE_NOVELTY" in line for line in result.ignored_observations)


def test_unknown_channel_is_diagnostic_only():
    flags = _run(_opid(route="1099", core="00116", tail="60501"))
    assert "ALFA_SBP_EMPIRICAL_PROFILE" not in flags
    assert "unknown channel 1099" in flags["ALFA_SBP_PROFILE_NOVELTY"].detail


def test_novelty_does_not_pair_with_another_b_group_into_fake():
    flags = _run(_opid())
    _, result = _verdict_for(flags)
    # One genuine B1 oddity on top of the novelty must still not reach 2 groups.
    ingest_flag(result, AlfaFlag(code="STREAM_COMPRESSION_RATIO_OUTLIER", detail="x", tier="B"))
    verdict, _, _, _ = compute_verdict(result)
    assert verdict == "ЧИСТО"


def test_unknown_marker_or_control_stays_tier_b():
    flags = _run(_opid(marker="C", core="00116", tail="60501"))
    emp = flags["ALFA_SBP_EMPIRICAL_PROFILE"]
    assert emp.tier == "B"
    assert "unknown marker C" in emp.detail
    assert "unknown core" not in emp.detail

    flags = _run(_opid(control="Z", core="00116", tail="60501"))
    assert "unknown control Z" in flags["ALFA_SBP_EMPIRICAL_PROFILE"].detail
