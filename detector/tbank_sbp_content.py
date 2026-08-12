"""T-Bank SBP ID content + geometry checks (K-TBANK-SBP-CONTENT-002 / GEOMETRY-001)."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .sbp_cipher import extract_receipt_datetime, extract_sbp_opid
from .tbank_sbp_geometry import check_tbank_sbp_geometry

_ASCII_ID_RE = re.compile(r"^[0-9A-Za-z]{32}$")
_PROFILE_BLOCK_RE = re.compile(r"^0011$")
_ROUTE_LEAD_VALID = frozenset({"0", "B", "G"})
_CLASS_BY_ROUTE: dict[str, frozenset[str]] = {
    "0": frozenset({"00"}),
    "B": frozenset({"B0", "B1"}),
    "G": frozenset({"G1"}),
}
# K-TBANK-SBP-ROUTE-MARKER-001 — linked *60501 suffix grammar (hard/known only).
_SUFFIX_TAIL_B1_00117 = "60501"
_SUFFIX_TAIL_FORBIDDEN: frozenset[tuple[str, str]] = frozenset({
    ("00", "00116"),
    ("G1", "00117"),
})
# K-TBANK-SBP-PROFILE-EMPIRICAL-001 — corpus-backed marker/suffix sets by (class, bank5).
# triple_control / linked_tuples — K-TBANK-SBP-CONTROL-LINK-001 (Jul 2026 corpus).
_LinkedTuple = tuple[str, str, str, str]
_TripleKey = tuple[str, str, str]
# Tier-A control link only where corpus shows unique control per (marker, slot, suffix).
_CONTROL_LINK_TIER_A_PROFILES = frozenset({("00", "00116"), ("B0", "00116")})
# Issuer bank5 codes observed on genuine T-Bank Jasper SBP receipts (т банк corpus).
# 00118 is no longer solo-HARD: new NSPK emitters can appear (same lesson as Alfa).
# Keep as Tier-B observation when outside the historical 00116/00117 set.
_TBANK_ISSUER_BANK5 = frozenset({"00116", "00117"})
# K-TBANK-SBP-LINKED-TUPLE-001 — confirmed reverse links:
# (class, bank5, slot, suffix) -> allowed {(route_marker, control), ...}.
# Unknown keys are never FAKE; only conflicts with known combinations are HARD.
_LinkedKey = tuple[str, str, str, str]
_LINKED_TUPLES: dict[_LinkedKey, frozenset[tuple[str, str]]] = {
    ("B1", "00117", "013", "760501"): frozenset({("1", "1")}),
    ("B1", "00117", "010", "790502"): frozenset({("0", "L")}),
    ("B0", "00116", "016", "680301"): frozenset({("6", "1"), ("7", "6")}),
}
# Profile-specific route_marker alphabets for the linked families above.
_LINKED_ROUTE_ALPHABET: dict[tuple[str, str], frozenset[str]] = {
    ("B1", "00117"): frozenset({"0", "1"}),
    ("B0", "00116"): frozenset({"6", "7"}),
}
_EMPIRICAL_PROFILES: dict[tuple[str, str], dict[str, object]] = {
    ("G1", "00117"): {
        "markers": frozenset({"0", "1"}),
        "suffixes": frozenset({"730902", "770402", "770901", "791103"}),
        "corpus_n": 24,
        "triple_control": {
            ("0", "001", "770402"): "N",
            ("0", "003", "770901"): "D",
            ("0", "007", "791103"): "J",
            ("0", "008", "770901"): "W",
            ("0", "008", "791103"): "U",
            ("0", "012", "730902"): "O",
            ("0", "014", "791103"): "5",
            ("0", "017", "770901"): "Z",
            ("0", "018", "791103"): "H",
            ("1", "002", "791103"): "0",
            ("1", "004", "770901"): "6",
            ("1", "004", "791103"): "E",
            ("1", "006", "791103"): "D",
            ("1", "016", "791103"): "I",
            ("1", "017", "791103"): "D",
            ("1", "018", "791103"): "S",
        },
        "linked_tuples": frozenset({
            ("0", "1", "002", "791103"),
            ("2", "1", "001", "791103"),
            ("4", "0", "010", "791103"),
            ("5", "0", "014", "791103"),
            ("6", "1", "004", "770901"),
            ("9", "0", "010", "791103"),
            ("D", "0", "003", "770901"),
            ("D", "1", "006", "791103"),
            ("D", "1", "017", "791103"),
            ("E", "1", "004", "791103"),
            ("F", "1", "001", "791103"),
            ("H", "0", "018", "791103"),
            ("I", "1", "016", "791103"),
            ("J", "0", "007", "791103"),
            ("N", "0", "001", "770402"),
            ("O", "0", "012", "730902"),
            ("S", "1", "018", "791103"),
            ("T", "0", "010", "791103"),
            ("U", "0", "008", "791103"),
            ("W", "0", "008", "770901"),
            ("Z", "0", "017", "770901"),
        }),
    },
    ("00", "00116"): {
        "markers": frozenset({"0", "1"}),
        "suffixes": frozenset({"640702", "661101", "670301", "680301", "681101"}),
        "corpus_n": 9,
        "triple_control": {
            ("0", "003", "670301"): "B",
            ("0", "004", "670301"): "A",
            ("0", "004", "681101"): "3",
            ("0", "007", "640702"): "F",
            ("0", "007", "670301"): "9",
            ("0", "008", "680301"): "D",
            ("1", "014", "661101"): "R",
            ("1", "016", "680301"): "6",
        },
        "linked_tuples": frozenset({
            ("3", "0", "004", "681101"),
            ("6", "1", "016", "680301"),
            ("9", "0", "007", "670301"),
            ("A", "0", "004", "670301"),
            ("B", "0", "003", "670301"),
            ("D", "0", "008", "680301"),
            ("F", "0", "007", "640702"),
            ("R", "1", "014", "661101"),
        }),
    },
    ("B1", "00117"): {
        "markers": frozenset({"0", "1"}),
        "suffixes": frozenset({"700501", "730501", "760501", "770302", "770901", "790502"}),
        "corpus_n": 20,
        "triple_control": {
            ("0", "002", "760501"): "V",
            ("0", "002", "770901"): "Y",
            ("0", "002", "790502"): "6",
            ("0", "006", "770302"): "D",
            ("0", "006", "770901"): "2",
            ("0", "010", "790502"): "L",
            ("0", "011", "790502"): "D",
            ("0", "013", "700501"): "D",
            ("0", "017", "790502"): "C",
            ("0", "018", "770901"): "L",
            ("1", "001", "760501"): "T",
            ("1", "011", "730501"): "7",
            ("1", "013", "760501"): "1",
            ("1", "020", "790502"): "A",
        },
        "linked_tuples": frozenset({
            ("1", "1", "013", "760501"),
            ("2", "0", "006", "770901"),
            ("6", "0", "002", "790502"),
            ("7", "1", "011", "730501"),
            ("A", "1", "020", "790502"),
            ("C", "0", "017", "790502"),
            ("D", "0", "006", "770302"),
            ("D", "0", "011", "790502"),
            ("D", "0", "013", "700501"),
            ("K", "0", "020", "790502"),
            ("L", "0", "010", "790502"),
            ("L", "0", "018", "770901"),
            ("N", "0", "020", "790502"),
            ("T", "1", "001", "760501"),
            ("V", "0", "002", "760501"),
            ("Y", "0", "002", "770901"),
        }),
    },
    ("B0", "00116"): {
        "markers": frozenset({"6", "7"}),
        "suffixes": frozenset({"680301"}),
        "corpus_n": 2,
        "triple_control": {
            ("6", "016", "680301"): "1",
            ("7", "016", "680301"): "6",
        },
        "linked_tuples": frozenset({
            ("1", "6", "016", "680301"),
            ("6", "7", "016", "680301"),
        }),
    },
}


@dataclass
class SbpCheckFlag:
    code: str
    detail: str
    rule_id: str = ""
    expected: str = ""
    actual: str = ""
    tier: str = "A"


@dataclass
class SbpCheckResult:
    flags: list[SbpCheckFlag] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(
        self,
        code: str,
        detail: str,
        *,
        rule_id: str = "",
        expected: str = "",
        actual: str = "",
        tier: str = "A",
    ) -> None:
        self.flags.append(SbpCheckFlag(
            code, detail,
            rule_id=rule_id or code,
            expected=expected,
            actual=actual,
            tier=tier,
        ))

    def note(self, msg: str) -> None:
        self.diagnostics.append(msg)


def is_jasper_openpdf_profile(producer: str, creator: str) -> bool:
    blob = f"{producer or ''} {creator or ''}".lower()
    return "jasperreports" in blob or "openpdf" in blob or "jaspersoft" in blob


def extract_sbp_opid_geometric(pdf_bytes: bytes, text: str = "") -> str | None:
    """Join a full 32-char SBP ID from geometric/visual fragments (27+5, 28+4, …).

    Does not rely on raw text line order alone — prefers fitz / content-stream
    SBP value lines (reading order), then label-adjacent text fragments.
    """
    fragments: list[str] = []

    # 1) Fitz SBP value lines in visual reading order (Y asc).
    try:
        from .tbank_sbp_geometry import _fitz_layout

        _labels, fitz_sbp = _fitz_layout(pdf_bytes)
        ordered = sorted(fitz_sbp or [], key=lambda r: (float(r.get("y", 0)), float(r.get("x", 0))))
        fragments = [
            re.sub(r"\s+", "", str(r.get("text") or ""))
            for r in ordered
            if r.get("text")
        ]
    except Exception:
        fragments = []

    # 2) Content-stream SBP block (geometry matcher) if fitz was incomplete.
    if not fragments or len("".join(fragments)) < 32:
        try:
            from .font_layers import _font_objects
            from .structure import content_stream_bytes, find_streams, is_content_stream
            from .tbank_sbp_geometry import _find_sbp_block, _fitz_layout, _parse_content_runs

            content = content_stream_bytes(pdf_bytes) or b""
            if not content:
                for _raw, dec in find_streams(pdf_bytes):
                    if is_content_stream(dec):
                        content = dec
                        break
            fonts, _ = _font_objects(pdf_bytes)
            if content and "F1" in fonts:
                _labels, fitz_sbp = _fitz_layout(pdf_bytes)
                runs = _parse_content_runs(content, fonts)
                _hid, _hsbp, sbp_runs = _find_sbp_block(runs, fitz_sbp=fitz_sbp)
                stream_frags = [
                    re.sub(r"\s+", "", str(r.get("text") or ""))
                    for r in (sbp_runs or [])
                    if r.get("text")
                ]
                if stream_frags:
                    fragments = stream_frags
        except Exception:
            pass

    joined = _join_sbp_fragments(fragments)
    if joined:
        return joined

    # 3) Label-adjacent text (handles wrap without trusting global order).
    label_join = _join_sbp_near_label(text or "")
    if label_join:
        return label_join

    return extract_sbp_opid(text) if text else None


def _join_sbp_fragments(parts: list[str]) -> str | None:
    cleaned = [re.sub(r"\s+", "", p or "") for p in parts if p]
    cleaned = [p for p in cleaned if p]
    if not cleaned:
        return None
    for p in cleaned:
        if _ASCII_ID_RE.fullmatch(p) and p[0] in "AB":
            return p
    # Prefer head starting with A/B + subsequent digit/alnum tails until 32.
    for i, head in enumerate(cleaned):
        if not head or head[0] not in "AB":
            continue
        acc = head
        if _ASCII_ID_RE.fullmatch(acc):
            return acc
        for tail in cleaned[i + 1:]:
            if not re.fullmatch(r"[0-9A-Z]+", tail):
                break
            acc += tail
            if len(acc) == 32 and _ASCII_ID_RE.fullmatch(acc):
                return acc
            if len(acc) > 32:
                break
    blob = "".join(cleaned)
    m = re.search(r"[AB][0-9A-Z]{31}", blob)
    return m.group(0) if m else None


def _join_sbp_near_label(text: str) -> str | None:
    lines = [(ln or "").strip() for ln in (text or "").splitlines()]
    for i, ln in enumerate(lines):
        low = ln.lower()
        if "идентификатор операции" not in low and low != "сбп":
            continue
        window: list[str] = []
        for ln2 in lines[i:i + 8]:
            low2 = ln2.lower()
            if "идентификатор" in low2 or low2 == "сбп":
                continue
            tok = re.sub(r"\s+", "", ln2)
            if re.fullmatch(r"[AB][0-9A-Z]{10,31}", tok) or re.fullmatch(r"[0-9A-Z]{4,8}", tok):
                window.append(tok)
        joined = _join_sbp_fragments(window)
        if joined:
            return joined
    return extract_sbp_opid(text)


def _check_ascii_structure(opid: str, res: SbpCheckResult) -> bool:
    if len(opid) != 32:
        res.add(
            "SBP_CIPHER_STRUCTURE",
            f"длина СБП-ID {len(opid)} вместо 32 символов",
            rule_id="K-TBANK-SBP-CONTENT-002",
            expected="32",
            actual=str(len(opid)),
        )
        return False
    if not _ASCII_ID_RE.fullmatch(opid):
        res.add(
            "SBP_CIPHER_STRUCTURE",
            f"СБП-ID «{opid}» содержит недопустимые символы (ожидаются ASCII-буквы и цифры)",
            rule_id="K-TBANK-SBP-CONTENT-002",
        )
        return False
    return True


def _check_timestamp_exact(opid: str, text: str, res: SbpCheckResult) -> None:
    """K-TBANK-SBP-TIME-001 — MSK printed time vs UTC core in ID (0/+1 sec)."""
    if not all(opid[i].isdigit() for i in range(1, 11)):
        res.add(
            "SBP_CIPHER_STRUCTURE",
            "блок даты/времени в СБП-ID не числовой",
            rule_id="K-TBANK-SBP-TIME-001",
        )
        return

    dt = extract_receipt_datetime(text, prefer_first_line=True)
    if not dt:
        res.stats["operation_datetime_missing"] = True
        return

    if dt.second == 0 and ":" not in (text.split("\n")[0] if text else ""):
        m = re.search(r"\d{2}:\d{2}:\d{2}", text or "")
        if not m:
            res.stats["timestamp_skipped"] = "no_seconds_in_receipt"
            return

    enc_year_digit = int(opid[1])
    enc_doy = int(opid[2:5])
    enc_hour = int(opid[5:7])
    enc_min = int(opid[7:9])
    enc_sec = int(opid[9:11])

    if enc_hour > 23 or enc_min > 59 or enc_sec > 59:
        res.add(
            "SBP_CIPHER_TIMESTAMP",
            f"невозможное время в ID: {enc_hour:02d}:{enc_min:02d}:{enc_sec:02d}",
            rule_id="K-TBANK-SBP-TIME-001",
            expected="HH≤23, MM≤59, SS≤59",
            actual=f"{enc_hour:02d}:{enc_min:02d}:{enc_sec:02d}",
        )
        return

    try:
        id_utc = datetime.datetime(dt.year, 1, 1, enc_hour, enc_min, enc_sec)
        id_utc += datetime.timedelta(days=enc_doy - 1)
    except ValueError:
        res.add(
            "SBP_CIPHER_TIMESTAMP",
            f"невозможное время в ID: {enc_hour:02d}:{enc_min:02d}:{enc_sec:02d}",
            rule_id="K-TBANK-SBP-TIME-001",
        )
        return

    id_msk = id_utc + datetime.timedelta(hours=3)
    printed_msk = dt.replace(tzinfo=None)
    delta = abs(int((id_msk - printed_msk).total_seconds()))

    res.stats["operation_datetime"] = dt.isoformat(sep=" ")
    res.stats["cipher_decoded"] = {
        "year_digit": enc_year_digit,
        "utc_doy": enc_doy,
        "printed_doy": dt.timetuple().tm_yday,
        "utc_hms": f"{enc_hour:02d}:{enc_min:02d}:{enc_sec:02d}",
        "id_utc": id_utc.isoformat(sep=" "),
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
            f"дата ID→MSK {id_msk.date()} vs напечатанная {printed_msk.date()} "
            f"(UTC doy в ID={enc_doy})"
        )
    if delta > 1:
        mismatches.append(
            f"время ID→MSK {id_msk.strftime('%H:%M:%S')} vs напечатанное "
            f"{printed_msk.strftime('%H:%M:%S')} (Δ={delta}s, допуск 0–1s)"
        )

    if mismatches:
        res.add(
            "SBP_CIPHER_TIMESTAMP",
            "; ".join(mismatches),
            rule_id="K-TBANK-SBP-TIME-001",
            expected="Δ≤1s MSK",
            actual=f"{delta}s",
        )


def _check_route_field(opid: str, res: SbpCheckResult) -> None:
    """K-TBANK-SBP-ROUTE-FIELD-001 — route/control/separator/class for Jasper SBP."""
    control = opid[15]
    separator = opid[16]
    route_lead = opid[17]
    sb_class = opid[17:19]
    res.stats["sbp_route"] = {
        "control": control,
        "separator": separator,
        "route_lead": route_lead,
        "class": sb_class,
    }

    if separator != "0":
        res.add(
            "SBP_ROUTE_FIELD_CONTAMINATION",
            f"separator ID[16]={separator!r} — для текущего поколения ожидается «0»",
            rule_id="K-TBANK-SBP-ROUTE-FIELD-001",
            expected="0",
            actual=separator,
        )
        return

    if route_lead not in _ROUTE_LEAD_VALID:
        res.add(
            "SBP_ROUTE_FIELD_CONTAMINATION",
            f"route_lead ID[17]={route_lead!r} вне алфавита текущего поколения "
            f"{sorted(_ROUTE_LEAD_VALID)}",
            rule_id="K-TBANK-SBP-ROUTE-FIELD-001",
            expected="0|B|G",
            actual=route_lead,
        )
        return

    allowed = _CLASS_BY_ROUTE.get(route_lead, frozenset())
    if allowed and sb_class not in allowed:
        res.add(
            "SBP_ROUTE_FIELD_CONTAMINATION",
            f"class ID[17:19]={sb_class!r} не согласован с route_lead={route_lead!r} "
            f"(допустимо: {sorted(allowed)})",
            rule_id="K-TBANK-SBP-ROUTE-FIELD-001",
            expected="|".join(sorted(allowed)),
            actual=sb_class,
        )
        return

    if control == route_lead and route_lead not in _ROUTE_LEAD_VALID:
        res.add(
            "SBP_ROUTE_FIELD_CONTAMINATION",
            f"control ID[15]={control!r} совпадает с route_lead и вне route-алфавита",
            rule_id="K-TBANK-SBP-ROUTE-FIELD-001",
            expected="control ≠ invalid route",
            actual=f"control=route={control}",
        )


def _check_sbp_control_triple_link(
    control: str,
    route_marker: str,
    slot: str,
    suffix: str,
    sb_class: str,
    bank5: str,
    res: SbpCheckResult,
) -> bool:
    """K-TBANK-SBP-CONTROL-LINK-001 — control char linked to (marker, slot, suffix)."""
    if (sb_class, bank5) not in _CONTROL_LINK_TIER_A_PROFILES:
        return False

    profile = _EMPIRICAL_PROFILES.get((sb_class, bank5))
    if not profile:
        return False

    triple_map = profile.get("triple_control")
    if not isinstance(triple_map, dict):
        return False

    triple: _TripleKey = (route_marker, slot, suffix)
    expected = triple_map.get(triple)
    if expected is None or expected == control:
        return False

    res.add(
        "SBP_CONTROL_TRIPLE_MISMATCH",
        (
            f"control ID[15]={control!r} не согласован с route_marker/slot/suffix="
            f"({route_marker!r}, {slot!r}, {suffix!r}) для class={sb_class}, bank5={bank5}: "
            f"на корпусе для этой тройки всегда {expected!r}"
        ),
        rule_id="K-TBANK-SBP-CONTROL-LINK-001",
        expected=expected,
        actual=control,
        tier="A",
    )
    return True


def _parse_sbp_link_fields(opid: str) -> dict[str, str]:
    """Canonical SBP ID field map (32-char ASCII)."""
    return {
        "route_marker": opid[14],
        "control": opid[15],
        "separator": opid[16],
        "class": opid[17:19],
        "slot": opid[19:22],
        "bank5": opid[22:27],
        "suffix": opid[26:32],
    }


@lru_cache(maxsize=1)
def _linked_tuple_owners() -> dict[tuple[str, str, str, str], frozenset[tuple[str, str]]]:
    """(route_marker, control, slot, suffix) → {(class, bank5), ...} from HARD + corpus."""
    owners: dict[tuple[str, str, str, str], set[tuple[str, str]]] = {}
    for (cls, b5, sl, suf), pairs in _LINKED_TUPLES.items():
        for marker, ctrl in pairs:
            owners.setdefault((marker, ctrl, sl, suf), set()).add((cls, b5))
    for (cls, b5), prof in _EMPIRICAL_PROFILES.items():
        linked = prof.get("linked_tuples")
        if not isinstance(linked, (set, frozenset)):
            continue
        for tup in linked:
            if not isinstance(tup, tuple) or len(tup) != 4:
                continue
            ctrl, marker, sl, suf = tup
            owners.setdefault((marker, ctrl, sl, suf), set()).add((cls, b5))
    return {k: frozenset(v) for k, v in owners.items()}


def _check_cross_class_linked_tuple(opid: str, res: SbpCheckResult) -> bool:
    """K-TBANK-SBP-CROSS-CLASS-001 — B1 grammar block spliced onto G1 (or vice versa).

    receipt_24.07.2026.pdf: class=G1 but (marker,control,slot,suffix)=(0,L,010,790502)
    is the confirmed B1/00117 linked tuple — clean G1 corpus never does this.
    """
    fields = _parse_sbp_link_fields(opid)
    route_marker = fields["route_marker"]
    control = fields["control"]
    sb_class = fields["class"]
    slot = fields["slot"]
    bank5 = fields["bank5"]
    suffix = fields["suffix"]
    claimed = (sb_class, bank5)
    owners = _linked_tuple_owners().get((route_marker, control, slot, suffix))
    if not owners or claimed in owners:
        return False
    foreign = sorted(f"{c}/{b}" for c, b in owners)
    res.add(
        "SBP_LINKED_TUPLE_CROSS_CLASS",
        (
            f"связка route_marker/control/slot/suffix="
            f"({route_marker!r},{control!r},{slot!r},{suffix!r}) "
            f"подтверждена только для {foreign}, но в ID class/bank5="
            f"{sb_class}/{bank5} (контаминация чужого grammar-блока)"
        ),
        rule_id="K-TBANK-SBP-CROSS-CLASS-001",
        expected=f"class/bank5∈{foreign}",
        actual=f"{sb_class}/{bank5}",
        tier="A",
    )
    res.stats["sbp_cross_class"] = {
        "claimed": claimed,
        "owners": sorted(owners),
        "tuple": (route_marker, control, slot, suffix),
    }
    return True


def _check_known_linked_tuples(opid: str, res: SbpCheckResult) -> None:
    """HARD linked-tuple + route alphabet — before empirical, Jasper-independent.

    Unknown (class, bank5, slot, suffix) keys are never FAKE.
    HARD only when a known linked key conflicts with (route_marker, control),
    or when a known tuple is claimed under the wrong class/bank5.
    """
    fields = _parse_sbp_link_fields(opid)
    route_marker = fields["route_marker"]
    control = fields["control"]
    sb_class = fields["class"]
    slot = fields["slot"]
    bank5 = fields["bank5"]
    suffix = fields["suffix"]

    res.stats["sbp_link_fields"] = fields

    if _check_cross_class_linked_tuple(opid, res):
        return

    alphabet = _LINKED_ROUTE_ALPHABET.get((sb_class, bank5))
    if alphabet is not None and route_marker not in alphabet:
        res.add(
            "SBP_ROUTE_FIELD_CONTAMINATION",
            (
                f"route_marker ID[14]={route_marker!r} вне алфавита "
                f"{sorted(alphabet)} для class={sb_class}, bank5={bank5}"
            ),
            rule_id="K-TBANK-SBP-ROUTE-FIELD-001",
            expected="|".join(sorted(alphabet)),
            actual=route_marker,
            tier="A",
        )

    key: _LinkedKey = (sb_class, bank5, slot, suffix)
    allowed = _LINKED_TUPLES.get(key)
    if allowed is None:
        res.stats["sbp_linked_tuple"] = "unknown_key"
        return

    pair = (route_marker, control)
    res.stats["sbp_linked_tuple"] = {
        "key": key,
        "pair": pair,
        "allowed": sorted(allowed),
        "ok": pair in allowed,
    }
    if pair in allowed:
        return

    allowed_fmt = sorted(f"{m}/{c}" for m, c in allowed)
    res.add(
        "SBP_LINKED_TUPLE_CONFLICT",
        (
            f"route_marker/control=({route_marker!r},{control!r}) не входит в "
            f"допустимый набор {allowed_fmt} для "
            f"class={sb_class}, bank5={bank5}, slot={slot}, suffix={suffix}"
        ),
        rule_id="K-TBANK-SBP-LINKED-TUPLE-001",
        expected=f"(route,control)∈{allowed_fmt}",
        actual=f"route_marker={route_marker}, control={control}",
        tier="A",
    )


def _check_suffix_60501_grammar(
    opid: str,
    sb_class: str,
    bank5: str,
    route_marker: str,
    suffix: str,
    res: SbpCheckResult,
) -> bool:
    """K-TBANK-SBP-ROUTE-MARKER-001 — *60501 tail linked to B1/00117 only."""
    if not (len(suffix) == 6 and suffix.endswith(_SUFFIX_TAIL_B1_00117)):
        return False
    if (sb_class, bank5) not in _SUFFIX_TAIL_FORBIDDEN:
        return False

    profile = _EMPIRICAL_PROFILES.get((sb_class, bank5), {})
    allowed_markers = profile.get("markers", frozenset())
    marker_mismatch = bool(allowed_markers and route_marker not in allowed_markers)

    if marker_mismatch:
        res.add(
            "KNOWN_FAKE_SBP_GRAMMAR_COMBINATION",
            (
                f"route_marker={route_marker!r} вне {sorted(allowed_markers)} "
                f"для class={sb_class}, bank5={bank5} и одновременно "
                f"suffix={suffix!r} (tail {_SUFFIX_TAIL_B1_00117}) не согласован "
                f"с class/bank5 (подтверждён только B1/00117)"
            ),
            rule_id="K-TBANK-SBP-ROUTE-MARKER-001",
            expected=f"marker∈{sorted(allowed_markers)}, suffix↔B1/00117",
            actual=f"marker={route_marker}, class={sb_class}, bank5={bank5}, suffix={suffix}",
            tier="KNOWN",
        )
        return True

    res.add(
        "SBP_GRAMMAR_SUFFIX_PROFILE",
        (
            f"suffix ID[26:32]={suffix!r} (tail {_SUFFIX_TAIL_B1_00117}) "
            f"не подтверждён для class={sb_class}, bank5={bank5} "
            f"(связка подтверждена только с B1/00117)"
        ),
        rule_id="K-TBANK-SBP-ROUTE-MARKER-001",
        expected="B1/00117/*60501",
        actual=f"{sb_class}/{bank5}/{suffix}",
        tier="A",
    )
    return True


def _check_sbp_profile_empirical(opid: str, res: SbpCheckResult) -> None:
    """K-TBANK-SBP-PROFILE-EMPIRICAL-001 — corpus marker/suffix observation (tier B)."""
    ref3 = opid[11:14]
    control = opid[15]
    route_marker = opid[14]
    sb_class = opid[17:19]
    slot = opid[19:22]
    bank5 = opid[22:27]
    suffix = opid[26:32]
    linked: _LinkedTuple = (control, route_marker, slot, suffix)
    res.stats["sbp_ref3"] = ref3
    res.stats["sbp_control"] = control
    res.stats["sbp_route_marker"] = route_marker
    res.stats["sbp_slot"] = slot
    res.stats["sbp_bank5"] = bank5
    res.stats["sbp_class"] = sb_class
    res.stats["sbp_suffix"] = suffix

    if _check_sbp_control_triple_link(
        control, route_marker, slot, suffix, sb_class, bank5, res,
    ):
        return

    if _check_suffix_60501_grammar(opid, sb_class, bank5, route_marker, suffix, res):
        return

    profile = _EMPIRICAL_PROFILES.get((sb_class, bank5))
    if not profile:
        res.stats["sbp_profile_empirical"] = "profile_not_in_corpus_v1"
        if bank5 not in _TBANK_ISSUER_BANK5:
            res.add(
                "SBP_TBANK_BANK5_MISMATCH",
                (
                    f"bank5 ID[22:27]={bank5!r} не является issuer-кодом Т-Банка "
                    f"в СБП-ID (ожидается {'/'.join(sorted(_TBANK_ISSUER_BANK5))}); "
                    f"class={sb_class}, suffix={suffix!r}"
                ),
                rule_id="K-TBANK-SBP-BANK5-001",
                expected="|".join(sorted(_TBANK_ISSUER_BANK5)),
                actual=bank5,
                tier="B",
            )
        return

    markers = profile["markers"]
    suffixes = profile["suffixes"]
    corpus_n = profile["corpus_n"]
    marker_bad = route_marker not in markers
    suffix_bad = suffix not in suffixes

    res.stats["sbp_profile_empirical"] = {
        "class": sb_class,
        "bank5": bank5,
        "control": control,
        "marker": route_marker,
        "suffix": suffix,
        "slot": slot,
        "linked_tuple": linked,
        "corpus_n": corpus_n,
        "observed_markers": sorted(markers),
        "observed_suffixes": sorted(suffixes),
        "marker_bad": marker_bad,
        "suffix_bad": suffix_bad,
    }

    if not marker_bad and not suffix_bad:
        _check_empirical_slot_suffix_binding(
            control, route_marker, slot, suffix, sb_class, bank5, res,
        )
        return

    parts: list[str] = []
    if marker_bad:
        parts.append(
            f"marker={route_marker!r} вне наблюдавшихся {sorted(markers)}"
        )
    if suffix_bad:
        parts.append(
            f"suffix={suffix!r} вне наблюдавшихся {sorted(suffixes)}"
        )

    res.add(
        "SBP_PROFILE_EMPIRICAL",
        (
            f"class={sb_class}, bank5={bank5}, slot={slot}: "
            f"{'; '.join(parts)} "
            f"(relevant originals 0/{corpus_n}; "
            f"наблюдавшиеся markers={sorted(markers)}, "
            f"suffixes={sorted(suffixes)})"
        ),
        rule_id="K-TBANK-SBP-PROFILE-EMPIRICAL-001",
        expected=f"marker∈{sorted(markers)}, suffix∈{sorted(suffixes)}",
        actual=f"marker={route_marker}, suffix={suffix}",
        tier="B",
    )


def _check_empirical_slot_suffix_binding(
    control: str,
    route_marker: str,
    slot: str,
    suffix: str,
    sb_class: str,
    bank5: str,
    res: SbpCheckResult,
) -> bool:
    """HARD when (slot, suffix) is corpus-known but (control, marker) is not.

    Unknown (slot, suffix) pairs are never FAKE (future templates).
    receipt_30.07.2026.pdf: G1/00117 slot=014 suffix=791103 only binds to
    (control,marker)=(5,0); clone used (A,1) with otherwise-legal marker/suffix.
    """
    profile = _EMPIRICAL_PROFILES.get((sb_class, bank5))
    if not profile:
        return False
    linked = profile.get("linked_tuples")
    if not isinstance(linked, (set, frozenset)):
        return False

    allowed_pairs = {
        (ctrl, marker)
        for tup in linked
        if isinstance(tup, tuple) and len(tup) == 4
        for ctrl, marker, sl, suf in (tup,)
        if sl == slot and suf == suffix
    }
    if not allowed_pairs:
        res.stats["sbp_slot_suffix_binding"] = "unknown_slot_suffix"
        return False

    pair = (control, route_marker)
    res.stats["sbp_slot_suffix_binding"] = {
        "slot": slot,
        "suffix": suffix,
        "pair": pair,
        "allowed": sorted(allowed_pairs),
        "ok": pair in allowed_pairs,
    }
    if pair in allowed_pairs:
        return False

    allowed_fmt = sorted(f"{c}/{m}" for c, m in allowed_pairs)
    res.add(
        "SBP_LINKED_TUPLE_CONFLICT",
        (
            f"control/route_marker=({control!r},{route_marker!r}) не входит в "
            f"корпусную связку {allowed_fmt} для "
            f"class={sb_class}, bank5={bank5}, slot={slot}, suffix={suffix}"
        ),
        rule_id="K-TBANK-SBP-SLOT-SUFFIX-001",
        expected=f"(control,route)∈{allowed_fmt}",
        actual=f"control={control}, route_marker={route_marker}",
        tier="A",
    )
    return True


def _check_profile_block(opid: str, res: SbpCheckResult) -> None:
    block = opid[22:26]
    res.stats["profile_block"] = block
    if not _PROFILE_BLOCK_RE.fullmatch(block):
        res.add(
            "SBP_CIPHER_STRUCTURE",
            f"фиксированный блок ID[22:26]={block!r} — для текущего профиля ожидается 0011",
            rule_id="K-TBANK-SBP-CONTENT-002",
            expected="0011",
            actual=block,
        )



def validate_tbank_sbp_id(
    opid: str,
    text: str,
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> SbpCheckResult:
    """Content (002) + raw geometry (GEOMETRY-001) for Jasper/OpenPDF SBP profile."""
    out = SbpCheckResult()
    jasper = is_jasper_openpdf_profile(producer, creator)
    out.stats["jasper_openpdf"] = jasper

    if not opid or len(opid) != 32:
        geo = extract_sbp_opid_geometric(pdf_bytes, text) or ""
        if geo and (not opid or len(geo) == 32):
            opid = geo
        elif not opid:
            opid = extract_sbp_opid(text) or ""
    out.stats["opid"] = opid

    if not opid:
        out.add(
            "SBP_CIPHER_MISSING",
            "не найден идентификатор операции СБП",
            rule_id="K-TBANK-SBP-CONTENT-002",
        )
        return out

    if not _check_ascii_structure(opid, out):
        return out

    _check_timestamp_exact(opid, text, out)

    # HARD linked tuples — all SBP receipts, before empirical / Jasper gate.
    _check_known_linked_tuples(opid, out)

    if not jasper:
        out.stats["profile_skipped"] = "not_jasper_openpdf"
        return out

    _check_profile_block(opid, out)
    _check_route_field(opid, out)
    _check_sbp_profile_empirical(opid, out)

    geom = check_tbank_sbp_geometry(pdf_bytes, opid, text)
    out.stats["geometry"] = geom.stats
    for gf in geom.flags:
        out.add(gf.code, gf.detail, rule_id=gf.rule_id)

    return out
