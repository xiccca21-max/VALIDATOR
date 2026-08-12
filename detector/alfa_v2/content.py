"""Content-stream AST and independent text-layer consistency checks."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import fitz
except ImportError:  # optional analyzer; absence must not manufacture evidence
    fitz = None

from .pdfutil import objects, refs, stream_role
from .streams import identify_emitter
from .types import ForensicResult

ATLAS_DIR = Path(__file__).with_name("atlas_data")
RULE_GROUP = "alfa_v2.content"

# Exact max decoded /Contents lengths (чеки corpus). SEQ sits in envelope
# gaps (e.g. Oracle 3417–3423 / 5158+; Quartz 5061–5063).
_ORACLE_CONTENT_DECODED_EXACT: frozenset[int] = frozenset({
    3413, 4152, 5091, 5095, 5099, 5103, 5111, 5115, 5139, 5151, 5542,
})
_QUARTZ_CONTENT_DECODED_EXACT: frozenset[int] = frozenset({
    5012, 6004, 6125, 6134, 6160, 6166, 6174, 6175, 6183, 6191, 6195, 6204,
    6224, 6231, 6243, 6246, 6253, 6258, 6264, 6265, 6269, 6293, 6302, 6325,
    6359, 6413, 12675,
})
# Exact SHA16 of max decoded /Contents body (чеки corpus). SEQ CLEAN 181707
# hit Oracle len=3413 (in length atlas) but body sha ∉ genuines (0/30).
_ORACLE_CONTENT_BODY_SHA16: frozenset[str] = frozenset({
    "0cda9895f9416e74", "1d557eac95fb416d", "2e3275575c57f046", "441a9abbcf272cf3",
    "529814492d0aa773", "610a246b31c889f3", "677e0451e758e453", "810f3b9964a2bcb2",
    "837d18f279670717", "9838608702e61777", "bb41bd894be997c1", "cdb3de2a385054f9",
    "ce92930fdfd3a102", "d637ebba9cdd20c5", "dfcb60239bb820cf", "fab33714b19ba142",
})
_QUARTZ_CONTENT_BODY_SHA16: frozenset[str] = frozenset({
    "0497443b3467d020", "068f7f9ac11fd271", "0a6ce1d26706e879", "0ae11970faab3d8f",
    "109e099c973b8fa0", "1f84481a48238c3d", "214d0d9122adf583", "3f26f4b4a9a41495",
    "406610802edd76fb", "4323099b3cc0a3ff", "5480e865d4deecd7", "5ac6d6d4532bd7ce",
    "68d12d9e2262e351", "6db60b3777998884", "740899bd71b3e58c", "7fc1aa6f471337ed",
    "80448afca8e42339", "a11a2f4429bef729", "a5ec40fe1045c3db", "a7116fde789ee98c",
    "ad559cfd2aebaf50", "ad55eb7cd9c1ca1c", "b4e15efccee76553", "b6f44a79524bc947",
    "ccade4923c736dce", "ced068df0d81bb1b", "d1ebdaa07ba40431", "e40e13fdf813b5b4",
})
_OP_RE = re.compile(
    rb"(?P<string>\((?:\\.|[^\\()])*\))|(?P<hex><[0-9A-Fa-f\s]+>)|"
    rb"(?P<name>/[^\s<>\[\]()]+)|(?P<number>[+-]?(?:\d+\.\d*|\.\d+|\d+))|"
    rb"(?P<bracket>[\[\]])|(?P<op>[A-Za-z][A-Za-z0-9*']*)"
)
_TEXT_OPS = frozenset({"Tj", "TJ", "'", '"'})
_KNOWN_OPS = frozenset(
    "q Q cm w J j M d ri i gs m l c v y h re S s f F f* B B* b b* n W W* "
    "BT ET Tc Tw Tz TL Tf Tr Ts Td TD Tm T* Tj TJ ' \" Do MP DP BMC BDC EMC BX EX sh".split()
)


@dataclass
class TextNode:
    text: str
    font: str
    render_mode: int
    x: float
    y: float
    off_page: bool = False
    invisible: bool = False


@dataclass
class ContentAst:
    operators: list[str] = field(default_factory=list)
    texts: list[TextNode] = field(default_factory=list)
    font_switches: list[str] = field(default_factory=list)
    clipping_count: int = 0
    gs_names: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    coordinates: list[tuple[str, tuple[float, ...]]] = field(default_factory=list)


def _decode_string(token: bytes) -> str:
    if token.startswith(b"<"):
        try:
            raw = bytes.fromhex(re.sub(rb"\s+", b"", token[1:-1]).decode())
            if len(raw) >= 2 and len(raw) % 2 == 0:
                text = raw.decode("utf-16-be", "ignore")
                if text:
                    return text
            return raw.decode("latin1", "ignore")
        except (ValueError, UnicodeError):
            return ""
    raw = re.sub(
        rb"\\([nrtbf()\\])",
        lambda m: {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}.get(m.group(1), m.group(1)),
        token[1:-1],
    )
    raw = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 255]), raw)
    return raw.decode("utf-8", "replace")


def parse_content_ast(data: bytes, *, page_box: tuple[float, float] = (612, 792)) -> ContentAst:
    ast = ContentAst()
    operands: list[bytes] = []
    in_text = False
    font, render_mode = "", 0
    x = y = 0.0
    q_depth = 0
    for match in _OP_RE.finditer(data):
        token = match.group(0)
        if match.lastgroup != "op" or token.decode("latin1") not in _KNOWN_OPS:
            operands.append(token)
            continue
        op = token.decode("latin1")
        ast.operators.append(op)
        if op == "q":
            q_depth += 1
        elif op == "Q":
            q_depth -= 1
            if q_depth < 0:
                ast.errors.append("graphics-state underflow")
                q_depth = 0
        elif op == "BT":
            if in_text:
                ast.errors.append("nested BT")
            in_text = True
        elif op == "ET":
            if not in_text:
                ast.errors.append("ET without BT")
            in_text = False
        elif op == "Tf" and len(operands) >= 2:
            font = operands[-2].lstrip(b"/").decode("latin1")
            ast.font_switches.append(font)
        elif op == "Tr" and operands:
            try:
                render_mode = int(float(operands[-1]))
            except ValueError:
                ast.errors.append("invalid Tr")
        elif op in {"Tm", "cm"} and len(operands) >= 6:
            try:
                values = tuple(float(v) for v in operands[-6:])
                ast.coordinates.append((op, values))
                if op == "Tm":
                    x, y = values[4], values[5]
            except ValueError:
                ast.errors.append(f"invalid {op}")
        elif op in {"Td", "TD"} and len(operands) >= 2:
            try:
                dx, dy = float(operands[-2]), float(operands[-1])
                x, y = x + dx, y + dy
                ast.coordinates.append((op, (dx, dy)))
            except ValueError:
                ast.errors.append(f"invalid {op}")
        elif op in {"W", "W*"}:
            ast.clipping_count += 1
        elif op == "gs" and operands:
            ast.gs_names.append(operands[-1].lstrip(b"/").decode("latin1"))
        elif op in _TEXT_OPS:
            if not in_text:
                ast.errors.append(f"{op} outside BT/ET")
            strings = [v for v in operands if v.startswith((b"(", b"<"))]
            text = "".join(_decode_string(v) for v in strings)
            if text:
                off_page = x < -5 or y < -5 or x > page_box[0] + 5 or y > page_box[1] + 5
                ast.texts.append(TextNode(text, font, render_mode, x, y, off_page, render_mode == 3))
        operands.clear()
    if in_text:
        ast.errors.append("unterminated BT")
    if q_depth:
        ast.errors.append("unbalanced q/Q")
    return ast


def _load_atlas() -> dict[str, Any]:
    try:
        data = json.loads((ATLAS_DIR / "content_ast.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _page_box(pdf: bytes) -> tuple[float, float]:
    match = re.search(rb"/MediaBox\s*\[\s*[-.\d]+\s+[-.\d]+\s+([-.\d]+)\s+([-.\d]+)", pdf)
    try:
        return (float(match.group(1)), float(match.group(2))) if match else (612, 792)
    except ValueError:
        return (612, 792)


def _content_objects(pdf: bytes) -> list[tuple[int, bytes]]:
    parsed = objects(pdf)
    referenced = {
        number for obj in parsed.values() for number in refs(obj.dictionary, b"Contents")
    }
    selected = []
    for number, obj in parsed.items():
        if obj.decoded_stream is None:
            continue
        if number in referenced or stream_role(obj) == "content":
            selected.append((number, obj.decoded_stream))
    return selected


def _fitz_text(pdf: bytes) -> str | None:
    if fitz is None:
        return None
    try:
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            return "\n".join(page.get_text("text") for page in doc)
    except Exception:
        return None


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", "", "".join(ch for ch in text if ch.isprintable())).casefold()


def check_content(pdf: bytes, *, producer: str = "") -> ForensicResult:
    result = ForensicResult()
    streams = _content_objects(pdf)
    box = _page_box(pdf)
    asts = [(number, parse_content_ast(data, page_box=box)) for number, data in streams]
    result.stats["content_objects"] = [number for number, _ in asts]
    decoded_lens = [len(data) for _, data in streams]
    result.stats["content_decoded_lens"] = decoded_lens
    max_dec = max(decoded_lens) if decoded_lens else 0
    result.stats["content_decoded_max"] = max_dec

    # Quartz/iOS genuines: phone content == 5012 B or SBP ≥6004 (n=27).
    # SEQ undersize shells ~4759–4790; SEQ phone rebuilds pad into midgap 5061–5065.
    emitter = identify_emitter(pdf, producer)
    if emitter == "quartz" and max_dec > 0:
        atlas_min = 5012
        hard_lo = atlas_min - 100  # 4912; SEQ max observed 4779
        midgap_hi = 6004  # SBP floor on genuines
        if max_dec < hard_lo:
            result.add(
                "ALFA_CONTENT_SIZE_STRONG_OUTLIER",
                (
                    f"decoded content max {max_dec} B — сильно меньше эталона "
                    f"Quartz/iOS (atlas≥{atlas_min}, n=27; HARD<{hard_lo})"
                ),
                group=RULE_GROUP,
                evidence={"content_decoded_max": max_dec, "atlas_min": atlas_min},
            )
        elif atlas_min < max_dec < midgap_hi:
            result.add(
                "ALFA_QUARTZ_CONTENT_MIDGAP",
                (
                    f"decoded content max {max_dec} B — в зазоре Quartz/iOS "
                    f"между phone={atlas_min} и SBP≥{midgap_hi} (n=27; "
                    f"SEQ phone shells 5061–5065)"
                ),
                group=RULE_GROUP,
                evidence={
                    "content_decoded_max": max_dec,
                    "phone_exact": atlas_min,
                    "sbp_floor": midgap_hi,
                },
            )

    # Oracle BI genuines (n=16): card content ∈ {3413, 4152}, SBP ∈ [5091, 5542].
    # SEQ card shells pad midgap 3545/3689; SBP rebuilds overshoot to ~5932.
    if emitter == "oracle" and max_dec > 0:
        card_lo, card_hi = 3413, 4152
        sbp_lo, sbp_hi = 5091, 5542
        hard_hi = sbp_hi + 150  # 5692; SEQ CLEAN-miss 5932
        result.stats["oracle_content_envelope"] = {
            "card_lo": card_lo,
            "card_hi": card_hi,
            "sbp_lo": sbp_lo,
            "sbp_hi": sbp_hi,
            "hard_hi": hard_hi,
            "max_dec": max_dec,
        }
        if card_lo < max_dec < card_hi or card_hi < max_dec < sbp_lo:
            result.add(
                "ALFA_ORACLE_CONTENT_MIDGAP",
                (
                    f"decoded content max {max_dec} B — в зазоре Oracle BI "
                    f"между card∈{{{card_lo},{card_hi}}} и SBP∈[{sbp_lo},{sbp_hi}] "
                    f"(n=16; SEQ card shells 3545/3689)"
                ),
                group=RULE_GROUP,
                evidence={
                    "content_decoded_max": max_dec,
                    "card_lo": card_lo,
                    "card_hi": card_hi,
                    "sbp_lo": sbp_lo,
                },
            )
        elif max_dec > hard_hi:
            result.add(
                "ALFA_CONTENT_SIZE_STRONG_OUTLIER",
                (
                    f"decoded content max {max_dec} B — сильно больше эталона "
                    f"Oracle BI (atlas≤{sbp_hi}, n=16; HARD>{hard_hi})"
                ),
                group=RULE_GROUP,
                evidence={
                    "content_decoded_max": max_dec,
                    "atlas_max": sbp_hi,
                    "hard_hi": hard_hi,
                },
            )

    # Exact decoded-content cardinality — SEQ pads into min–max gaps.
    if max_dec > 0 and emitter in {"oracle", "quartz"}:
        exact = (
            _ORACLE_CONTENT_DECODED_EXACT
            if emitter == "oracle"
            else _QUARTZ_CONTENT_DECODED_EXACT
        )
        label = "Oracle BI" if emitter == "oracle" else "Quartz/iOS"
        result.stats["content_decoded_exact_atlas"] = {
            "emitter": emitter,
            "max_dec": max_dec,
            "allowed_n": len(exact),
        }
        if max_dec not in exact:
            result.add(
                "ALFA_CONTENT_DECODED_EXACT_UNKNOWN",
                (
                    f"decoded content max {max_dec} B вне точного корпуса "
                    f"{label} (allowed={sorted(exact)}, n={len(exact)}) — "
                    f"SEQ content в зазоре envelope"
                ),
                group=RULE_GROUP,
                evidence={"content_decoded_max": max_dec, "emitter": emitter},
            )

        # Exact body hash: SEQ can land on a genuine length while rewriting
        # literals (card CLEAN 181707: len=3413 atlas hit, sha unknown).
        body = max((data for _, data in streams), key=len) if streams else b""
        body_sha = hashlib.sha256(body).hexdigest()[:16] if body else ""
        body_atlas = (
            _ORACLE_CONTENT_BODY_SHA16
            if emitter == "oracle"
            else _QUARTZ_CONTENT_BODY_SHA16
        )
        result.stats["content_body_sha16"] = body_sha
        result.stats["content_body_exact_atlas"] = {
            "emitter": emitter,
            "sha16": body_sha,
            "allowed_n": len(body_atlas),
        }
        if body_sha and body_sha not in body_atlas:
            result.add(
                "ALFA_CONTENT_BODY_EXACT_UNKNOWN",
                (
                    f"decoded /Contents sha16={body_sha} вне точного корпуса "
                    f"{label} (atlas {len(body_atlas)} тел, n="
                    f"{30 if emitter == 'oracle' else 58}) — SEQ переписал "
                    f"literals при длине из envelope"
                ),
                group=RULE_GROUP,
                evidence={"content_body_sha16": body_sha, "emitter": emitter},
            )

    errors = [(number, error) for number, ast in asts for error in ast.errors]
    if errors:
        result.add(
            "ALFA_CONTENT_STREAM_EDIT",
            "Content AST has invalid text or graphics-state structure",
            group=RULE_GROUP,
            evidence={"errors": errors},
        )

    # Oracle genuines: page content has either zero « ET» tokens or a large
    # cluster (≥30, Quartz-style). SEQ shells patch a single operand and leave
    # exactly one spaced ET (observed 1) among otherwise CRLF-terminated ETs.
    joined = b"\n".join(data for _, data in streams)
    space_et = len(re.findall(rb" ET\b", joined))
    result.stats["content_space_et"] = space_et
    if 1 <= space_et <= 10:
        result.add(
            "ALFA_CONTENT_ET_WHITESPACE_ANOMALY",
            (
                f"page content has {space_et} spaced « ET» token(s); "
                f"в корпусе Альфа только 0 или ≥30 — след SEQ patch content-stream"
            ),
            group=RULE_GROUP,
            evidence={"space_et": space_et},
        )

    all_text = [(number, node) for number, ast in asts for node in ast.texts]
    positions: dict[tuple[str, int, int], list[tuple[int, TextNode]]] = {}
    for number, node in all_text:
        key = (_norm_text(node.text), round(node.x * 2), round(node.y * 2))
        if key[0]:
            positions.setdefault(key, []).append((number, node))
    duplicates = [items for items in positions.values() if len(items) > 1]
    hidden = [(number, node) for number, node in all_text if node.invisible or node.off_page]
    if duplicates or hidden:
        result.add(
            "ALFA_OVERLAY_TEXT_LAYER",
            "Duplicate-position, invisible, or off-page text forms an overlay layer",
            group=RULE_GROUP,
            evidence={
                "duplicate_groups": [[item[0] for item in group] for group in duplicates],
                "hidden": [
                    {"object": n, "text": node.text[:80], "Tr": node.render_mode, "x": node.x, "y": node.y}
                    for n, node in hidden
                ],
            },
        )

    direct = _norm_text(" ".join(node.text for _, node in all_text if not node.invisible and not node.off_page))
    fitz_text = _fitz_text(pdf)
    if fitz_text is not None:
        rendered = _norm_text(fitz_text)
        inconsistent = bool(direct) != bool(rendered)
        if direct and rendered:
            common = sum(1 for chunk in re.findall(r"[\w]{3,}", direct) if chunk in rendered)
            inconsistent = inconsistent or (len(direct) > 30 and common == 0)
        if inconsistent:
            # Oracle/Quartz text extraction paths diverge on originals; keep diagnostic.
            result.add(
                "ALFA_TEXT_LAYER_INCONSISTENT",
                "Direct content decoding and PyMuPDF expose inconsistent text layers",
                tier="DIAGNOSTIC",
                group=RULE_GROUP,
                evidence={"direct_chars": len(direct), "pymupdf_chars": len(rendered)},
            )

    atlas = _load_atlas()
    emitter = identify_emitter(pdf, producer)
    expected = atlas.get(emitter, {}) if isinstance(atlas.get(emitter), dict) else {}
    actual_ops = [op for _, ast in asts for op in ast.operators]
    skeleton = hashlib.sha256(" ".join(actual_ops).encode()).hexdigest()
    allowed = expected.get("operator_skeleton_sha256", [])
    if isinstance(allowed, str):
        allowed = [allowed]
    if allowed and skeleton not in allowed:
        result.add(
            "ALFA_CONTENT_STREAM_EDIT",
            "Content operator AST differs from the role-matched Alfa atlas",
            group=RULE_GROUP,
            evidence={"operator_skeleton_sha256": skeleton},
        )
    coordinate_profile = expected.get("coordinates", {})
    if isinstance(coordinate_profile, dict) and coordinate_profile:
        drift = 0.0
        actual = [value for _, ast in asts for _, values in ast.coordinates for value in values]
        reference = coordinate_profile.get("values", [])
        if actual and isinstance(reference, list) and reference:
            drift = max((abs(a - float(b)) for a, b in zip(actual, reference)), default=0.0)
        if drift > float(coordinate_profile.get("tolerance", 0.5)):
            result.add(
                "ALFA_COORDINATE_DRIFT",
                f"Content coordinates drift by up to {drift:.3f}pt",
                tier="DIAGNOSTIC",
                group=RULE_GROUP,
            )
    result.stats.update(
        ast_count=len(asts),
        text_node_count=len(all_text),
        font_switch_count=sum(len(ast.font_switches) for _, ast in asts),
        clipping_count=sum(ast.clipping_count for _, ast in asts),
        gs_count=sum(len(ast.gs_names) for _, ast in asts),
    )
    return result


check_content_ast = check_content
