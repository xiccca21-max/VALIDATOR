from detector.tbank_v6.stages import _apply_competitor_018_native_combo_hard
from detector.tbank_v6.types import PipelineResult


REQUIRED = [
    "TBANK_CONTENT_LEN_EXACT_UNKNOWN",
    "TBANK_CONTENT_SKELETON_EXACT_UNKNOWN",
    "TBANK_F1_GLYF_CMAP_EXACT_UNKNOWN",
    "TBANK_F2_GLYF_HEIGHT_EXACT_UNKNOWN",
]


def _result(*, content_len: int = 4432, valid_tuple: bool = True) -> PipelineResult:
    result = PipelineResult()
    result.ignored_observations = [f"[{code}] test" for code in REQUIRED]
    result.stats["content_profile_check"] = {"content_decoded_len": content_len}
    result.stats["sbp_content"] = {
        "sbp_link_fields": {
            "route_marker": "0",
            "control": "H" if valid_tuple else "A",
            "separator": "0",
            "class": "G1",
            "slot": "018",
            "bank5": "00117",
            "suffix": "791103",
        }
    }
    return result


def test_native_slot018_four_way_combo_is_hard():
    for content_len in (4405, 4432, 4436):
        result = _result(content_len=content_len)
        if content_len in (4405, 4436):
            result.ignored_observations = [
                note for note in result.ignored_observations
                if "TBANK_CONTENT_LEN_EXACT_UNKNOWN" not in note
            ]
        _apply_competitor_018_native_combo_hard(result)
        assert "TBANK_COMPETITOR_TUPLE_018_NATIVE_COMBO_004" in [
            flag.code for flag in result.hard_flags
        ]


def test_native_slot018_combo_requires_tuple_length_and_all_signals():
    for result in (_result(content_len=4408), _result(valid_tuple=False)):
        _apply_competitor_018_native_combo_hard(result)
        assert not result.hard_flags

    missing = _result()
    missing.ignored_observations.pop()
    _apply_competitor_018_native_combo_hard(missing)
    assert not missing.hard_flags
