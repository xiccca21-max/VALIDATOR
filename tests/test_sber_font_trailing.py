from detector.sber_v2.fonts import sfnt_trailing_nonzero


def _font(tail: bytes) -> bytes:
    table = b"abcd"
    # offset of the only table sits just after the 12-byte header and one entry
    offset = 12 + 16
    header = b"\x00\x01\x00\x00" + (1).to_bytes(2, "big") + b"\x00" * 6
    entry = b"test" + b"\x00\x00\x00\x00" + offset.to_bytes(4, "big") + len(table).to_bytes(4, "big")
    return header + entry + table + tail


def test_zero_alignment_is_not_entropy():
    assert sfnt_trailing_nonzero(_font(b"\x00\x00")) == 0


def test_nonzero_bytes_after_last_table_are_entropy():
    assert sfnt_trailing_nonzero(_font(b"\x00\x00" + b"\xea\x4e")) == 2
