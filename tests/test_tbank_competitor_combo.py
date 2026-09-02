from detector.tbank_v6.stages import _apply_competitor_combo_hard
from detector.tbank_v6.types import PipelineResult


def _result_with_codes(codes: list[str]) -> PipelineResult:
    r = PipelineResult()
    r.stats["content_profile_check"] = {"content_decoded_len": 4402}
    r.stats["reassembly_family_v3"] = {"f1_glyf_len": 13000, "f2_glyf_len": 1474}
    r.stats["sbp_content"] = {"sbp_link_fields": {"bank5": "00117", "suffix": "791103"}}
    r.ignored_observations = [f"[{c}] demo" for c in codes]
    return r


def test_competitor_combo_adds_hard_flag():
    r = _result_with_codes([
        "TBANK_CONTENT_LEN_EXACT_UNKNOWN",
        "TBANK_F1_TWIN_SHAPE_MISMATCH",
        "TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH",
        "TBANK_F1_GLYF_SIZE_MULTISET_MISMATCH",
    ])
    _apply_competitor_combo_hard(r)
    codes = [f.code for f in r.hard_flags]
    assert "TBANK_COMPETITOR_NOVELTY_COMBO_001" in codes


def test_competitor_combo_requires_all_four():
    r = _result_with_codes([
        "TBANK_CONTENT_LEN_EXACT_UNKNOWN",
        "TBANK_F1_TWIN_SHAPE_MISMATCH",
        "TBANK_F1_GLYF_SHAPE_ENVELOPE_MISMATCH",
    ])
    _apply_competitor_combo_hard(r)
    codes = [f.code for f in r.hard_flags]
    assert "TBANK_COMPETITOR_NOVELTY_COMBO_001" not in codes
