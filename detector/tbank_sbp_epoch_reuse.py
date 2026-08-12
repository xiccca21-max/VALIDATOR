"""Corpus-backed SBP epoch and receipt-stem linkage checks."""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .sbp_cipher import extract_receipt_datetime


EPOCH_RULE_ID = "T-TBANK-SBP-PROFILE-EPOCH-001"
EPOCH_EARLY_RULE_ID = "T-TBANK-SBP-PROFILE-EPOCH-EARLY-001"
STEM_RULE_ID = "T-TBANK-RECEIPT-STEM-REUSE-001"
EPOCH_CODE = "SBP_PROFILE_EPOCH_MISMATCH"
EPOCH_EARLY_CODE = "SBP_PROFILE_EPOCH_TOO_EARLY"
STEM_CODE = "RECEIPT_STEM_REUSE_CONFLICT"
_DATA_PATH = Path(__file__).with_name("atlas_data") / "tbank_sbp_epoch_stems.json"
_RECEIPT_RE = re.compile(r"1-\d{3}-\d{3}-\d{3}-\d{3}")
_HISTORICAL_GAP_DAYS = 21
# Early-use HARD: profile first seen in corpus only after this many samples,
# and receipt/ID dates must precede first_date by at least this margin.
# (SEQ 180630/656/662: G1|00117|791103 first=2026-06-29, receipt=2026-04-21.)
_EARLY_MIN_SAMPLES = 5
_EARLY_MIN_LEAD_DAYS = 14


@dataclass
class EpochReuseFlag:
    code: str
    detail: str
    rule_id: str
    tier: str = "B"


@dataclass
class EpochReuseResult:
    flags: list[EpochReuseFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _load_data() -> dict:
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _decode_id_msk(opid: str, visible: datetime.datetime) -> datetime.datetime | None:
    if len(opid) != 32 or not opid[1:11].isdigit():
        return None
    if int(opid[1]) != visible.year % 10:
        return None
    try:
        utc = datetime.datetime(
            visible.year,
            1,
            1,
            int(opid[5:7]),
            int(opid[7:9]),
            int(opid[9:11]),
        )
        utc += datetime.timedelta(days=int(opid[2:5]) - 1)
        return utc + datetime.timedelta(hours=3)
    except ValueError:
        return None


def check_sbp_epoch_and_receipt_stem(
    opid: str,
    text: str,
) -> EpochReuseResult:
    out = EpochReuseResult()
    data = _load_data()
    if not data:
        out.stats["skipped"] = "corpus_index_missing"
        return out

    visible_dt = extract_receipt_datetime(text, prefer_first_line=True)
    id_msk = _decode_id_msk(opid, visible_dt) if visible_dt else None
    receipt_match = _RECEIPT_RE.search(text or "")
    receipt = receipt_match.group(0) if receipt_match else ""
    out.stats.update({
        "visible_datetime": visible_dt.isoformat(sep=" ") if visible_dt else "",
        "id_msk": id_msk.isoformat(sep=" ") if id_msk else "",
        "receipt_number": receipt,
    })

    if len(opid) == 32 and visible_dt and id_msk:
        sb_class = opid[17:19]
        bank5 = opid[22:27]
        suffix = opid[26:32]
        profile_key = f"{sb_class}|{bank5}|{suffix}"
        profile = (data.get("profiles") or {}).get(profile_key)
        corpus_last_raw = data.get("corpus_last_date", "")
        if profile and corpus_last_raw:
            try:
                first_date = datetime.date.fromisoformat(str(profile["first_date"]))
                last_date = datetime.date.fromisoformat(profile["last_date"])
                corpus_last = datetime.date.fromisoformat(corpus_last_raw)
                samples = int(profile.get("samples") or 0)
            except (KeyError, TypeError, ValueError):
                first_date = last_date = corpus_last = None
                samples = 0
            if last_date and corpus_last and first_date:
                deadline = last_date + datetime.timedelta(days=_HISTORICAL_GAP_DAYS)
                generation_closed = deadline <= corpus_last
                visible_late = visible_dt.date() > deadline
                id_late = id_msk.date() > deadline
                visible_early_days = (first_date - visible_dt.date()).days
                id_early_days = (first_date - id_msk.date()).days
                out.stats["profile_epoch"] = {
                    "key": profile_key,
                    "first_date": profile.get("first_date"),
                    "last_date": profile.get("last_date"),
                    "samples": profile.get("samples"),
                    "deadline": deadline.isoformat(),
                    "generation_closed": generation_closed,
                    "visible_late": visible_late,
                    "id_late": id_late,
                    "visible_early_days": visible_early_days,
                    "id_early_days": id_early_days,
                }
                # HARD: receipt uses a class|bank5|suffix generation that the
                # confirmed corpus only starts later — temporal splice, not a
                # novelty pin on an unseen key (unknown keys stay CLEAN).
                if (
                    samples >= _EARLY_MIN_SAMPLES
                    and visible_early_days >= _EARLY_MIN_LEAD_DAYS
                    and id_early_days >= _EARLY_MIN_LEAD_DAYS
                ):
                    out.flags.append(EpochReuseFlag(
                        EPOCH_EARLY_CODE,
                        (
                            f"профиль {sb_class}/{bank5}/{suffix} в корпусе впервые "
                            f"{profile.get('first_date')} (n={samples}), но ID→MSK="
                            f"{id_msk.date()} и дата квитанции={visible_dt.date()} "
                            f"раньше на {min(visible_early_days, id_early_days)}+ дн. — "
                            "невозможная временная стыковка поколения СБП"
                        ),
                        EPOCH_EARLY_RULE_ID,
                        tier="A",
                    ))
                elif generation_closed and visible_late and id_late:
                    out.flags.append(EpochReuseFlag(
                        EPOCH_CODE,
                        (
                            f"профиль {sb_class}/{bank5}/{suffix} наблюдался "
                            f"{profile.get('first_date')}–{profile.get('last_date')} "
                            f"(n={profile.get('samples')}); ID→MSK={id_msk.date()} и "
                            f"дата квитанции={visible_dt.date()} существенно позже "
                            "завершившейся генерации"
                        ),
                        EPOCH_RULE_ID,
                    ))

    if receipt:
        stem = receipt.rsplit("-", 1)[0]
        originals = (data.get("receipt_stems") or {}).get(stem)
        out.stats["receipt_stem"] = stem
        if originals:
            known_receipts = {item.get("receipt", "") for item in originals}
            known_opids = {item.get("opid", "") for item in originals}
            known_dates = {item.get("date", "") for item in originals}
            visible_date = visible_dt.date().isoformat() if visible_dt else ""
            tail_changed = receipt not in known_receipts
            operation_changed = bool(opid) and opid not in known_opids
            date_changed = bool(visible_date) and visible_date not in known_dates
            out.stats["receipt_stem_match"] = {
                "known_receipts": sorted(known_receipts),
                "known_dates": sorted(known_dates),
                "tail_changed": tail_changed,
                "operation_changed": operation_changed,
                "date_changed": date_changed,
            }
            if tail_changed and operation_changed and date_changed:
                out.flags.append(EpochReuseFlag(
                    STEM_CODE,
                    (
                        f"stem {stem} уже существует в оригинальном корпусе, "
                        f"но изменены четвёртый блок ({receipt}), операция и дата "
                        f"({visible_date}); оригинальные номера={sorted(known_receipts)}"
                    ),
                    STEM_RULE_ID,
                ))

    return out
