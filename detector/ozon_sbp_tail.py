"""Ozon SBP tail structure, clock collapse, provenance.

Unknown tail combos are DIAGNOSTIC. KNOWN only for the confirmed 830901
generator family (B1 + 0011 + 830901). The previous full-tail ban on
0B10180011810101 was retired: live bank originals use that family.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .ozon_profiles import FAMILY_SBP_IN, FAMILY_SBP_OUT

_SBP_FULL_RE = re.compile(r"^[AB][0-9A-Z]{31}$")

# Confirmed Aug 2026 generator family (Telegram attachment_e7cb… / da16690a…).
# Grammar: 0 + B1 + slot(3) + 0011 + 830901. Slot varies (010, 012, …).
# 0/34 on чеки/озон чекии. Must not match live 810101 (B1/018).
KNOWN_FAKE_SBP_830901_RE = re.compile(
    r"^[AB][0-9]{10}[0-9A-Z]{5}0B1[0-9]{3}0011830901$"
)

_PDF_DATE_RE = re.compile(
    r"^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})"
)
_M105_PRODUCER_RE = re.compile(r"^Skia/PDF\s+m105\s*$", re.I)

# Observed (generator_epoch, family, route, slot, fixed_block, suffix) from
# озон-оригинал.zip / corpus SBP originals — unknown combo is DIAGNOSTIC only.
TRUSTED_TAIL_PROFILES: frozenset[tuple[str, str, str, str, str, str]] = frozenset({
    ("m105", "SBP_OUT", "00", "014", "0011", "670301"),
    ("m105", "SBP_OUT", "00", "002", "0011", "630701"),
    ("m105", "SBP_OUT", "00", "011", "0011", "690101"),
    ("m105", "SBP_OUT", "00", "018", "0011", "661101"),
    ("m105", "SBP_OUT", "00", "017", "0011", "630701"),
    ("m105", "SBP_OUT", "00", "012", "0011", "640502"),
    ("m105", "SBP_OUT", "B1", "013", "0011", "760501"),
    ("m105", "SBP_OUT", "B1", "008", "0011", "760501"),
    ("m105", "SBP_OUT", "B1", "016", "0011", "770302"),
    # Live original 2026-07-21 (was FP under retired K-OZON-SBP-GEN-20260719-001).
    ("m105", "SBP_OUT", "B1", "018", "0011", "810101"),
    ("m105", "SBP_IN", "00", "003", "0011", "520701"),
    ("m105", "SBP_IN", "00", "004", "0011", "660101"),
    ("m105", "SBP_IN", "00", "002", "0011", "550702"),
    ("m105", "SBP_IN", "00", "002", "0011", "660101"),
    ("m105", "SBP_IN", "00", "018", "0011", "630701"),
    ("m105", "SBP_IN", "00", "000", "0011", "650701"),
    ("m105", "SBP_IN", "00", "000", "0011", "630701"),
    ("m105", "SBP_IN", "00", "008", "0011", "611101"),
})


@dataclass(frozen=True)
class OzonSbpParts:
    timestamp_core: str  # [0:11] incl. A/B
    node: str            # [11:16]
    fixed_zero: str      # [16]
    route: str           # [17:19]
    slot: str            # [19:22]
    fixed_block: str     # [22:26]
    suffix: str          # [26:32]
    full_tail: str       # [11:32]


@dataclass
class TailFlag:
    code: str
    detail: str
    tier: str = "DIAGNOSTIC"
    rule_id: str = ""
    group: str = ""
    expected: str = ""
    actual: str = ""
    raw_evidence: str = ""


@dataclass
class TailProvenanceResult:
    flags: list[TailFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    parts: OzonSbpParts | None = None


def parse_ozon_sbp_id(operation_id: str) -> OzonSbpParts | None:
    if not operation_id or not _SBP_FULL_RE.fullmatch(operation_id):
        return None
    if not all(operation_id[i].isdigit() for i in range(1, 11)):
        return None
    return OzonSbpParts(
        timestamp_core=operation_id[0:11],
        node=operation_id[11:16],
        fixed_zero=operation_id[16],
        route=operation_id[17:19],
        slot=operation_id[19:22],
        fixed_block=operation_id[22:26],
        suffix=operation_id[26:32],
        full_tail=operation_id[11:32],
    )


def parse_pdf_date(value: str) -> datetime | None:
    m = _PDF_DATE_RE.match((value or "").strip())
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = map(int, m.groups())
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def decode_ozon_sbp_timestamp(
    operation_id: str,
    *,
    year_hint: int | None = None,
) -> datetime | None:
    """Decode UTC wall-clock from Ozon SBP core (positions 1..11)."""
    parts = parse_ozon_sbp_id(operation_id)
    if not parts:
        return None
    core = parts.timestamp_core
    enc_year_digit = int(core[1])
    enc_doy = int(core[2:5])
    enc_hour = int(core[5:7])
    enc_min = int(core[7:9])
    enc_sec = int(core[9:11])
    if enc_hour > 23 or enc_min > 59 or enc_sec > 59 or enc_doy < 1 or enc_doy > 366:
        return None

    if year_hint is not None:
        base = year_hint - (year_hint % 10) + enc_year_digit
        year = min((base, base - 10, base + 10), key=lambda y: abs(y - year_hint))
    else:
        year = 2020 + enc_year_digit

    try:
        return datetime(year, 1, 1, enc_hour, enc_min, enc_sec) + timedelta(days=enc_doy - 1)
    except (ValueError, OverflowError):
        return None


def is_exact_m105_pdf14(producer: str, pdf_bytes: bytes) -> bool:
    if not _M105_PRODUCER_RE.match((producer or "").strip()):
        return False
    return pdf_bytes[:16].startswith(b"%PDF-1.4")


def is_known_fake_sbp_family(
    operation_id: str,
    *,
    family: str,
    producer: str,
    pdf_bytes: bytes,
) -> bool:
    """KNOWN only for the 830901 generator family, not unknown tails in general.

    The previous 810101 full-tail ban FPed a live original. 830901 is absent
    from the genuine Skia corpus and shared by confirmed fakes.
    """
    if family not in (FAMILY_SBP_OUT, FAMILY_SBP_IN):
        return False
    if not is_exact_m105_pdf14(producer, pdf_bytes):
        return False
    return bool(KNOWN_FAKE_SBP_830901_RE.fullmatch(operation_id or ""))


def generator_epoch(producer: str) -> str:
    if _M105_PRODUCER_RE.match((producer or "").strip()):
        return "m105"
    return "unknown"


def tail_profile_key(
    parts: OzonSbpParts,
    *,
    family: str,
    producer: str,
) -> tuple[str, str, str, str, str, str]:
    return (
        generator_epoch(producer),
        family,
        parts.route,
        parts.slot,
        parts.fixed_block,
        parts.suffix,
    )


def validate_ozon_tail(
    operation_id: str,
    family: str,
    producer: str,
    trusted_tail_profiles: frozenset[tuple[str, str, str, str, str, str]] | None = None,
) -> list[TailFlag]:
    parts = parse_ozon_sbp_id(operation_id)
    if parts is None:
        return []
    if family not in (FAMILY_SBP_OUT, FAMILY_SBP_IN):
        return []
    trusted = trusted_tail_profiles if trusted_tail_profiles is not None else TRUSTED_TAIL_PROFILES
    key = tail_profile_key(parts, family=family, producer=producer)
    if key in trusted:
        return []
    return [
        TailFlag(
            code="OZON_SBP_TAIL_UNKNOWN",
            detail=(
                f"Неизвестная комбинация Ozon SBP tail: "
                f"route={parts.route} slot={parts.slot} "
                f"block={parts.fixed_block} suffix={parts.suffix}"
            ),
            tier="DIAGNOSTIC",
            rule_id="OZ-ID-TAIL-001",
            group="sbp_tail_provenance",
            actual=str(key),
            raw_evidence=parts.full_tail,
        )
    ]


def validate_sbp_pdf_clocks(
    operation_id: str,
    *,
    creation_date: str,
    mod_date: str,
) -> tuple[list[TailFlag], dict]:
    """OZ-SBP-CLOCK-002 — collapse is DIAGNOSTIC alone; decisive only with tail conflict."""
    flags: list[TailFlag] = []
    stats: dict = {}
    creation_utc = parse_pdf_date(creation_date)
    moddate_utc = parse_pdf_date(mod_date)
    year_hint = creation_utc.year if creation_utc else None
    sbp_time_utc = decode_ozon_sbp_timestamp(operation_id, year_hint=year_hint)
    stats["sbp_timestamp_utc"] = sbp_time_utc.isoformat(sep=" ") if sbp_time_utc else None
    stats["creation_date_utc"] = creation_utc.isoformat(sep=" ") if creation_utc else None
    stats["mod_date_utc"] = moddate_utc.isoformat(sep=" ") if moddate_utc else None

    if not sbp_time_utc or not creation_utc or not moddate_utc:
        stats["clock_collapse"] = False
        return flags, stats

    sbp_creation_delta = abs((creation_utc - sbp_time_utc).total_seconds())
    mod_creation_delta = abs((moddate_utc - creation_utc).total_seconds())
    clock_collapse = sbp_creation_delta <= 1 and mod_creation_delta <= 1
    stats["delta_seconds"] = sbp_creation_delta
    stats["mod_creation_delta"] = mod_creation_delta
    stats["clock_collapse"] = clock_collapse

    if clock_collapse:
        flags.append(TailFlag(
            code="OZON_SBP_PDF_CLOCK_COLLAPSE",
            detail=(
                f"SBP UTC {sbp_time_utc.isoformat(sep=' ')} совпадает с "
                f"CreationDate/ModDate (Δ={sbp_creation_delta:.0f}s) — "
                f"clock provenance collapse"
            ),
            tier="DIAGNOSTIC",
            rule_id="OZ-SBP-CLOCK-002",
            group="clock_provenance",
            expected="SBP timestamp ≠ PDF CreationDate (export lag)",
            actual=f"delta={sbp_creation_delta:.0f}s",
            raw_evidence=str(stats),
        ))
    return flags, stats


def validate_filename_provenance(original_filename: str | None) -> list[TailFlag]:
    """Filename is supporting only — never sole FAKE basis."""
    if not original_filename:
        return []
    name = Path_basename(original_filename)
    if not name.lower().startswith("ozonbank_document"):
        return []

    normalized = re.sub(
        r" \(\d+\)(?=\.pdf$)",
        "",
        name,
        flags=re.IGNORECASE,
    )
    canonical = re.fullmatch(
        r"ozonbank_document_(\d{14})\.pdf",
        normalized,
        flags=re.IGNORECASE,
    )
    if canonical:
        return []
    return [
        TailFlag(
            code="OZON_OFFICIAL_FILENAME_GRAMMAR_CONFLICT",
            detail=(
                f"имя файла «{normalized}» не соответствует "
                f"ozonbank_document_YYYYMMDDHHMMSS.pdf"
            ),
            tier="DIAGNOSTIC",
            rule_id="OZ-FN-001",
            group="filename_provenance",
            actual=normalized,
        )
    ]


def Path_basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def validate_ozon_sbp_tail_provenance(
    operation_id: str,
    *,
    family: str,
    producer: str,
    pdf_bytes: bytes,
    creation_date: str = "",
    mod_date: str = "",
    source_filename: str | None = None,
) -> TailProvenanceResult:
    """Run known-fake → clock/tail composite → filename diagnostics."""
    out = TailProvenanceResult()
    parts = parse_ozon_sbp_id(operation_id or "")
    out.parts = parts
    out.stats["operation_id"] = operation_id
    out.stats["family"] = family

    if not operation_id or family not in (FAMILY_SBP_OUT, FAMILY_SBP_IN):
        return out

    if is_known_fake_sbp_family(
        operation_id, family=family, producer=producer, pdf_bytes=pdf_bytes,
    ):
        slot = parts.slot if parts else "?"
        tail = parts.full_tail if parts else operation_id[11:]
        out.flags.append(TailFlag(
            code="OZON_KNOWN_FAKE_SBP_TAIL_FAMILY",
            detail=(
                f"подтверждённое generator-семейство Ozon SBP: "
                f"route=B1 slot={slot} block=0011 suffix=830901 "
                f"(хвост {tail})"
            ),
            tier="KNOWN",
            rule_id="K-OZON-SBP-GEN-830901-001",
            group="sbp_tail_provenance",
            expected="Ozon native suffix ≠ 830901 on B1/0011",
            actual=tail,
            raw_evidence=operation_id,
        ))
        out.stats["known_fake_830901"] = True
        out.flags.extend(validate_filename_provenance(source_filename))
        return out

    # Unknown tail stays DIAGNOSTIC (810101 live-original lesson).
    tail_flags = validate_ozon_tail(operation_id, family, producer)
    clock_flags, clock_stats = validate_sbp_pdf_clocks(
        operation_id, creation_date=creation_date, mod_date=mod_date,
    )
    out.stats["clock"] = clock_stats
    out.flags.extend(tail_flags)
    out.flags.extend(clock_flags)

    unknown = any(f.code == "OZON_SBP_TAIL_UNKNOWN" for f in tail_flags)
    collapse = bool(clock_stats.get("clock_collapse"))
    exact_m105 = is_exact_m105_pdf14(producer, pdf_bytes)
    out.stats["exact_m105_pdf14"] = exact_m105
    out.stats["tail_unknown"] = unknown

    # Novelty composite: unknown trusted-tail whitelist miss must not FAKE.
    if exact_m105 and unknown and collapse and parts:
        out.flags.append(TailFlag(
            code="OZON_CURRENT_GENERATOR_PROVENANCE_CONFLICT",
            detail=(
                "m105/PDF-1.4 + SBP tail вне корпуса + clock collapse — "
                "диагностика provenance (неполный atlas хвостов ≠ FAKE)"
            ),
            tier="DIAGNOSTIC",
            rule_id="OZ-CURR-PROVENANCE-003",
            group="sbp_tail_provenance",
            expected="trusted tail OR export lag vs CreationDate",
            actual=parts.full_tail,
            raw_evidence=str({
                "clock": clock_stats,
                "tail": {
                    "route": parts.route,
                    "slot": parts.slot,
                    "fixed_block": parts.fixed_block,
                    "suffix": parts.suffix,
                    "full_tail": parts.full_tail,
                },
            }),
        ))

    # 3) Filename — diagnostics only
    out.flags.extend(validate_filename_provenance(source_filename))
    return out
