import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import check_history  # noqa: E402


SBER_TEXT = (
    "Чек по операции\n24.09.2026 22:41:07 (МСК)\nПеревод клиенту СберБанка\n"
    "Сумма перевода 45 000,00 ₽\nНомер документа 5493912345\n"
)
SBER_PARSED = {"amount": "45 000,00 ₽"}


def _use_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(check_history, "_PATH", tmp_path / "hist.db")


def test_first_sight_returns_empty_and_no_block(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    prior = check_history.record(b"%PDF-a", SBER_TEXT, SBER_PARSED,
                                 user_id=1, username="alice", bank="Сбер")
    assert prior == []
    assert check_history.format_history(prior) == ""


def test_same_file_second_time_lists_previous_checker(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    check_history.record(b"%PDF-a", SBER_TEXT, SBER_PARSED,
                         user_id=1, username="@alice", bank="Сбер")
    prior = check_history.record(b"%PDF-a", SBER_TEXT, SBER_PARSED,
                                 user_id=2, username="bob", bank="Сбер")
    assert len(prior) == 1
    assert prior[0]["username"] == "alice"
    block = check_history.format_history(prior)
    lines = block.split("\n")
    assert lines[0] == "Чек ранее проверялся:"
    assert lines[1].startswith("- ") and lines[1].endswith(", @alice")
    # "- dd.mm.yyyy hh:mm, @user"
    assert len(lines[1].split(", ")[0]) == len("- 24.09.2026 22:41")


def test_reexported_same_operation_matches_by_op_key(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    check_history.record(b"%PDF-first-export", SBER_TEXT, SBER_PARSED,
                         user_id=1, username="alice")
    prior = check_history.record(b"%PDF-second-export", SBER_TEXT, SBER_PARSED,
                                 user_id=2, username="bob")
    assert [e["username"] for e in prior] == ["alice"]


def test_different_operation_same_receiver_does_not_match(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    other = SBER_TEXT.replace("5493912345", "5493999999")
    check_history.record(b"%PDF-a", SBER_TEXT, SBER_PARSED, user_id=1, username="alice")
    prior = check_history.record(b"%PDF-b", other, SBER_PARSED, user_id=2, username="bob")
    assert prior == []


def test_no_strong_opid_falls_back_to_file_hash_only(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    # Only a bare 20-digit account number: must NOT become an operation key.
    text = "Счёт получателя 40817810099910004312\nСумма 1 000,00 ₽"
    assert check_history.operation_key(text, {"amount": "1 000,00"}) is None
    check_history.record(b"%PDF-x", text, None, user_id=1, username="alice")
    assert check_history.record(b"%PDF-y", text, None, user_id=2, username="bob") == []
    assert len(check_history.record(b"%PDF-x", text, None, user_id=3, username="carol")) == 1


def test_missing_username_shows_id(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    check_history.record(b"%PDF-a", "", None, user_id=777, username=None)
    prior = check_history.record(b"%PDF-a", "", None, user_id=1, username="bob")
    assert check_history.format_history(prior).endswith(", id:777")


def test_kronlead_checks_are_never_recorded_or_shown(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    # kronlead checks first: nothing is stored.
    assert check_history.record(b"%PDF-a", "", None, user_id=5, username="@KronLead") == []
    assert check_history.record(b"%PDF-a", "", None, user_id=1, username="alice") == []
    # kronlead checks again: still sees others, but is not added himself.
    prior = check_history.record(b"%PDF-a", "", None, user_id=5, username="kronlead")
    assert [e["username"] for e in prior] == ["alice"]
    prior = check_history.record(b"%PDF-a", "", None, user_id=2, username="bob")
    assert [e["username"] for e in prior] == ["alice"]
    # Even a stale row with that username is filtered out at display time.
    block = check_history.format_history(
        [{"checked_at": 0.0, "user_id": 5, "username": "kronlead"}]
    )
    assert block == ""


def test_long_history_is_capped(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    for i in range(13):
        check_history.record(b"%PDF-a", "", None, user_id=i, username=f"u{i}")
    prior = check_history.record(b"%PDF-a", "", None, user_id=99, username="last")
    assert len(prior) == 13
    block = check_history.format_history(prior)
    lines = block.split("\n")
    assert lines[1] == "- … и ещё 3 раз ранее"
    assert len(lines) == 2 + check_history.MAX_SHOWN
    assert lines[-1].endswith(", @u12")
