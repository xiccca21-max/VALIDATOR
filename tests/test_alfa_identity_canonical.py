"""Alfa identity: first-seen is canonical; clones do not poison originals."""

from detector.alfa_v2.identity import (
    IdentityFields,
    _normal_amount,
    check_identity,
    critical_signature,
)


def _fields(**overrides) -> IdentityFields:
    base = dict(
        operation_id="C160406261736948",
        sbp_id="A61551545348731O0G10080011770901",
        submethod="sbp",
        amount="4000",
        fee="0",
        operation_date="2026-06-04T18:45:37",
        sender="",
        receiver="алина александровна а",
        recipient_bank="озон банк (ozon)",
        destination_requisites="номер телефона получателя=+7 (927) 489-03-91",
    )
    base.update(overrides)
    return IdentityFields(**base)


def test_amount_currency_does_not_change_signature():
    assert _normal_amount("4000") == _normal_amount("4000 RUB") == "4000"
    assert _normal_amount("4 000 RUR") == "4000"
    a = _fields(amount="4000")
    b = _fields(amount="4000 RUB")
    assert critical_signature(a) == critical_signature(b)


def test_clone_does_not_poison_original_recheck(tmp_path):
    db = tmp_path / "id.db"
    original = _fields()
    clone = _fields(destination_requisites="номер телефона получателя=+7 (927) 489-03-90")

    first = check_identity(original, file_id="orig", data_path=db)
    assert not first.conflict

    stolen = check_identity(clone, file_id="clone", data_path=db)
    assert stolen.conflict
    assert stolen.stats.observations_stored == 0

    again = check_identity(original, file_id="orig", data_path=db)
    assert not again.conflict


def test_regenerated_pdf_same_fields_is_clean(tmp_path):
    db = tmp_path / "id.db"
    fields = _fields()
    a = check_identity(fields, file_id="file-a", data_path=db)
    b = check_identity(fields, file_id="file-b", data_path=db)
    assert not a.conflict
    assert not b.conflict


def test_known_fake_does_not_take_first_seen_slot(tmp_path):
    db = tmp_path / "id.db"
    clone = _fields(destination_requisites="номер телефона получателя=+7 (927) 489-03-90")
    original = _fields()

    poisoned = check_identity(clone, file_id="seq", data_path=db, store=False)
    assert not poisoned.conflict
    assert poisoned.stats.observations_stored == 0

    genuine = check_identity(original, file_id="orig", data_path=db)
    assert not genuine.conflict
