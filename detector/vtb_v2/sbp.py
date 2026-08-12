"""Full VTB SBP-ID parser + known-fake linked tuple / tail matchers."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from .known_signatures import (
    VTB_KNOWN_FAKE_LINKED_TUPLES,
    VTB_KNOWN_FAKE_SBP_IDS,
    VTB_KNOWN_FAKE_SBP_TAILS,
)
from .subtypes import normalize_text
from .types import VtbFlag

_SBP_RE = re.compile(r"^[AB][0-9A-Z]{31}$")
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4}),?\s*(\d{2}):(\d{2})")

# Native VTB openhtml SBP genuines (чеки/втб оригинал, n=13) — bank5 always 00117.
# Clone kits paste foreign NSPK cores (e.g. 00118).
_VTB_BANK5_ALLOWED: frozenset[str] = frozenset({"00117"})


@dataclass
class SbpParsed:
    raw: str = ""
    marker: str = ""
    control: str = ""
    sb_class: str = ""
    slot: str = ""
    bank5: str = ""
    suffix: str = ""
    block_0011: str = ""
    year_digit: str = ""
    doy: int = 0
    hour_utc: int = 0
    minute: int = 0
    second: int = 0
    core: str = ""
    tail14: str = ""
    linked_tuple: tuple[str, str, str, str, str, str] | None = None


@dataclass
class SbpCheckResult:
    flags: list[VtbFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    parsed: SbpParsed | None = None
    known_fake_hit: bool = False


def extract_sbp_opid(text: str) -> str | None:
    """Remove only spaces/newlines; keep other characters. Glue broken 32-char IDs."""
    raw = normalize_text(text)
    # Prefer labelled field, glue across line break.
    low = raw.lower()
    for marker in ("id операции в сбп", "id операции"):
        idx = low.find(marker)
        if idx >= 0:
            tail = raw[idx + len(marker):idx + len(marker) + 80]
            compact = re.sub(r"[\t \n\r]+", "", tail)
            m = re.match(r"([AB][0-9A-Z]{31})", compact)
            if m:
                return m.group(1)
    compact = re.sub(r"[\t \n\r]+", "", raw)
    m = re.search(r"([AB][0-9A-Z]{31})", compact)
    return m.group(1) if m else None


def parse_operation_datetime(text: str) -> datetime.datetime | None:
    raw = normalize_text(text)
    idx = raw.lower().find("дата операции")
    window = raw[idx:idx + 80] if idx >= 0 else raw
    m = _DATE_RE.search(window) or _DATE_RE.search(raw)
    if not m:
        return None
    d, mo, y, h, mi = map(int, m.groups())
    try:
        return datetime.datetime(y, mo, d, h, mi, 0)
    except ValueError:
        return None


def parse_sbp_id(opid: str) -> SbpParsed:
    p = SbpParsed(raw=opid)
    if len(opid) != 32:
        return p
    p.year_digit = opid[1]
    p.core = opid[1:11]
    try:
        p.doy = int(opid[1:5]) % 1000
        p.hour_utc = int(opid[5:7])
        p.minute = int(opid[7:9])
        p.second = int(opid[9:11])
    except ValueError:
        pass
    p.tail14 = opid[14:]
    p.marker = opid[14]
    p.control = opid[15]
    p.sb_class = opid[17:19]
    p.slot = opid[19:22]
    p.bank5 = opid[22:27]
    p.suffix = opid[26:32]
    p.block_0011 = opid[22:26]
    p.linked_tuple = (
        p.sb_class, p.bank5, p.marker, p.control, p.slot, p.suffix,
    )
    return p


def _flag(code: str, detail: str, *, tier: str = "HARD", group: str = "") -> VtbFlag:
    return VtbFlag(code=code, detail=detail, tier=tier, group=group, rule_id=code)


def validate_sbp_id(opid: str | None, text: str = "") -> SbpCheckResult:
    res = SbpCheckResult()
    if not opid:
        res.flags.append(_flag("VTB_SBP_ID_MISSING", "не найден ID операции в СБП"))
        return res

    res.stats["opid"] = opid
    if len(opid) != 32:
        res.flags.append(_flag(
            "VTB_SBP_ID_STRUCTURE", f"длина ID {len(opid)} вместо 32",
        ))
        return res
    if not _SBP_RE.match(opid):
        res.flags.append(_flag(
            "VTB_SBP_ID_STRUCTURE",
            f"ID «{opid}» содержит недопустимые символы",
        ))
        return res
    if not all(opid[i].isdigit() for i in range(1, 11)):
        res.flags.append(_flag(
            "VTB_SBP_ID_STRUCTURE", "timestamp core не числовой",
        ))
        return res

    parsed = parse_sbp_id(opid)
    res.parsed = parsed
    res.stats.update({
        "year_digit": parsed.year_digit,
        "doy": parsed.doy,
        "hour_utc": parsed.hour_utc,
        "minute": parsed.minute,
        "second": parsed.second,
        "marker": parsed.marker,
        "control": parsed.control,
        "class": parsed.sb_class,
        "slot": parsed.slot,
        "bank5": parsed.bank5,
        "suffix": parsed.suffix,
        "block_0011": parsed.block_0011,
        "tail14": parsed.tail14,
        "linked_tuple": parsed.linked_tuple,
    })

    if (
        parsed.hour_utc > 23 or parsed.minute > 59 or parsed.second > 59
        or parsed.doy < 1 or parsed.doy > 366
    ):
        res.flags.append(_flag(
            "VTB_SBP_ID_TIMESTAMP",
            f"невозможное время: doy={parsed.doy} "
            f"{parsed.hour_utc:02d}:{parsed.minute:02d}:{parsed.second:02d}",
        ))
        return res

    if parsed.block_0011 != "0011":
        res.flags.append(_flag(
            "VTB_SBP_ID_0011_MISSING",
            f"блок ID[22:26]={parsed.block_0011!r} — ожидается 0011",
        ))

    if parsed.bank5 not in _VTB_BANK5_ALLOWED:
        res.flags.append(_flag(
            "VTB_SBP_ID_STRUCTURE",
            (
                f"ядро bank5 «{parsed.bank5}» не из нативных ВТБ SBP "
                f"(ожидается 00117) — чужой NSPK-код на квитанции эмитента ВТБ"
            ),
        ))

    dt = parse_operation_datetime(text)
    if dt:
        res.stats["receipt_datetime"] = dt.isoformat(sep=" ")
        year_digit_expected = str(dt.year % 10)
        if parsed.year_digit != year_digit_expected:
            # Year digit is part of doy encoding (YYYYD... via [1:5]%1000);
            # only HARD when decade digit clearly disagrees with visible year
            # AND doy also disagrees — avoid FP on encoding schemes.
            real_doy = dt.timetuple().tm_yday
            if abs(parsed.doy - real_doy) > 2:
                res.flags.append(_flag(
                    "VTB_SBP_ID_YEAR",
                    f"год/doy в ID не согласован с датой операции "
                    f"(digit={parsed.year_digit}, doy={parsed.doy}, "
                    f"ожидался doy≈{real_doy})",
                ))

        real_doy = dt.timetuple().tm_yday
        if abs(parsed.doy - real_doy) > 2:
            res.flags.append(_flag(
                "VTB_SBP_ID_TIMESTAMP",
                f"день года в ID {parsed.doy}, в чеке {real_doy}",
            ))
        else:
            try:
                enc_date = datetime.date(dt.year, 1, 1) + datetime.timedelta(
                    days=parsed.doy - 1,
                )
                encoded_dt = datetime.datetime(
                    enc_date.year, enc_date.month, enc_date.day,
                    parsed.hour_utc, parsed.minute, parsed.second,
                )
                encoded_local = encoded_dt + datetime.timedelta(hours=3)
                diff_sec = (encoded_local - dt).total_seconds()
                res.stats["local_diff_sec"] = diff_sec
                abs_min = abs(diff_sec) / 60
                if abs_min > 5:
                    res.flags.append(_flag(
                        "VTB_SBP_ID_TIMESTAMP",
                        f"UTC core отличается от операции на {int(diff_sec)} сек",
                    ))
                elif abs_min > 2:
                    res.flags.append(_flag(
                        "VTB_SBP_ID_DRIFT",
                        f"drift {int(diff_sec)} сек — diagnostic/supporting",
                        tier="B",
                        group="sbp_grammar",
                    ))
            except (ValueError, OverflowError):
                pass
    else:
        res.stats["receipt_datetime_missing"] = True

    # Known-fake matchers (alternative channels — one series).
    if opid in VTB_KNOWN_FAKE_SBP_IDS:
        res.known_fake_hit = True
        res.flags.append(_flag(
            "VTB_KNOWN_FAKE_SBP_ID",
            f"точный известный фейковый SBP ID «{opid}»",
            tier="KNOWN",
        ))
    elif parsed.linked_tuple in VTB_KNOWN_FAKE_LINKED_TUPLES:
        res.known_fake_hit = True
        res.flags.append(_flag(
            "VTB_SBP_LINKED_TUPLE_KNOWN_FAKE",
            f"точное совпадение linked-tuple {parsed.linked_tuple}",
            tier="KNOWN",
        ))
    elif parsed.tail14 in VTB_KNOWN_FAKE_SBP_TAILS:
        res.known_fake_hit = True
        res.flags.append(_flag(
            "VTB_SBP_TAIL_SPLICE_KNOWN_FAKE",
            f"точный SBP-tail splice «{parsed.tail14}»",
            tier="KNOWN",
        ))
    else:
        # New class/marker/suffix alone → diagnostic, never HARD.
        res.flags.append(_flag(
            "VTB_SBP_EMPIRICAL_PROFILE",
            (
                f"SBP tuple class={parsed.sb_class} marker={parsed.marker} "
                f"suffix={parsed.suffix} — observation"
            ),
            tier="DIAGNOSTIC",
        ))

    return res
