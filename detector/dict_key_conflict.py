"""Dictionary-level duplicate critical key conflict auditor."""

from __future__ import annotations

import re
from typing import Any

from .structural_deep_xref_stream import DeepAuditResult, StructFinding

CRITICAL_KEYS = frozenset({
    b"/Length",
    b"/Contents",
    b"/Resources",
    b"/Root",
    b"/Pages",
    b"/Parent",
    b"/Type",
    b"/Subtype",
    b"/Font",
    b"/XObject",
    b"/Filter",
    b"/DecodeParms",
    b"/MediaBox",
    b"/CropBox",
})

# Keys where first-vs-last value changes graph / streams / render
GRAPH_CRITICAL = frozenset({
    b"/Contents",
    b"/Resources",
    b"/Root",
    b"/Pages",
    b"/Parent",
    b"/Length",
    b"/Font",
    b"/XObject",
    b"/Filter",
    b"/DecodeParms",
})


def _skip_string(data: bytes, i: int) -> int:
    """Skip PDF literal string starting at '('."""
    assert data[i : i + 1] == b"("
    i += 1
    depth = 1
    while i < len(data) and depth:
        c = data[i]
        if c == 0x5C:  # backslash
            i += 2
            continue
        if c == 0x28:  # (
            depth += 1
        elif c == 0x29:  # )
            depth -= 1
        i += 1
    return i


def _skip_hex_or_dict_delim(data: bytes, i: int) -> int:
    """Skip <...> hex string; caller must not be at <<."""
    assert data[i : i + 1] == b"<"
    i += 1
    while i < len(data) and data[i : i + 1] != b">":
        i += 1
    return i + 1 if i < len(data) else i


def _normalize_value(raw: bytes) -> bytes:
    return re.sub(rb"\s+", b" ", raw.strip())


def _parse_dicts(pdf_bytes: bytes) -> list[tuple[int, dict[bytes, list[bytes]]]]:
    """Return list of (offset, key -> list of raw values) for each <<...>> dict.

    Stream bodies are skipped so binary noise is not mistaken for keys.
    """
    data = pdf_bytes
    n = len(data)
    i = 0
    dicts: list[tuple[int, dict[bytes, list[bytes]]]] = []
    stack: list[tuple[int, dict[bytes, list[bytes]], int]] = []
    # Each stack item: (start_offset, key_map, parse_pos_after_<<)

    while i < n:
        # Skip stream payloads using nearest /Length when inside an object — coarse:
        # when we see 'stream' newline, jump to endstream
        if data[i : i + 6] == b"stream" and (i == 0 or data[i - 1 : i] in b"\r\n \t>"):
            j = i + 6
            if data[j : j + 2] == b"\r\n":
                j += 2
            elif data[j : j + 1] in b"\r\n":
                j += 1
            es = data.find(b"endstream", j)
            if es > 0:
                i = es + 9
                continue

        if data[i : i + 2] == b"<<":
            stack.append((i, {}, i + 2))
            i += 2
            continue

        if data[i : i + 2] == b">>":
            if stack:
                start, keymap, _ = stack.pop()
                dicts.append((start, keymap))
            i += 2
            continue

        if data[i : i + 1] == b"(":
            i = _skip_string(data, i)
            continue

        if data[i : i + 1] == b"<" and data[i : i + 2] != b"<<":
            i = _skip_hex_or_dict_delim(data, i)
            continue

        if stack and data[i : i + 1] == b"/":
            # Parse name
            m = re.match(rb"/[A-Za-z0-9_.#+-]+", data[i : i + 64])
            if not m:
                i += 1
                continue
            key = m.group(0)
            # Canonicalize escaped names lightly: /Foo#20Bar already in bytes
            j = i + len(key)
            while j < n and data[j : j + 1] in b"\x00\r\n \t":
                j += 1
            # Value extent: until next key or >> at this nesting (approx)
            vstart = j
            depth = 0
            k = j
            while k < n:
                if data[k : k + 2] == b"<<":
                    depth += 1
                    k += 2
                    continue
                if data[k : k + 2] == b">>":
                    if depth == 0:
                        break
                    depth -= 1
                    k += 2
                    continue
                if depth == 0 and data[k : k + 1] == b"/" and k > j:
                    # next key at same level
                    break
                if depth == 0 and data[k : k + 1] == b"(":
                    k = _skip_string(data, k)
                    continue
                if depth == 0 and data[k : k + 1] == b"<" and data[k : k + 2] != b"<<":
                    k = _skip_hex_or_dict_delim(data, k)
                    continue
                if depth == 0 and data[k : k + 1] == b"[":
                    # skip array roughly
                    ad = 1
                    k += 1
                    while k < n and ad:
                        if data[k : k + 1] == b"(":
                            k = _skip_string(data, k)
                            continue
                        if data[k : k + 1] == b"[":
                            ad += 1
                        elif data[k : k + 1] == b"]":
                            ad -= 1
                        k += 1
                    continue
                k += 1
            val = data[vstart:k]
            if key in CRITICAL_KEYS or key.split(b"#")[0] in CRITICAL_KEYS:
                stack[-1][1].setdefault(key, []).append(val)
            i = k
            continue

        i += 1

    return dicts


def _values_conflict(vals: list[bytes]) -> bool:
    norms = [_normalize_value(v) for v in vals]
    return len(set(norms)) > 1


def audit_duplicate_critical_dict_keys(pdf_bytes: bytes) -> DeepAuditResult:
    res = DeepAuditResult()
    dicts = _parse_dicts(pdf_bytes)
    conflicts = 0
    for offset, keymap in dicts:
        for key, vals in keymap.items():
            if len(vals) < 2:
                continue
            if not _values_conflict(vals):
                # identical repeats — not HARD
                continue
            base = key.split(b"#")[0]
            if base not in CRITICAL_KEYS and key not in CRITICAL_KEYS:
                continue
            conflicts += 1
            first = _normalize_value(vals[0])
            last = _normalize_value(vals[-1])
            # Prefer HARD when graph-critical
            code = "DUPLICATE_CRITICAL_DICT_KEY_CONFLICT"
            detail = (
                f"dictionary@{offset} duplicate {key.decode('latin1', 'replace')} "
                f"with conflicting values: first={first[:80]!r} last={last[:80]!r}"
            )
            if base in GRAPH_CRITICAL or key in GRAPH_CRITICAL:
                detail += (
                    "; first-vs-last changes object graph / stream / page contents"
                )
            res.add(StructFinding(
                code=code,
                detail=detail,
                offset=offset,
                expected=first[:120].decode("latin1", "replace"),
                actual=last[:120].decode("latin1", "replace"),
                parser_stage="dict_key_conflict",
            ))
            # Proven parse ambiguity for graph-critical conflicts
            if base in {b"/Contents", b"/Root", b"/Pages", b"/Length"} or key in {
                b"/Contents", b"/Root", b"/Pages", b"/Length"
            }:
                res.add(StructFinding(
                    code="PDF_CRITICAL_PARSE_AMBIGUITY",
                    detail=(
                        f"Page/stream critical key {key.decode('latin1', 'replace')} "
                        f"resolves differently first-value vs last-value at dict@{offset}: "
                        f"{first[:60]!r} vs {last[:60]!r}"
                    ),
                    offset=offset,
                    expected=first[:120].decode("latin1", "replace"),
                    actual=last[:120].decode("latin1", "replace"),
                    parser_stage="dict_key_conflict.ambiguity",
                ))
    res.stats["dicts_scanned"] = len(dicts)
    res.stats["critical_conflicts"] = conflicts
    return res
