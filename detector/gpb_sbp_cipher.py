"""
Gazprombank SBP ID validation (32 chars) — spec §12.

Core: lead A/B + UTC year digit + doy + HHMMSS + tail.
Corpus drift from displayed minute start: −19..+23 sec.
Do NOT apply T-Bank/Sber/VTB/Ozon rules.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from .gpb_profiles import parse_operation_datetime

_SBP_RE = re.compile(r"^[A-Z0-9]{32}$")
_HARD_MINUTES = 5
_DIAG_MINUTES = 2
_DRIFT_MIN = -19
_DRIFT_MAX = 23


@dataclass
class CipherFlag:
    code: str
    detail: str
    rule_id: str = ""


@dataclass
class CipherResult:
    flags: list[CipherFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, code: str, detail: str, *, rule_id: str = "") -> None:
        self.flags.append(CipherFlag(code, detail, rule_id=rule_id or code))


def _doy_to_date(year: int, doy: int) -> datetime.date | None:
    try:
        return datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)
    except (ValueError, OverflowError):
        return None


def validate_gpb_sbp_cipher(opid: str, text: str = "") -> CipherResult:
    res = CipherResult()
    if not opid:
        res.add("GPB_SBP_ID_MISSING", "не найден номер операции СБП", rule_id="GPB-ID-001")
        return res

    res.stats["opid"] = opid
    if len(opid) != 32 or not _SBP_RE.match(opid):
        res.add(
            "GPB_SBP_ID_STRUCTURE",
            f"ID «{opid[:34]}» — длина/алфавит не соответствуют 32 uppercase alnum",
            rule_id="GPB-ID-001",
        )
        return res

    if not all(opid[i].isdigit() for i in range(1, 11)):
        res.add("GPB_SBP_ID_STRUCTURE", "timestamp core не числовой", rule_id="GPB-ID-001")
        return res

    enc_doy = int(opid[1:5]) % 1000
    enc_hour = int(opid[5:7])
    enc_min = int(opid[7:9])
    enc_sec = int(opid[9:11])
    res.stats.update({
        "encoded_doy": enc_doy,
        "encoded_hour_utc": enc_hour,
        "encoded_min": enc_min,
        "encoded_sec": enc_sec,
    })

    if enc_hour > 23 or enc_min > 59 or enc_sec > 59 or enc_doy < 1 or enc_doy > 366:
        res.add(
            "GPB_SBP_ID_TIMESTAMP",
            f"невозможное время в core",
            rule_id="GPB-ID-002",
        )
        return res

    dt = parse_operation_datetime(text)
    if not dt:
        res.stats["receipt_datetime_missing"] = True
        return res

    res.stats["receipt_datetime"] = dt.isoformat(sep=" ")
    real_doy = dt.timetuple().tm_yday

    if abs(enc_doy - real_doy) > 2:
        res.add(
            "GPB_SBP_ID_TIMESTAMP",
            f"день года в ID {enc_doy}, в чеке {real_doy}",
            rule_id="GPB-ID-002",
        )
        return res

    enc_date = _doy_to_date(dt.year, enc_doy)
    if not enc_date:
        res.add("GPB_SBP_ID_TIMESTAMP", f"невалидный doy {enc_doy}", rule_id="GPB-ID-002")
        return res

    encoded_dt = datetime.datetime(
        enc_date.year, enc_date.month, enc_date.day,
        enc_hour, enc_min, enc_sec,
    )
    encoded_local = encoded_dt + datetime.timedelta(hours=3)
    diff_sec = (encoded_local - dt).total_seconds()
    res.stats["local_diff_sec"] = diff_sec

    op_utc_hour = (dt.hour - 3) % 24
    if enc_min != dt.minute:
        min_diff = min(abs(enc_min - dt.minute), 60 - abs(enc_min - dt.minute))
        if min_diff > 2 and enc_hour != op_utc_hour:
            res.add(
                "GPB_SBP_ID_TIMESTAMP",
                f"минута в core {enc_min}, в чеке {dt.minute}",
                rule_id="GPB-ID-002",
            )
            return res

    if diff_sec < _DRIFT_MIN or diff_sec > _DRIFT_MAX:
        abs_min = abs(diff_sec) / 60
        if abs_min > _HARD_MINUTES:
            res.add(
                "GPB_SBP_ID_TIMESTAMP",
                f"UTC core отличается от операции на {int(diff_sec)} сек (>5 мин)",
                rule_id="GPB-ID-002",
            )
        elif abs_min > _DIAG_MINUTES:
            res.stats["ts_drift_diagnostic"] = diff_sec
            res.add(
                "GPB_SBP_ID_DRIFT",
                f"drift {int(diff_sec)} сек — diagnostic (2–5 мин)",
                rule_id="GPB-ID-003",
            )

    return res
