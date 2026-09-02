"""T-Bank B1/013 is a March–May slot, not a June–August graft."""

from detector.tbank_sbp_content import SbpCheckResult, _check_profile_epoch_expiry

_MAY_B1013 = "B6137185128962110B10130011760501"


def _codes(opid: str, text: str) -> set[str]:
    res = SbpCheckResult()
    _check_profile_epoch_expiry(opid, text, res)
    return {flag.code for flag in res.flags}


def test_june_b1013_is_hard():
    assert "SBP_PROFILE_EPOCH_SLOT_CONFLICT" in _codes(
        _MAY_B1013, "15.06.2026 12:00:00",
    )


def test_august_b1013_is_hard():
    assert "SBP_PROFILE_EPOCH_SLOT_CONFLICT" in _codes(
        _MAY_B1013, "10.08.2026 12:00:00",
    )


def test_may_b1013_stays_clean():
    assert "SBP_PROFILE_EPOCH_SLOT_CONFLICT" not in _codes(
        _MAY_B1013, "17.05.2026 12:00:00",
    )


def test_june_g100x_stays_clean():
    june_g1 = "A6163081200000000G10040011779103"
    assert len(june_g1) == 32
    assert "SBP_PROFILE_EPOCH_SLOT_CONFLICT" not in _codes(
        june_g1, "15.06.2026 12:00:00",
    )
