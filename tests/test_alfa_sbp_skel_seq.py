"""Confirmed SEQ Oracle batch is pinned by file SHA, not size holes."""

from pathlib import Path

from detector.alfa import analyze
from detector.alfa_v2.known_signatures import KNOWN_FAKE_FILE_SHA256
from detector.alfa_v2.rules import HARD_CODES

DOWNLOADS = Path(r"C:\Users\fanis\Downloads\Telegram Desktop")
SEQ18 = [
    "alfa_sbp_155955.pdf", "alfa_sbp_160035.pdf", "alfa_sbp_160108.pdf",
    "alfa_sbp_160152.pdf", "alfa_sbp_160217.pdf", "alfa_sbp_160237.pdf",
    "alfa_sbp_160303.pdf", "alfa_sbp_160333.pdf", "alfa_sbp_160353.pdf",
    "alfa_sbp_160412.pdf", "alfa_sbp_160435.pdf", "alfa_sbp_160454.pdf",
    "alfa_sbp_160521.pdf", "alfa_sbp_160601.pdf", "alfa_sbp_160618.pdf",
    "alfa_sbp_160646.pdf", "alfa_sbp_160705.pdf", "alfa_sbp_160740.pdf",
]


def test_skel_seq_size_holes_not_hard():
    assert "ALFA_ORACLE_SBP_SKEL_SEQ" not in HARD_CODES


def test_seq18_known_file_sha():
    hits = 0
    for name in SEQ18:
        path = DOWNLOADS / name
        if not path.is_file():
            continue
        hits += 1
        result = analyze(path.read_bytes())
        flags = result.get("flags") or []
        assert result["verdict"] == "ФЕЙК", (name, flags)
        assert any("ALFA_KNOWN_FAKE_SIGNATURE" in str(flag) for flag in flags), (
            name,
            flags,
        )
    if hits:
        assert hits >= 18
        assert len(KNOWN_FAKE_FILE_SHA256) >= 18 + 3
