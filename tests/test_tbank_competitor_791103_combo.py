from detector.tbank_v6.stages import _apply_competitor_791103_combo_hard
from detector.tbank_v6.types import PipelineResult


def _mk(codes: list[str], *, content_len: int = 4405, tuple_ok: bool = True) -> PipelineResult:
    r = PipelineResult()
    r.stats["content_profile_check"] = {"content_decoded_len": content_len}
    if tuple_ok:
        r.stats["sbp_content"] = {
            "sbp_link_fields": {
                "route_marker": "0",
                "control": "5",
                "separator": "0",
                "class": "G1",
                "slot": "014",
                "bank5": "00117",
                "suffix": "791103",
            }
        }
    else:
        r.stats["sbp_content"] = {
            "sbp_link_fields": {
                "route_marker": "0",
                "control": "5",
                "separator": "0",
                "class": "G1",
                "slot": "014",
                "bank5": "00117",
                "suffix": "770901",
            }
        }
    r.ignored_observations = [f"[{c}] demo" for c in codes]
    return r


def test_791103_combo_adds_hard():
    r = _mk([
        "TBANK_CONTENT_SKELETON_EXACT_UNKNOWN",
        "TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN",
    ])
    _apply_competitor_791103_combo_hard(r)
    assert "TBANK_COMPETITOR_TUPLE_791103_COMBO_002" in [f.code for f in r.hard_flags]


def test_791103_combo_requires_tuple_and_len():
    r_bad_tuple = _mk(
        ["TBANK_CONTENT_SKELETON_EXACT_UNKNOWN", "TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN"],
        tuple_ok=False,
    )
    _apply_competitor_791103_combo_hard(r_bad_tuple)
    assert "TBANK_COMPETITOR_TUPLE_791103_COMBO_002" not in [f.code for f in r_bad_tuple.hard_flags]

    r_bad_len = _mk(
        ["TBANK_CONTENT_SKELETON_EXACT_UNKNOWN", "TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN"],
        content_len=4383,
    )
    _apply_competitor_791103_combo_hard(r_bad_len)
    assert "TBANK_COMPETITOR_TUPLE_791103_COMBO_002" not in [f.code for f in r_bad_len.hard_flags]
