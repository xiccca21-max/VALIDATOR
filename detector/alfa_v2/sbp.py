"""Alfa v2 parser for 32-character SBP operation identifiers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

_ALPHABET_RE = re.compile(r"^[0-9A-Z]{32}$")
_DATE_RE = re.compile(
    r"(\d{2})[.](\d{2})[.](\d{4})(?:\s*(?:г[.]?)?)"
    r"(?:\s+|,\s*)(\d{2}):(\d{2})(?::(\d{2}))?"
)
_MAX_COMPLETION_LAG = timedelta(hours=3, minutes=5)

_HERE = Path(__file__).resolve().parent
_DETECTOR = _HERE.parent
_ATLAS_PATHS = (
    _HERE / "atlas_data" / "alfa_sbp_atlas.json",
    _HERE / "atlas_data" / "sbp-segmentation.v1.json",
    _HERE / "alfa_sbp_atlas.json",
    _DETECTOR / "atlas_data" / "alfa_sbp_atlas.json",
    _DETECTOR / "alfa_sbp_extensions.json",
    _DETECTOR / "atlas_data" / "_alfa_corpus_scan.json",
)


@dataclass(frozen=True)
class SbpFlag:
    code: str
    detail: str
    tier: str = "HARD"
    group: str = "sbp"


@dataclass
class SbpResult:
    flags: list[SbpFlag] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    def add(
        self,
        code: str,
        detail: str,
        tier: str = "HARD",
        group: str = "sbp",
    ) -> None:
        self.flags.append(SbpFlag(code, detail, tier, group))


@dataclass(frozen=True)
class SbpIdentifier:
    raw: str
    marker: str
    calendar: str
    hour: str
    minute: str
    second: str
    reference: str
    control: str
    route: str
    core: str
    tail: str
    encoded_utc: datetime | None = None

    @property
    def slot(self) -> str:
        """Compatibility name for the four-character channel."""
        return self.route

    @property
    def channel(self) -> str:
        return self.route

    @property
    def calendar_time(self) -> str:
        return f"{self.calendar}{self.hour}{self.minute}{self.second}"


@dataclass(frozen=True)
class SbpAtlas:
    markers: frozenset[str] = frozenset()
    controls: frozenset[str] = frozenset()
    routes: frozenset[str] = frozenset()
    cores: frozenset[str] = frozenset()
    tails: frozenset[str] = frozenset()
    combinations: frozenset[tuple[str, str, str, str]] = frozenset()
    core_tails: frozenset[tuple[str, str]] = frozenset()
    deterministic_links: Mapping[tuple[str, str, str], frozenset[str]] = field(
        default_factory=dict
    )
    sources: tuple[str, ...] = ()


def _safe_json(path: Path) -> object:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _iter_samples(data: object) -> Iterable[Mapping[str, Any]]:
    if isinstance(data, list):
        for item in data:
            if isinstance(item, Mapping):
                yield item
    elif isinstance(data, Mapping):
        for key in ("samples", "records", "entries"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, Mapping):
                        yield item


def _opid_from_sample(sample: Mapping[str, Any]) -> str:
    for key in ("sbp_id", "opid", "id", "operation_id"):
        value = sample.get(key)
        if isinstance(value, str) and len(value) == 32:
            return value.upper()
    return ""


def canonical_segments(opid: str) -> dict[str, str]:
    """Alfa SBP: type | calendar/time | reference | control | channel | core | tail.

    Overlapping T-Bank-style linked-tuple slices (route_marker[14], class[17:19],
    suffix[26:32]) are not part of this layout and must not be used.
    """
    value = (opid or "").strip().upper()
    if len(value) < 32:
        value = value.ljust(32)
    return {
        "type": value[0:1],
        "calendar_time": value[1:11],
        "reference": value[11:17],
        "control": value[17:18],
        "channel": value[18:22],
        "core": value[22:27],
        "tail": value[27:32],
    }


def load_generated_atlas(paths: Iterable[Path] | None = None) -> SbpAtlas:
    """Load optional generated data without making startup depend on it."""
    markers: set[str] = set()
    controls: set[str] = set()
    routes: set[str] = set()
    cores: set[str] = set()
    tails: set[str] = set()
    combinations: set[tuple[str, str, str, str]] = set()
    core_tails: set[tuple[str, str]] = set()
    links: dict[tuple[str, str, str], set[str]] = {}
    sources: list[str] = []

    for path in paths or _ATLAS_PATHS:
        data = _safe_json(Path(path))
        if data is None:
            continue
        sources.append(str(path))
        if isinstance(data, Mapping):
            for value in data.get("extensions", ()):
                if isinstance(value, str) and len(value) == 5:
                    tails.add(value)
            for value in data.get("core_suffixes", ()):
                if isinstance(value, str) and len(value) == 5:
                    cores.add(value)

            raw_links = data.get("deterministic_links", {})
            if isinstance(raw_links, Mapping):
                for key, value in raw_links.items():
                    parts = tuple(str(key).split("|"))
                    if len(parts) != 3:
                        continue
                    allowed = value if isinstance(value, list) else [value]
                    valid = frozenset(
                        str(item) for item in allowed if isinstance(item, (str, int))
                    )
                    if valid:
                        links[parts] = set(valid)

        for sample in _iter_samples(data):
            opid = _opid_from_sample(sample)
            if not _ALPHABET_RE.fullmatch(opid):
                continue
            # Also accept sbp_id field from segmentation entries.
            segs = canonical_segments(opid)
            marker, control = segs["type"], segs["control"]
            route, core, tail = segs["channel"], segs["core"], segs["tail"]
            markers.add(marker)
            controls.add(control)
            routes.add(route)
            cores.add(core)
            tails.add(tail)
            combinations.add((marker, control, route, tail))
            core_tails.add((core, tail))

    return SbpAtlas(
        markers=frozenset(markers),
        controls=frozenset(controls),
        routes=frozenset(routes),
        cores=frozenset(cores),
        tails=frozenset(tails),
        combinations=frozenset(combinations),
        core_tails=frozenset(core_tails),
        deterministic_links={key: frozenset(value) for key, value in links.items()},
        sources=tuple(sources),
    )


def extract_sbp_id(text: str) -> str | None:
    compact = re.sub(r"\s+", "", (text or "").upper())
    match = re.search(r"(?<![A-Z0-9])([A-Z][0-9A-Z]{31})(?![A-Z0-9])", compact)
    return match.group(1) if match else None


def extract_completion_datetime(text: str) -> datetime | None:
    raw = (text or "").replace("\xa0", " ").replace("\u202f", " ")
    low = raw.lower()
    match = None
    for label in ("дата и время перевода", "дата и время операции", "дата операции"):
        start = low.find(label)
        if start >= 0:
            match = _DATE_RE.search(raw[start : start + 120])
            if match:
                break
    if not match:
        match = _DATE_RE.search(raw)
    if not match:
        return None
    day, month, year, hour, minute, second = match.groups()
    try:
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0)
        )
    except ValueError:
        return None


def _decode_datetime(identifier: str) -> datetime | None:
    try:
        calendar_value = int(identifier[1:5])
        year = 2020 + calendar_value // 1000
        day_of_year = calendar_value % 1000
        if day_of_year < 1:
            return None
        start = datetime(year, 1, 1)
        date = start + timedelta(days=day_of_year - 1)
        if date.year != year:
            return None
        return date.replace(
            hour=int(identifier[5:7]),
            minute=int(identifier[7:9]),
            second=int(identifier[9:11]),
        )
    except (TypeError, ValueError, OverflowError):
        return None


def parse_sbp_id(identifier: str) -> SbpIdentifier:
    """Slice a 32-character identifier; malformed values remain inspectable."""
    value = (identifier or "").strip().upper()
    return SbpIdentifier(
        raw=value,
        marker=value[0:1],
        calendar=value[1:5],
        hour=value[5:7],
        minute=value[7:9],
        second=value[9:11],
        reference=value[11:17],
        control=value[17:18],
        route=value[18:22],
        core=value[22:27],
        tail=value[27:32],
        encoded_utc=_decode_datetime(value) if len(value) == 32 else None,
    )


parse_identifier = parse_sbp_id


def _add_empirical(result: SbpResult, details: list[str]) -> None:
    if details:
        result.add(
            "ALFA_SBP_EMPIRICAL_PROFILE",
            "; ".join(details),
            tier="B",
            group="B6_sbp_empirical",
        )



def validate_sbp_id(
    identifier: str,
    text: str = "",
    *,
    completion_datetime: datetime | None = None,
    atlas: SbpAtlas | None = None,
) -> SbpResult:
    """Validate deterministic structure/time and observe empirical slots.

    Unknown marker/control/route/tail combinations are always Tier-B.  They
    become hard only if an optional generated atlas explicitly declares a
    deterministic ``marker|control|route -> allowed tails`` relation.
    """
    parsed = parse_sbp_id(identifier)
    result = SbpResult(stats={"identifier": parsed.raw, "length": len(parsed.raw)})

    if len(parsed.raw) != 32:
        result.add(
            "ALFA_SBP_ID_STRUCTURE_INVALID",
            f"identifier length is {len(parsed.raw)}, expected 32",
        )
        return result
    if not _ALPHABET_RE.fullmatch(parsed.raw):
        result.add(
            "ALFA_SBP_ID_STRUCTURE_INVALID",
            "identifier must contain exactly 32 uppercase Latin letters/digits",
        )
        return result

    segs = canonical_segments(parsed.raw)
    result.stats.update(
        {
            "marker": parsed.marker,
            "type": segs["type"],
            "calendar": parsed.calendar,
            "calendar_time": segs["calendar_time"],
            "hour": parsed.hour,
            "minute": parsed.minute,
            "second": parsed.second,
            "reference": parsed.reference,
            "control": parsed.control,
            "route": parsed.route,
            "channel": segs["channel"],
            "slot": parsed.slot,
            "core": parsed.core,
            "tail": parsed.tail,
        }
    )

    if not parsed.calendar.isdigit() or not all(
        value.isdigit() for value in (parsed.hour, parsed.minute, parsed.second)
    ):
        result.add(
            "ALFA_SBP_ID_STRUCTURE_INVALID",
            "calendar/time positions [1:11] must be decimal digits",
        )
    elif parsed.encoded_utc is None:
        result.add(
            "ALFA_SBP_ID_CALENDAR_CONFLICT",
            f"calendar/time block {parsed.raw[1:11]!r} is not a valid UTC timestamp",
        )

    if not re.fullmatch(r"[0-9A-Z]{6}", parsed.reference):
        result.add(
            "ALFA_SBP_ID_STRUCTURE_INVALID",
            f"reference {parsed.reference!r} has invalid structure",
        )
    elif parsed.reference[-1] != "0":
        result.add(
            "ALFA_SBP_ID_STRUCTURE_INVALID",
            f"reference final position [16] is {parsed.reference[-1]!r}, expected '0'",
        )
    if not parsed.control.isalnum() or not parsed.control.isascii():
        result.add(
            "ALFA_SBP_ID_STRUCTURE_INVALID",
            f"control position [17] is invalid: {parsed.control!r}",
        )
    if not parsed.route.isdigit():
        result.add(
            "ALFA_SBP_ID_STRUCTURE_INVALID",
            f"channel [18:22] is not numeric: {parsed.route!r}",
        )
    if not parsed.core.isdigit():
        result.add(
            "ALFA_SBP_ID_STRUCTURE_INVALID",
            f"core [22:27] is not numeric: {parsed.core!r}",
        )
    if not parsed.tail.isdigit():
        result.add(
            "ALFA_SBP_ID_STRUCTURE_INVALID",
            f"tail [27:32] is not numeric: {parsed.tail!r}",
        )

    completion = completion_datetime or extract_completion_datetime(text)
    if completion:
        result.stats["completion_datetime"] = completion.isoformat(sep=" ")
    if completion and parsed.encoded_utc:
        encoded_local = parsed.encoded_utc + timedelta(hours=3)
        result.stats["encoded_utc"] = parsed.encoded_utc.isoformat(sep=" ")
        result.stats["encoded_local"] = encoded_local.isoformat(sep=" ")
        allowed_dates = {completion.date(), (completion - timedelta(days=1)).date()}
        if encoded_local.date() not in allowed_dates:
            result.add(
                "ALFA_SBP_ID_CALENDAR_CONFLICT",
                f"encoded local date {encoded_local.date()} is neither completion "
                f"day {completion.date()} nor previous day",
            )
        lag = completion - encoded_local
        result.stats["completion_lag_seconds"] = lag.total_seconds()
        # Seconds equality and a literal :00 carry no evidentiary meaning.
        if lag < timedelta(0):
            result.add(
                "ALFA_SBP_ID_TIME_ORDER_CONFLICT",
                f"encoded time {encoded_local.time()} is later than completion "
                f"{completion.time()}",
            )
        elif lag > _MAX_COMPLETION_LAG:
            result.add(
                "ALFA_SBP_ID_TIME_ORDER_CONFLICT",
                f"encoded time precedes completion by {lag}, over the 3h profile",
            )

    atlas = atlas or load_generated_atlas()
    result.stats["atlas_sources"] = list(atlas.sources)
    combination = (parsed.marker, parsed.control, parsed.route, parsed.tail)
    empirical: list[str] = []
    if atlas.markers and parsed.marker not in atlas.markers:
        empirical.append(f"unknown marker {parsed.marker}")
    if atlas.controls and parsed.control not in atlas.controls:
        empirical.append(f"unknown control {parsed.control}")
    if atlas.routes and parsed.route not in atlas.routes:
        empirical.append(f"unknown channel {parsed.route}")
    # Unknown core/tail is observational only (Tier-B at most).
    # Never HARD from absence in the closed corpus ending 2026-06-29
    # (historically core∈{00116,00117}); new emitters such as 00118/810101
    # must not decide authenticity alone.
    if atlas.cores and parsed.core not in atlas.cores:
        empirical.append(f"unknown core {parsed.core}")
    if atlas.tails and parsed.tail not in atlas.tails:
        empirical.append(f"unknown tail {parsed.tail}")
    if atlas.combinations and combination not in atlas.combinations:
        empirical.append(
            "unknown marker/control/route/tail combination "
            + "/".join(combination)
        )
    _add_empirical(result, empirical)
    result.stats["empirical_combination_observed"] = (
        combination in atlas.combinations if atlas.combinations else None
    )

    deterministic_key = (parsed.marker, parsed.control, parsed.route)
    allowed_tails = atlas.deterministic_links.get(deterministic_key)
    if allowed_tails and parsed.tail not in allowed_tails:
        result.add(
            "ALFA_SBP_ATLAS_LINK_MISMATCH",
            f"atlas deterministically links {'/'.join(deterministic_key)} to "
            f"{sorted(allowed_tails)}, not {parsed.tail}",
            group="sbp_atlas",
        )
    return result


validate_identifier = validate_sbp_id


def validate_sbp_text(text: str, atlas: SbpAtlas | None = None) -> SbpResult:
    identifier = extract_sbp_id(text)
    if identifier is None:
        result = SbpResult()
        result.add("ALFA_SBP_ID_MISSING", "no 32-character SBP identifier found")
        return result
    return validate_sbp_id(identifier, text, atlas=atlas)
