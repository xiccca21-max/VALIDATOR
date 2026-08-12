"""Классификация FontFile2: known / suspicious / forgery (без whitelist-hard)."""

from __future__ import annotations

# Invariant breaks → tier forgery (уже должны дать отдельные hard-флаги)
_INVARIANT_FORGERY_CODES = frozenset({
    "USED_CID_MISSING_FROM_CMAP",
    "USED_CID_MISSING_FROM_W",
    "USED_CID_CMAP_MISMATCH",
    "CMAP_W_MISMATCH",
    "CMAP_INVALID",
    "FONTFILE2_CID_MISSING",
    "BROKEN_GLYPH_ZERO_LENGTH",
    "GLYPH_BBOX_IMPOSSIBLE",
    "LOCA_TABLE_BROKEN",
    "TTF_NUMGLYPHS_MISMATCH",
    "TTF_HMTX_COUNT_MISMATCH",
    "TTF_CHECKSUM_ADJUSTMENT_INVALID",
    "broken_glyphmap",
})

_INVARIANT_FORGERY_PREFIXES = (
    "GLYPH_TTF_",
)


def _flag_codes(flags: list[str]) -> set[str]:
    import re
    rx = re.compile(r"^\[([A-Z0-9_]+)\]")
    out: set[str] = set()
    for f in flags:
        m = rx.match(f or "")
        if m:
            out.add(m.group(1))
    return out


def classify_font_stack(
    *,
    ff2_triplet_known: bool,
    ff2_unknown_layers: list[str],
    flag_lines: list[str],
) -> tuple[str, str]:
    """
    known      — triplet/layers в корпусе
    suspicious — новый subset, но инварианты целы (PASS)
    forgery    — новый subset + сломанные CID/glyph/hmtx (уже в flags)
    """
    codes = _flag_codes(flag_lines)
    for code in codes:
        if code in _INVARIANT_FORGERY_CODES:
            return "forgery", "новый subset + нарушена внутренняя согласованность шрифта"
        if any(code.startswith(p) for p in _INVARIANT_FORGERY_PREFIXES):
            return "forgery", "новый subset + чужие контуры символов"

    if ff2_triplet_known and not ff2_unknown_layers:
        return "known", "известный набор FontFile2 из корпуса оригиналов"

    if ff2_unknown_layers:
        layers = ", ".join(ff2_unknown_layers)
        return (
            "suspicious",
            f"новый subset ({layers}) — glyf/CID/hmtx в норме, не ФЕЙК",
        )

    return "known", "шрифтовый стек без отклонений"


def append_unknown_layer_stats(details: dict, fingerprints: dict, pools: dict[str, set[str]]) -> None:
    """Логируем неизвестные слои как SUSPICIOUS, не FAKE."""
    for layer in ("F1", "F2", "F3"):
        fp = fingerprints.get(layer)
        if not fp:
            continue
        h = fp["sha256_16"]
        if h not in pools.get(layer, set()):
            details.setdefault("stats_only", []).append(
                f"[FF2_{layer}_SUBSET_UNKNOWN] {layer}={h} ({fp['size']} B) "
                f"не в корпусе — только подозрительно"
            )
