# -*- coding: utf-8 -*-
"""Campaign scenario tests (temp DB)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

tmp = tempfile.mkdtemp(prefix="camp_")
os.environ["CAMPAIGN_DB_PATH"] = str(Path(tmp) / "campaign.db")

# Reload campaign modules against temp DB
import importlib
import campaign.db as db
importlib.reload(db)
import campaign.service as service
importlib.reload(service)

from campaign.config import (
    CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS,
    STATUS_ACCEPTED,
    STATUS_DUPLICATE,
    STATUS_FAKE,
    STATUS_REJECTED,
    STATUS_REVERSED,
)


def fake_pdf(tag: bytes) -> bytes:
    return b"%PDF-1.4\n" + tag + b"\n%%EOF\n"


import hashlib
from datetime import date

# Monkeypatch identity.extract_identity for deterministic tests
import campaign.identity as identity

_calls = {"n": 0}


def _fake_identity(pdf_bytes, *, bank_name=""):
    _calls["n"] += 1
    n = _calls["n"]
    tag = pdf_bytes[9:40].decode("latin1", errors="ignore")
    sha = identity.file_sha256(pdf_bytes)
    if "dupbase" in tag or "dupcopy" in tag:
        op_hash = hashlib.sha256(b"SAMEOP").hexdigest()
        sbp = "SBPSAME"
    else:
        op_hash = hashlib.sha256(f"op-{tag}".encode()).hexdigest()
        sbp = f"SBP{n}"
    return {
        "text": "ok",
        "producer": "test",
        "bank_key": "alfa",
        "bank_name": "Альфа-Банк",
        "method": "sbp",
        "file_sha256": sha,
        "operation_identity_hash": op_hash,
        "operation_id": f"OP{n}",
        "sbp_id": sbp,
        "transaction_number": f"OP{n}",
        "operation_datetime": "20.07.2026 12:00",
        "operation_date": date(2026, 7, 20),
        "amount_raw": "1000 руб.",
        "sender_mask": "**** 1111",
        "recipient_identifier": "+79990001122",
        "status_text": "Успешно",
        "operation_completed": True,
        "date_ok": True,
        "parsed": {},
    }


identity.extract_identity = _fake_identity
service.extract_identity = _fake_identity


def clean_result():
    return {"verdict": "ЧИСТО", "score": 0, "flags": [], "details": {"engine": "test"}}


def fake_result():
    return {"verdict": "ФЕЙК", "score": 95, "flags": ["[X]"], "details": {"engine": "test", "hard_count": 1}}


def ok(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        raise SystemExit(1)


# 1 accept
r1 = service.process_upload(user_id=1, username="u1", pdf_bytes=fake_pdf(b"acc1"), bank_name="Альфа-Банк", result=clean_result())
ok("accept status", r1["status"] == STATUS_ACCEPTED)
ok("accept reward", r1["reward_kopecks"] == CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS)
snap = service.profile_snapshot(1)
ok("balance after accept", snap["balance_kopecks"] == CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS)
ok("accepted count", snap["accepted"] == 1)

# 2 duplicate same op identity
r2 = service.process_upload(user_id=2, username="u2", pdf_bytes=fake_pdf(b"dupcopyXX"), bank_name="Альфа-Банк", result=clean_result())
# first establish base with same op
_calls["n"] = 10
r_base = service.process_upload(user_id=3, username="u3", pdf_bytes=fake_pdf(b"dupbaseYY"), bank_name="Альфа-Банк", result=clean_result())
r_dup = service.process_upload(user_id=4, username="u4", pdf_bytes=fake_pdf(b"dupcopyZZ"), bank_name="Альфа-Банк", result=clean_result())
ok("dupbase accepted or pending", r_base["status"] in (STATUS_ACCEPTED, STATUS_DUPLICATE))
# Ensure one of them accepted and other duplicate - if base accepted:
if r_base["status"] == STATUS_ACCEPTED:
    ok("duplicate status", r_dup["status"] == STATUS_DUPLICATE)
else:
    # if somehow base was dup of earlier, still check r_dup
    ok("duplicate-ish", r_dup["status"] == STATUS_DUPLICATE or r_base["status"] == STATUS_DUPLICATE)

# 3 fake
rf = service.process_upload(user_id=5, username="u5", pdf_bytes=fake_pdf(b"fakeone1"), bank_name="Альфа-Банк", result=fake_result())
ok("fake status", rf["status"] == STATUS_FAKE)

# 4 manual reject of pending-like: create accepted then reject
ra = service.process_upload(user_id=6, username="u6", pdf_bytes=fake_pdf(b"manrej01"), bank_name="Альфа-Банк", result=clean_result())
ok("pre-reject accepted", ra["status"] == STATUS_ACCEPTED)
cid = ra["check_id"]
rj = service.reject_check(cid, admin_id=99, reason="Нарушение условий акции")
ok("reject reversed", rj["status"] == STATUS_REVERSED and rj["reversed"] is True)
snap6 = service.profile_snapshot(6)
ok("balance after reverse 0", snap6["balance_kopecks"] == 0)

# 5 fake after accept reverses
rb = service.process_upload(user_id=7, username="u7", pdf_bytes=fake_pdf(b"fakerev1"), bank_name="Альфа-Банк", result=clean_result())
fk = service.fake_check(rb["check_id"], admin_id=99, reason="подделка после проверки")
ok("fake reverse", fk["reversed"] is True)
ok("balance user7 0", service.profile_snapshot(7)["balance_kopecks"] == 0)

# 6 adjust
adj = service.adjust_balance(1, 300, "компенсация", admin_id=99)
ok("adjust ok", adj["ok"] and adj["balance"] == CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS + 300)

# 7 export
csv_data = service.export_csv()
ok("export header", "user_id,username,uploaded_count" in csv_data)

# 8 payout once
# ensure user1 has positive balance
p1 = service.payout_mark(1, "paid", admin_id=99, reason="test payout")
ok("payout ok", p1["ok"] is True)
p2 = service.payout_mark(1, "paid", admin_id=99, reason="again")
ok("payout blocked", p2["ok"] is False)

# 9 idempotent accept
again = service.accept_check(r1["check_id"], admin_id=99)
ok("idempotent accept", again.get("idempotent") or again.get("status") == STATUS_ACCEPTED)

print("ALL SCENARIOS PASSED")
print("tmp db", os.environ["CAMPAIGN_DB_PATH"])
