"""Competitor-matching trailing NBSP pad — 0 FP on genuines (max run 1)."""

from detector.alfa_v2.profile_semantics import validate_field_artifacts
from detector.nbsp_padding import CODE, find_trailing_nbsp_padding, trailing_nbsp_count


def test_one_trailing_nbsp_is_clean():
    text = "Получатель\nКирилл Станиславович К\u00a0\nСформирована\n19.08.2026\u00a0\n"
    assert find_trailing_nbsp_padding(text) == []
    codes = {f.code for f in validate_field_artifacts(text).flags}
    assert CODE not in codes


def test_two_trailing_nbsp_on_fio_is_hard():
    text = "Получатель\nКирилл Станиславович К\u00a0\u00a0\u00a0\n"
    hits = find_trailing_nbsp_padding(text)
    assert hits and hits[0].count == 3
    assert hits[0].field == "ФИО"
    codes = {f.code for f in validate_field_artifacts(text).flags}
    assert CODE in codes


def test_formed_and_message_pad_is_hard():
    text = (
        "Сформирована\n19.08.2026 18:33\u00a0\u00a0\n"
        "Сообщение\nперевод\u00a0\u00a0\u00a0\u00a0\n"
    )
    hits = find_trailing_nbsp_padding(text)
    kinds = {h.field for h in hits}
    assert "Сформирована" in kinds
    assert "сообщение" in kinds


def test_trailing_nbsp_count():
    assert trailing_nbsp_count("abc") == 0
    assert trailing_nbsp_count("abc\u00a0") == 1
    assert trailing_nbsp_count("abc\u00a0\u00a0") == 2
