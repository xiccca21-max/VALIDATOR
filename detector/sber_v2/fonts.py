"""Font layer contamination / CID closure for Sber v2."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from io import BytesIO

from ..pdf_forensics import Weight, run_pdf_forensics
from ..sber_profiles import detect_generator_path
from .atlas import atlas_profile
from .types import SberFlag

try:
    from fontTools.ttLib import TTFont
except ImportError:  # pragma: no cover
    TTFont = None  # type: ignore

_FONT_HARD = frozenset({
    "USED_CID_MISSING_FROM_CMAP",
    "CMAP_INVALID",
    "USED_CID_MISSING_FROM_W",
    "FONTFILE2_MISSING",
    "MISSING_FONT_OBJECT",
    "GLYPH_OUTLINE_MISMATCH",
    "USED_CID_EMPTY_GLYPH",
    "GLYPH_SLOT_TRANSPLANT",
})
_JASPER_SOFT = frozenset({
    "W_ARRAY_PRETTY_PRINTED",
    "W_ARRAY_SERIALIZATION_ANOMALY",
    "CMAP_W_MISMATCH",
    "W_EXTRA_CID",
    "MISSING_WIDTH_TABLE",
})

# Novelty FontFile2 sha blacklist retired (genuine FPs). Structural/rebuild only.
#
# Decompressed FontFile2 byte-length envelopes by profile (atlas of genuines).
# SEQ rebuilds for sber_internal_jasper keep /Length≈24695 but inflate glyf to
# ≥56332 B; genuines in this profile sit at 55136 / 55476 / 56064 only.
# (min_dec, max_dec, n_atlas, slack_bytes)
_FF2_DEC_ENVELOPES: dict[str, tuple[int, int, int, int]] = {
    # (min_dec, max_dec, n_atlas, slack_bytes)
    "sber_internal_jasper": (55_136, 56_064, 15, 150),
    # SBP jasper: genuines 51944–53912; SEQ rebuilds inflate to ≥56180
    "sbp_outgoing": (51_944, 53_912, 14, 250),
    "sbp_request": (51_944, 53_912, 14, 250),
}
# Compressed FontFile2 stream length (raw /Length body). Newer SEQ keeps
# decoded size inside the envelope above but recompresses to ~21–23 KB;
# genuines for sber_internal_jasper sit at ~24695–25383.
# (min_raw, max_raw, n_atlas, slack_bytes)
_FF2_RAW_ENVELOPES: dict[str, tuple[int, int, int, int]] = {
    "sber_internal_jasper": (24_695, 25_383, 5, 250),
}

# Exact decoded FontFile2 sizes for sber_internal_jasper genuines (n=15).
# Soft envelope above is too wide for SEQ near-miss shells (55568, 55368…).
_INTERNAL_FF2_DEC_ALLOWED: frozenset[int] = frozenset({55_136, 55_476, 56_064})

# sbp_outgoing genuines (n=41): unique nonempty glyf payload lengths ∈ [52,56].
# SEQ hard shells inflate to 57–62; CLEAN 180323 under-subsets to 45.
_SBP_OUTGOING_UNIQ_LENS_MIN = 52
_SBP_OUTGOING_UNIQ_LENS_MAX = 56
# nonempty glyph count corpus 66–73; SEQ packs 80–85 or under-subsets to 52.
_SBP_OUTGOING_NONEMPTY_MIN = 66
_SBP_OUTGOING_NONEMPTY_MAX = 73
# Compressed FontFile2 body: genuines 22855–23965; SEQ CLEAN use ~19271.
_SBP_OUTGOING_FF2_RAW_MIN = 22_000
# Unique positive hmtx advances: genuines always 425 (n=14 unique /
# sbp_outgoing). SEQ CLEAN 180546+ reassemble to 428–430.
_SBP_OUTGOING_HMTX_UNIQ_ADVANCES = 425
# Content stream length floor (forensics content_stream_size).
# Genuines ≥3558; SEQ CLEAN 180548 = 3554.
_SBP_OUTGOING_CONTENT_LEN_MIN = 3558


def _glyf_subset_stats(dec: bytes) -> tuple[int | None, int | None]:
    """Return (uniq_nonempty_lens, nonempty_count via loca length>0)."""
    if TTFont is None or not dec:
        return None, None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tt = TTFont(BytesIO(dec))
        loca = tt["loca"]
        n = int(tt["maxp"].numGlyphs)
        lens: set[int] = set()
        nonempty = 0
        for i in range(n):
            ln = int(loca[i + 1]) - int(loca[i])
            if ln > 0:
                lens.add(ln)
                nonempty += 1
        return len(lens), nonempty
    except Exception:
        return None, None


def _glyf_contour_nonempty(dec: bytes) -> int | None:
    """Glyphs with numberOfContours != 0 (excludes zero-contour loca stubs)."""
    if TTFont is None or not dec:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tt = TTFont(BytesIO(dec))
        glyf = tt["glyf"]
        return sum(
            1
            for name in tt.getGlyphOrder()
            if int(getattr(glyf[name], "numberOfContours", 0) or 0) != 0
        )
    except Exception:
        return None


def _hmtx_unique_pos_advances(dec: bytes) -> int | None:
    """Cardinality of distinct positive hmtx advanceWidths."""
    if TTFont is None or not dec:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tt = TTFont(BytesIO(dec))
        metrics = tt["hmtx"].metrics
        return len({int(m[0]) for m in metrics.values() if int(m[0]) > 0})
    except Exception:
        return None


def _glyf_uniq_nonempty_lens(dec: bytes) -> int | None:
    uniq, _ = _glyf_subset_stats(dec)
    return uniq

@dataclass
class CheckResult:
    flags: list[SberFlag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    analysis_ok: bool = True


def sfnt_trailing_nonzero(font: bytes) -> int:
    """Count nonzero bytes after the last declared SFNT table.

    Live Sber FontFile2 programs end on the last table plus zero alignment.
    Nonzero bytes past that point are length padding, not glyph data.
    """
    if len(font) < 12 or font[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return 0
    count = int.from_bytes(font[4:6], "big")
    if count <= 0 or 12 + 16 * count > len(font):
        return 0
    end = 0
    for index in range(count):
        entry = 12 + 16 * index
        offset = int.from_bytes(font[entry + 8:entry + 12], "big")
        length = int.from_bytes(font[entry + 12:entry + 16], "big")
        if offset < 0 or length < 0:
            continue
        end = max(end, offset + length)
    if end <= 0 or end >= len(font):
        return 0
    return sum(1 for byte in font[end:] if byte)


def _f(code: str, detail: str, *, tier: str = "HARD", group: str = "font") -> SberFlag:
    return SberFlag(code=code, detail=detail, tier=tier, group=group, rule_id=code)


def check_font_contamination(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
    profile_id: str = "",
) -> CheckResult:
    out = CheckResult()
    try:
        gen = detect_generator_path(producer, creator)
        out.stats["generator"] = gen
        forensic = run_pdf_forensics(pdf_bytes, bank="sber", tier="jasper")
        out.stats["forensics"] = forensic.stats

        hard_hits = 0
        for f in forensic.flags:
            if gen in ("jasper_itext", "pdfium") and f.code in _JASPER_SOFT:
                out.flags.append(_f(f.code, f.detail, tier="DIAGNOSTIC"))
                continue
            if f.code in _FONT_HARD and f.weight == Weight.HIGH:
                hard_hits += 1
                out.flags.append(_f(f.code, f.detail))
                out.flags.append(_f(
                    "SBER_FONT_LAYER_CONTAMINATION",
                    f"{f.code}: {f.detail}",
                ))
            elif f.weight == Weight.HIGH:
                out.flags.append(_f(
                    f.code, f.detail, tier="DIAGNOSTIC",
                ))

        # Unknown FontFile2 vs atlas → diagnostic only (never solo HARD)
        import hashlib
        import re
        import zlib
        known = set(atlas_profile(profile_id).get("fontfile2_sha16") or [])
        env = _FF2_DEC_ENVELOPES.get(profile_id or "")
        raw_env = _FF2_RAW_ENVELOPES.get(profile_id or "")
        ff2_decs: list[int] = []
        ff2_raws: list[int] = []
        for m in re.finditer(rb"/FontFile2\s+(\d+)\s+\d+\s+R", pdf_bytes):
            onum = int(m.group(1))
            pat = re.compile(rf"{onum}\s+0\s+obj(.*?)endobj".encode(), re.S)
            om = pat.search(pdf_bytes)
            if not om:
                continue
            sm = re.search(rb"stream\r?\n(.*?)\n?endstream", om.group(1), re.S)
            if not sm:
                continue
            raw = sm.group(1)
            try:
                dec = zlib.decompress(raw)
            except Exception:
                dec = raw
            ff2_decs.append(len(dec))
            ff2_raws.append(len(raw))
            trailing = sfnt_trailing_nonzero(dec)
            out.stats["font_trailing_nonzero"] = trailing
            if trailing:
                out.flags.append(_f(
                    "SBER_FONT_TRAILING_ENTROPY",
                    (
                        f"FontFile2 obj {onum}: после последней таблицы шрифта "
                        f"{trailing} ненулевых байт. У живых чеков Сбера там "
                        f"только нулевое выравнивание"
                    ),
                ))
            h16 = hashlib.sha256(dec).hexdigest()[:16]
            # Novelty FontFile2 sha blacklists disabled (genuine FP risk).
            # Keep diagnostic observation of atlas-unknown fonts only.
            if known and h16 not in known:
                out.flags.append(_f(
                    "SBER_NEW_FONTFILE2_SHA",
                    f"новый FontFile2 sha16={h16} (diagnostic)",
                    tier="DIAGNOSTIC",
                ))

            if env and len(dec) > 0:
                amin, amax, n_atlas, slack = env
                if n_atlas >= 5:
                    lo, hi = amin - slack, amax + slack
                    if len(dec) < lo or len(dec) > hi:
                        side = "больше" if len(dec) > hi else "меньше"
                        out.flags.append(_f(
                            "SBER_FONTFILE2_SIZE_STRONG_OUTLIER",
                            (
                                f"FontFile2 decoded {len(dec)} B — сильно {side} "
                                f"эталона профиля {profile_id} "
                                f"(atlas {amin}–{amax}, n={n_atlas}; "
                                f"порог HARD {lo}–{hi})"
                            ),
                        ))

            # Exact size profile for internal Jasper (not soft envelope).
            if (
                profile_id == "sber_internal_jasper"
                and len(dec) > 0
                and len(dec) not in _INTERNAL_FF2_DEC_ALLOWED
            ):
                allowed = ", ".join(str(v) for v in sorted(_INTERNAL_FF2_DEC_ALLOWED))
                out.flags.append(_f(
                    "SBER_FONTFILE2_DEC_PROFILE",
                    (
                        f"FontFile2 decoded {len(dec)} B вне корпуса "
                        f"sber_internal_jasper ({allowed}; n=15) — чужой "
                        f"subset/reassembly FontFile2"
                    ),
                ))

            # Unique nonempty glyf lengths + nonempty cardinality.
            if profile_id in ("sbp_outgoing", "sbp_request") and len(dec) > 0:
                uniq, nonempty = _glyf_subset_stats(dec)
                out.stats.setdefault("glyf_uniq_nonempty_lens", []).append(uniq)
                out.stats.setdefault("glyf_nonempty_count", []).append(nonempty)
                if (
                    uniq is not None
                    and profile_id == "sbp_outgoing"
                    and (
                        uniq < _SBP_OUTGOING_UNIQ_LENS_MIN
                        or uniq > _SBP_OUTGOING_UNIQ_LENS_MAX
                    )
                ):
                    out.flags.append(_f(
                        "SBER_FONT_GLYF_UNIQ_LENS",
                        (
                            f"unique nonempty glyf lengths={uniq} вне "
                            f"[{_SBP_OUTGOING_UNIQ_LENS_MIN},"
                            f"{_SBP_OUTGOING_UNIQ_LENS_MAX}] (корпус "
                            f"sbp_outgoing n=41) — пересобранный glyf "
                            f"payload / чужой subsetter"
                        ),
                    ))
                if (
                    nonempty is not None
                    and profile_id == "sbp_outgoing"
                    and (
                        nonempty < _SBP_OUTGOING_NONEMPTY_MIN
                        or nonempty > _SBP_OUTGOING_NONEMPTY_MAX
                    )
                ):
                    out.flags.append(_f(
                        "SBER_FONT_GLYF_NONEMPTY_COUNT",
                        (
                            f"nonempty glyphs={nonempty} вне "
                            f"[{_SBP_OUTGOING_NONEMPTY_MIN},"
                            f"{_SBP_OUTGOING_NONEMPTY_MAX}] (корпус "
                            f"sbp_outgoing n=41) — чужой glyf subset в "
                            f"FontFile2"
                        ),
                    ))

                # Contour-nonempty (not just loca length>0). SEQ near-miss
                # shells pad loca stubs with zero-contour glyf so loca-count
                # lands in [66,73] while real outlines stay ~55–60.
                # Genuines: contour == loca nonempty ∈ [66,73] (n=14 unique).
                if profile_id == "sbp_outgoing":
                    contours = _glyf_contour_nonempty(dec)
                    out.stats.setdefault("glyf_contour_nonempty", []).append(
                        contours
                    )
                    if contours is not None and (
                        contours < _SBP_OUTGOING_NONEMPTY_MIN
                        or contours > _SBP_OUTGOING_NONEMPTY_MAX
                    ):
                        out.flags.append(_f(
                            "SBER_FONT_GLYF_CONTOUR_NONEMPTY",
                            (
                                f"contour-nonempty glyphs={contours} вне "
                                f"[{_SBP_OUTGOING_NONEMPTY_MIN},"
                                f"{_SBP_OUTGOING_NONEMPTY_MAX}] (корпус "
                                f"sbp_outgoing; loca_nonempty={nonempty}) — "
                                f"zero-contour glyf stubs / чужой subsetter"
                            ),
                        ))
                    elif (
                        contours is not None
                        and nonempty is not None
                        and contours != nonempty
                    ):
                        out.flags.append(_f(
                            "SBER_FONT_GLYF_LOCA_CONTOUR_MISMATCH",
                            (
                                f"loca_nonempty={nonempty} ≠ "
                                f"contour_nonempty={contours} (корпус "
                                f"sbp_outgoing: всегда равны) — ghost glyf "
                                f"slots без контуров"
                            ),
                        ))

                    # hmtx advanceWidth vocabulary size — Jasper SBP genuines
                    # always expose exactly 425 distinct positive advances;
                    # SEQ rebuilds that pass contour/loca pads still drift.
                    n_adv = _hmtx_unique_pos_advances(dec)
                    out.stats.setdefault("hmtx_uniq_pos_advances", []).append(
                        n_adv
                    )
                    if (
                        n_adv is not None
                        and n_adv != _SBP_OUTGOING_HMTX_UNIQ_ADVANCES
                    ):
                        out.flags.append(_f(
                            "SBER_FONT_HMTX_UNIQ_ADVANCES",
                            (
                                f"hmtx unique positive advances={n_adv} "
                                f"≠ {_SBP_OUTGOING_HMTX_UNIQ_ADVANCES} "
                                f"(корпус sbp_outgoing всегда "
                                f"{_SBP_OUTGOING_HMTX_UNIQ_ADVANCES}; "
                                f"n=14 unique) — чужой hmtx / subsetter"
                            ),
                        ))

            # Compressed FontFile2 too small ⇒ foreign Flate/subset packing.
            if (
                profile_id == "sbp_outgoing"
                and len(raw) > 0
                and len(raw) < _SBP_OUTGOING_FF2_RAW_MIN
            ):
                out.flags.append(_f(
                    "SBER_FONTFILE2_RAW_TOO_SMALL",
                    (
                        f"FontFile2 compressed {len(raw)} B < "
                        f"{_SBP_OUTGOING_FF2_RAW_MIN} (корпус ≥22855; n=41) "
                        f"— чужая Flate-упаковка / subset FontFile2"
                    ),
                ))

            if raw_env and len(raw) > 0:
                rmin, rmax, n_atlas, slack = raw_env
                if n_atlas >= 5:
                    lo, hi = rmin - slack, rmax + slack
                    if len(raw) < lo or len(raw) > hi:
                        side = "больше" if len(raw) > hi else "меньше"
                        out.flags.append(_f(
                            "SBER_FONTFILE2_SIZE_STRONG_OUTLIER",
                            (
                                f"FontFile2 compressed {len(raw)} B — сильно {side} "
                                f"эталона профиля {profile_id} "
                                f"(atlas raw {rmin}–{rmax}, n={n_atlas}; "
                                f"порог HARD {lo}–{hi})"
                            ),
                        ))

        out.stats["fontfile2_decoded_sizes"] = ff2_decs
        out.stats["fontfile2_compressed_sizes"] = ff2_raws

        # Content-stream length floor for sbp_outgoing Jasper shell.
        if profile_id == "sbp_outgoing":
            clen = forensic.stats.get("content_stream_size")
            out.stats["content_stream_size"] = clen
            if (
                isinstance(clen, int)
                and clen > 0
                and clen < _SBP_OUTGOING_CONTENT_LEN_MIN
            ):
                out.flags.append(_f(
                    "SBER_CONTENT_STREAM_TOO_SHORT",
                    (
                        f"content stream {clen} B < "
                        f"{_SBP_OUTGOING_CONTENT_LEN_MIN} "
                        f"(корпус sbp_outgoing ≥3558; n=14 unique) — "
                        f"урезанный/пересобранный content"
                    ),
                ))

        out.stats["font_hard_hits"] = hard_hits
    except Exception as exc:
        out.analysis_ok = False
        out.stats["error"] = str(exc)[:200]
    return out
