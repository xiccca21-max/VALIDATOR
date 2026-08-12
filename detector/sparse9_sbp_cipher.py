"""Per-bank SBP ID validation — MB-SBP-* (no cross-bank cipher rules)."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from .sparse9_profiles import BANK_CONTRACTS, parse_operation_datetime

_SBP_RE = re.compile(r"^[A-Z0-9]{32}$")

# NSPK member cores observed on native Raif pdfHTML SBP originals.
_RAIF_BANK5_ALLOWED: frozenset[str] = frozenset({"00116", "00117"})

# OTP issuer member core on native OTP SBP genuines (Quartz phone+SBP corpus).
# 00118 on an OTP-branded receipt is a pasted foreign NSPK id (clone kits),
# not a new OTP member code — issuer INN/footer already pins the bank.
_OTP_BANK5_ALLOWED: frozenset[str] = frozenset({"00117"})

# PSB issuer member core on native PSB SBP genuines (чеки/Промсвязьбанк).
_PSB_BANK5_ALLOWED: frozenset[str] = frozenset({"00117"})


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


def validate_sparse9_sbp_cipher(opid: str, text: str, bank_key: str) -> CipherResult:
    res = CipherResult()
    contract = BANK_CONTRACTS.get(bank_key)
    if not contract or not contract.sbp_id_required:
        res.stats["sbp_not_required"] = True
        return res

    if not opid:
        res.add("MB_SBP_ID_MISSING", "не найден номер операции СБП", rule_id="MB-SBP-001")
        return res

    res.stats["opid"] = opid
    if len(opid) != 32 or not _SBP_RE.match(opid):
        res.add(
            "MB_SBP_ID_STRUCTURE",
            f"ID «{opid[:34]}» — не 32 uppercase alnum",
            rule_id="MB-SBP-002",
        )
        return res

    if not all(opid[i].isdigit() for i in range(1, 11)):
        res.add("MB_SBP_ID_STRUCTURE", "timestamp core не числовой", rule_id="MB-SBP-002")
        return res

    bank5 = opid[22:27]
    sb_class = opid[17:19]
    slot = opid[19:22]
    suffix = opid[26:32]
    res.stats.update({
        "sbp_bank5": bank5,
        "sbp_class": sb_class,
        "sbp_slot": slot,
        "sbp_suffix": suffix,
    })

    # Structural bank5 check is independent of receipt datetime parsing.
    if bank_key == "raif" and bank5 not in _RAIF_BANK5_ALLOWED:
        res.add(
            "MB_SBP_ID_STRUCTURE",
            f"ядро bank5 «{bank5}» не из нативных Raif SBP (ожидается 00116/00117)",
            rule_id="MB-SBP-002-RAIF-BANK5",
        )
        return res
    if bank_key == "otp" and bank5 not in _OTP_BANK5_ALLOWED:
        res.add(
            "MB_SBP_ID_STRUCTURE",
            f"ядро bank5 «{bank5}» не из нативных OTP SBP (ожидается 00117) — "
            f"чужой NSPK-код на квитанции эмитента ОТП",
            rule_id="MB-SBP-002-OTP-BANK5",
        )
        return res
    if bank_key == "psb" and bank5 not in _PSB_BANK5_ALLOWED:
        res.add(
            "MB_SBP_ID_STRUCTURE",
            f"ядро bank5 «{bank5}» не из нативных PSB SBP (ожидается 00117) — "
            f"чужой NSPK-код на квитанции эмитента ПСБ",
            rule_id="MB-SBP-002-PSB-BANK5",
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
    })

    if enc_hour > 23 or enc_min > 59 or enc_sec > 59 or enc_doy < 1 or enc_doy > 366:
        res.add("MB_SBP_ID_TIMESTAMP", "невозможное время в core", rule_id="MB-SBP-003")
        return res

    dt = parse_operation_datetime(text, bank_key)
    if not dt:
        # Do not skip remaining structural work silently — timestamp link is
        # diagnostic-only when the receipt uses a bank-specific date format
        # we could not parse; bank5 was already enforced above.
        res.stats["receipt_datetime_missing"] = True
        return res

    res.stats["receipt_datetime"] = dt.isoformat(sep=" ")
    real_doy = dt.timetuple().tm_yday
    if abs(enc_doy - real_doy) > 2:
        res.add(
            "MB_SBP_ID_TIMESTAMP",
            f"день года в ID {enc_doy}, в чеке {real_doy}",
            rule_id="MB-SBP-003",
        )
        return res

    enc_date = _doy_to_date(dt.year, enc_doy)
    if not enc_date:
        res.add("MB_SBP_ID_TIMESTAMP", f"невалидный doy {enc_doy}", rule_id="MB-SBP-003")
        return res

    encoded_dt = datetime.datetime(
        enc_date.year, enc_date.month, enc_date.day,
        enc_hour, enc_min, enc_sec,
    )
    encoded_local = encoded_dt + datetime.timedelta(hours=3)
    diff_sec = (encoded_local - dt).total_seconds()
    res.stats["local_diff_sec"] = diff_sec

    drift_min = contract.sbp_drift_min
    drift_max = contract.sbp_drift_max
    if drift_min <= diff_sec <= drift_max:
        return res

    abs_min = abs(diff_sec) / 60
    if abs_min > contract.sbp_hard_minutes:
        res.add(
            "MB_SBP_ID_TIMESTAMP",
            f"UTC core отличается от операции на {int(diff_sec)} сек (>{contract.sbp_hard_minutes} мин)",
            rule_id="MB-SBP-004",
        )
    else:
        res.stats["ts_drift_diagnostic"] = diff_sec
        res.add(
            "MB_SBP_ID_DRIFT",
            f"drift {int(diff_sec)} сек — diagnostic для {bank_key}",
            rule_id="MB-SBP-005",
        )

    return res
