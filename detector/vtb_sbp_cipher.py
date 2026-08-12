"""
VTB SBP ID validation (32 chars) — spec §11.

Core: [A/B] + 10 digits UTC + 21-char tail.
Displayed time has minutes only; ID UTC+3 may differ from minute start by -24..+59 sec.
Do NOT apply T-Bank/Sber second thresholds or emitter-core rules.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from .vtb_profiles import parse_operation_datetime

_SBP_RE = re.compile(r"^[AB][0-9A-Z]{31}$")
_HARD_MINUTES = 5
_DIAG_MINUTES = 2

# NSPK member core on native VTB openhtml SBP genuines (чеки/втб оригинал, n=13).
# 00118 on a VTB-branded receipt is a pasted foreign NSPK id (clone kits).
_VTB_BANK5_ALLOWED: frozenset[str] = frozenset({"00117"})


@dataclass
class CipherFlag:
    code: str
    detail: str
    rule_id: str = ""


@dataclass
class CipherResult:
    flags: list[CipherFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, code: str, detail: str, *, rule_id: str = "", tier: str = "HARD") -> None:
        self.flags.append(CipherFlag(code, detail, rule_id=rule_id or code))
        self.stats.setdefault("flag_tiers", {})[code] = tier


def _doy_to_date(year: int, doy: int) -> datetime.date | None:
    try:
        return datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)
    except (ValueError, OverflowError):
        return None


def validate_vtb_sbp_cipher(opid: str, text: str = "") -> CipherResult:
    res = CipherResult()
    if not opid:
        res.add("VTB_SBP_ID_MISSING", "не найден ID операции в СБП", rule_id="VTB-ID-001")
        return res

    res.stats["opid"] = opid
    if len(opid) != 32:
        res.add("VTB_SBP_ID_STRUCTURE", f"длина ID {len(opid)} вместо 32", rule_id="VTB-ID-001")
        return res

    if not _SBP_RE.match(opid):
        res.add("VTB_SBP_ID_STRUCTURE", f"ID «{opid}» недопустимый формат", rule_id="VTB-ID-001")
        return res

    if not all(opid[i].isdigit() for i in range(1, 11)):
        res.add("VTB_SBP_ID_STRUCTURE", "timestamp core не числовой", rule_id="VTB-ID-001")
        return res

    bank5 = opid[22:27]
    res.stats["sbp_bank5"] = bank5
    if bank5 not in _VTB_BANK5_ALLOWED:
        res.add(
            "VTB_SBP_ID_STRUCTURE",
            (
                f"ядро bank5 «{bank5}» не из нативных ВТБ SBP "
                f"(ожидается 00117) — чужой NSPK-код на квитанции эмитента ВТБ"
            ),
            rule_id="VTB-ID-001",
        )

    enc_doy = int(opid[1:5]) % 1000
    enc_hour = int(opid[5:7])
    enc_min = int(opid[7:9])
    enc_sec = int(opid[9:11])
    res.stats.update({
        "encoded_doy": enc_doy,
        "encoded_hour_utc": enc_hour,
        "encoded_min": enc_min,
        "encoded_sec": enc_sec,
        "tail": opid[11:32],
    })

    if enc_hour > 23 or enc_min > 59 or enc_sec > 59 or enc_doy < 1 or enc_doy > 366:
        res.add(
            "VTB_SBP_ID_TIMESTAMP",
            f"невозможное время: doy={enc_doy} {enc_hour:02d}:{enc_min:02d}:{enc_sec:02d}",
            rule_id="VTB-ID-002",
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
            "VTB_SBP_ID_TIMESTAMP",
            f"день года в ID {enc_doy}, в чеке {real_doy}",
            rule_id="VTB-ID-002",
        )
        return res

    enc_date = _doy_to_date(dt.year, enc_doy)
    if not enc_date:
        res.add("VTB_SBP_ID_TIMESTAMP", f"невалидный doy {enc_doy}", rule_id="VTB-ID-002")
        return res

    encoded_dt = datetime.datetime(
        enc_date.year, enc_date.month, enc_date.day,
        enc_hour, enc_min, enc_sec,
    )
    op_local = dt
    encoded_local = encoded_dt + datetime.timedelta(hours=3)
    diff_sec = (encoded_local - op_local).total_seconds()
    res.stats["local_diff_sec"] = diff_sec

    if enc_min != dt.minute:
        min_diff = min(abs(enc_min - dt.minute), 60 - abs(enc_min - dt.minute))
        op_utc_hour = (dt.hour - 3) % 24
        if min_diff > 2 and enc_hour != op_utc_hour:
            res.add(
                "VTB_SBP_ID_TIMESTAMP",
                f"минута в core {enc_min}, в чеке {dt.minute}",
                rule_id="VTB-ID-002",
            )
            return res

    if diff_sec < -24 or diff_sec > 59:
        abs_min = abs(diff_sec) / 60
        if abs_min > _HARD_MINUTES:
            res.add(
                "VTB_SBP_ID_TIMESTAMP",
                f"UTC core отличается от операции на {int(diff_sec)} сек (>5 мин)",
                rule_id="VTB-ID-002",
            )
        elif abs_min > _DIAG_MINUTES:
            res.stats["ts_drift_diagnostic"] = diff_sec
            res.add(
                "VTB_SBP_ID_DRIFT",
                f"drift {int(diff_sec)} сек — diagnostic (2–5 мин)",
                rule_id="VTB-ID-003",
                tier="DIAGNOSTIC",
            )

    return res
