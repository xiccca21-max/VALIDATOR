"""K-TBANK-SBP-LINKED-TUPLE-001 synthetic regression."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector.tbank_sbp_content import validate_tbank_sbp_id
from detector.tbank_v6.rules import classify_code


def _opid(route_marker: str) -> str:
    # [0] lead, [1:11] UTC core, [11:14] ref3, [14] marker, [15] control,
    # [16] separator, [17:19] class, [19:22] slot, [22:26] profile,
    # [26:32] suffix.
    value = (
        "A"
        "6197112249"
        "623"
        f"{route_marker}"
        "1"
        "0"
        "B1"
        "013"
        "0011"
        "760501"
    )
    assert len(value) == 32
    return value


def _codes(route_marker: str) -> set[str]:
    result = validate_tbank_sbp_id(
        _opid(route_marker),
        "",
        b"",
        producer="OpenPDF 1.3.30.jaspersoft.2",
        creator="JasperReports Library version 6.20.3",
    )
    return {flag.code for flag in result.flags}


def main() -> int:
    failures: list[str] = []
    code = "SBP_LINKED_TUPLE_CONFLICT"

    if classify_code(code) != "A":
        failures.append(f"{code}: tier={classify_code(code)!r}, expected 'A'")

    for marker in ("8", "2", "3"):
        if code not in _codes(marker):
            failures.append(
                f"marker={marker}, control=1, slot=013, suffix=760501: "
                f"missing {code}"
            )

    if code in _codes("1"):
        failures.append(
            "marker=1, control=1, slot=013, suffix=760501: "
            f"unexpected {code}"
        )

    if failures:
        print("FAIL", len(failures))
        for item in failures:
            print(" ", item)
        return 1

    print("PASS linked tuple regression (4 cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
