"""
Ozon SBP ID validation (32 chars) — spec §11.1.

Core: [A/B] + 10 digits (UTC year digit, day-of-year, HHMMSS) + 21-char tail.
After UTC+3 timestamp must fall in the same displayed minute (seconds 3–53 observed).
No T-Bank/Alfa/Sber emitter-core rules.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from .ozon_profiles import parse_operation_datetime

_SBP_RE = re.compile(r"^[AB][0-9A-Z]{31}$")


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


def validate_ozon_sbp_cipher(opid: str, text: str = "") -> CipherResult:
    res = CipherResult()
    if not opid:
        res.add("OZON_SBP_ID_MISSING", "не найден ID операции СБП", rule_id="OZ-ID-001")
        return res

    res.stats["opid"] = opid
    if len(opid) != 32:
        res.add(
            "OZON_SBP_ID_STRUCTURE",
            f"длина ID {len(opid)} вместо 32",
            rule_id="OZ-ID-001",
        )
        return res

    if not _SBP_RE.match(opid):
        res.add(
            "OZON_SBP_ID_STRUCTURE",
            f"ID «{opid}» содержит недопустимые символы",
            rule_id="OZ-ID-001",
        )
        return res

    if not all(opid[i].isdigit() for i in range(1, 11)):
        res.add(
            "OZON_SBP_ID_STRUCTURE",
            "timestamp core не числовой",
            rule_id="OZ-ID-001",
        )
        return res

    enc_year_digit = int(opid[1])
    enc_doy = int(opid[2:5])
    enc_hour = int(opid[5:7])
    enc_min = int(opid[7:9])
    enc_sec = int(opid[9:11])
    res.stats.update({
        "encoded_year_digit": enc_year_digit,
        "encoded_doy": enc_doy,
        "encoded_hour_utc": enc_hour,
        "encoded_min": enc_min,
        "encoded_sec": enc_sec,
        "tail": opid[11:32],
    })

    if enc_hour > 23 or enc_min > 59 or enc_sec > 59 or enc_doy < 1 or enc_doy > 366:
        res.add(
            "OZON_SBP_ID_TIMESTAMP",
            f"невозможное время в core: doy={enc_doy} {enc_hour:02d}:{enc_min:02d}:{enc_sec:02d}",
            rule_id="K-OZON-SBP-TIME-001",
        )
        return res

    if enc_sec < 3 or enc_sec > 53:
        res.add(
            "OZON_SBP_ID_TIMESTAMP",
            f"секунды в core {enc_sec} вне наблюдаемого профиля 3–53",
            rule_id="K-OZON-SBP-TIME-001",
        )

    dt = parse_operation_datetime(text)
    if not dt:
        res.stats["receipt_datetime_missing"] = True
        return res

    res.stats["receipt_datetime"] = dt.isoformat(sep=" ")

    try:
        id_utc = datetime.datetime(dt.year, 1, 1, enc_hour, enc_min, enc_sec)
        id_utc += datetime.timedelta(days=enc_doy - 1)
    except ValueError:
        res.add(
            "OZON_SBP_ID_TIMESTAMP",
            f"невозможная дата/время в core: doy={enc_doy}",
            rule_id="K-OZON-SBP-TIME-001",
        )
        return res

    id_msk = id_utc + datetime.timedelta(hours=3)
    printed_msk = dt.replace(tzinfo=None)
    delta = abs(int((id_msk - printed_msk).total_seconds()))

    res.stats["cipher_decoded"] = {
        "year_digit": enc_year_digit,
        "doy": enc_doy,
        "utc_hms": f"{enc_hour:02d}:{enc_min:02d}:{enc_sec:02d}",
        "id_msk": id_msk.isoformat(sep=" "),
        "delta_sec": delta,
    }

    mismatches: list[str] = []
    if enc_year_digit != id_utc.year % 10:
        mismatches.append(
            f"год ID[1]={enc_year_digit}, UTC-ядро {id_utc.year % 10}"
        )
    if id_msk.date() != printed_msk.date():
        mismatches.append(
            f"дата ID→MSK {id_msk.date()} vs напечатанная {printed_msk.date()}"
        )
    if (
        id_msk.replace(second=0, microsecond=0) != printed_msk.replace(second=0, microsecond=0)
        and delta > 60
    ):
        mismatches.append(
            f"время ID→MSK {id_msk.strftime('%H:%M:%S')} vs "
            f"{printed_msk.strftime('%H:%M:%S')} (Δ={delta}s)"
        )

    if mismatches:
        res.add(
            "OZON_SBP_ID_TIMESTAMP",
            "; ".join(mismatches),
            rule_id="K-OZON-SBP-TIME-001",
        )

    res.stats["tail_observation"] = opid[11:32]
    return res
