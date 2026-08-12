"""
Sber SBP ID validation (32 chars) — spec §11.

Core: [A/B] + 10 digits (year digit, UTC day-of-year, UTC HHMMSS) + 21-char tail.
Corpus: core precedes visible operation time by 3–10 seconds (NOT T-Bank 0–1 sec).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from .sber_profiles import parse_operation_datetime

_SBP_RE = re.compile(r"^[AB][0-9A-Z]{31}$")
_SBER_TS_MIN_SEC = 0
_SBER_TS_MAX_SEC = 15
_SBER_TS_HARD_SEC = 90


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


def validate_sber_sbp_cipher(opid: str, text: str = "") -> CipherResult:
    res = CipherResult()
    if not opid:
        res.add(
            "SBER_SBP_ID_MISSING",
            "не найден идентификатор операции в СБП",
            rule_id="SBR-SEM-007",
        )
        return res

    res.stats["opid"] = opid
    res.stats["length"] = len(opid)

    if len(opid) != 32:
        res.add(
            "SBER_SBP_ID_STRUCTURE",
            f"длина ID {len(opid)} вместо 32 символов",
            rule_id="SBR-SEM-007",
        )
        return res

    if not _SBP_RE.match(opid):
        res.add(
            "SBER_SBP_ID_STRUCTURE",
            f"ID «{opid}» содержит недопустимые символы",
            rule_id="SBR-SEM-007",
        )
        return res

    if not all(opid[i].isdigit() for i in range(1, 11)):
        res.add(
            "SBER_SBP_ID_STRUCTURE",
            "блок timestamp core в ID не числовой",
            rule_id="SBR-SEM-007",
        )
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
        "tail": opid[11:32],
    })

    if enc_hour > 23 or enc_min > 59 or enc_sec > 59 or enc_doy < 1 or enc_doy > 366:
        res.add(
            "SBER_SBP_ID_TIMESTAMP",
            f"невозможное время в core: doy={enc_doy} {enc_hour:02d}:{enc_min:02d}:{enc_sec:02d}",
            rule_id="SBR-SEM-007",
        )
        return res

    dt = parse_operation_datetime(text)
    if not dt:
        res.stats["receipt_datetime_missing"] = True
        return res

    res.stats["receipt_datetime"] = dt.isoformat(sep=" ")
    real_doy = dt.timetuple().tm_yday
    res.stats["receipt_doy"] = real_doy

    if abs(enc_doy - real_doy) > 2:
        res.add(
            "SBER_SBP_ID_TIMESTAMP",
            f"в ID день года {enc_doy}, в чеке {real_doy} — конфликт на дни",
            rule_id="SBR-SEM-008",
        )
        return res

    enc_date = _doy_to_date(dt.year, enc_doy)
    if not enc_date:
        res.add(
            "SBER_SBP_ID_TIMESTAMP",
            f"невалидный день года {enc_doy} в core",
            rule_id="SBR-SEM-007",
        )
        return res

    encoded_dt = datetime.datetime(
        enc_date.year, enc_date.month, enc_date.day,
        enc_hour, enc_min, enc_sec,
    )
    op_utc = dt - datetime.timedelta(hours=3)
    diff_sec = (op_utc - encoded_dt).total_seconds()
    res.stats["utc_diff_sec"] = diff_sec

    if diff_sec < -_SBER_TS_HARD_SEC:
        res.add(
            "SBER_SBP_ID_TIMESTAMP",
            f"core на {abs(int(diff_sec))} сек позже операции (допустимо ≤{_SBER_TS_MAX_SEC})",
            rule_id="SBR-SEM-008",
        )
    elif diff_sec > _SBER_TS_HARD_SEC:
        res.add(
            "SBER_SBP_ID_TIMESTAMP",
            f"core на {int(diff_sec)} сек раньше операции — конфликт на минуты/дни",
            rule_id="SBR-SEM-008",
        )
    elif not (_SBER_TS_MIN_SEC <= diff_sec <= _SBER_TS_MAX_SEC):
        res.stats["ts_drift_observation"] = diff_sec

    return res


def validate_legacy_document(doc_id: str, text: str = "") -> CipherResult:
    """Legacy 36-char document: 14-digit YYYYMMDDHHMMSS + 22-char lowercase tail."""
    res = CipherResult()
    if not doc_id:
        return res

    res.stats["legacy_doc"] = doc_id
    if len(doc_id) != 36:
        res.add(
            "SBER_LEGACY_DOC_STRUCTURE",
            f"длина документа {len(doc_id)} вместо 36",
            rule_id="SBR-SEM-010",
        )
        return res

    prefix = doc_id[:14]
    tail = doc_id[14:]
    if not prefix.isdigit():
        res.add(
            "SBER_LEGACY_DOC_TIMESTAMP",
            f"префикс документа не числовой: «{prefix}»",
            rule_id="SBR-SEM-010",
        )
        return res
    if not re.fullmatch(r"[a-z0-9]{22}", tail):
        res.add(
            "SBER_LEGACY_DOC_STRUCTURE",
            f"хвост документа не lowercase alnum: «{tail[:12]}…»",
            rule_id="SBR-SEM-010",
        )
        return res

    try:
        enc_dt = datetime.datetime.strptime(prefix, "%Y%m%d%H%M%S")
    except ValueError:
        res.add(
            "SBER_LEGACY_DOC_TIMESTAMP",
            f"невозможная дата в префиксе: «{prefix}»",
            rule_id="SBR-SEM-010",
        )
        return res

    dt = parse_operation_datetime(text)
    if not dt:
        return res

    diff = (dt - enc_dt).total_seconds()
    res.stats["legacy_diff_sec"] = diff
    if diff < -5 or diff > 60:
        res.add(
            "SBER_LEGACY_DOC_TIMESTAMP",
            f"префикс документа отличается от операции на {int(diff)} сек",
            rule_id="SBR-SEM-010",
        )

    return res
