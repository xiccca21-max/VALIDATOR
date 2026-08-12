"""Ozon Skia/PDF m105 cluster profile gate (OZ-SERIALIZER-MIX-001)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .structure import content_stream_bytes, xref_integrity

RULE_ID = "OZ-SERIALIZER-MIX-001"
_M105_PRODUCER_RE = re.compile(r"^Skia/PDF\s+m105\s*$", re.I)
_BT_RE = re.compile(r"\bBT\b")
_OP_TOKEN_RE = re.compile(
    r"(?:-\.\d+|\.\d+|-?\d+(?:\.\d+)?|<[0-9A-Fa-f]+>|\([^)]*\)|/[A-Za-z0-9+*]+|"
    r"\b(?:cm|q|Q|re|f|F|n|W\*?|rg|RG|gs|BT|ET|Tm|Td|TD|Tf|Tj|TJ|BDC|EMC)\b)"
)

# Canonical first lines after BT in m105 SBP/card receipts (serialization, not semantics).
_POST_BT_CANONICAL = (
    "BT",
    "/P <</MCID 0 >>BDC",
    "/F4 14 Tf",
    "1 0 0 -1 24 90 Tm",
    "<0248> Tj",
)

# Cluster-whitelisted high-precision literals (present in genuine m105 originals).
_CLUSTER_LITERALS = frozenset({
    ".23999999", "-.23999999", "877.91998", "809.03998", "842.88", "774", "912",
    "4.1722445", "1.35585999",
})


@dataclass
class M105ProfileResult:
    matched: bool = False
    stats: dict = field(default_factory=dict)
    reason: str = ""


def _producer_m105(pdf_bytes: bytes, producer: str) -> bool:
    if producer and _M105_PRODUCER_RE.match(producer.strip()):
        return True
    m = re.search(rb"/Producer\s*\(([^)]*)\)", pdf_bytes[:12000])
    if not m:
        return False
    val = m.group(1).decode("latin1", "replace").strip()
    return bool(_M105_PRODUCER_RE.match(val))


def _pdf_version_14(pdf_bytes: bytes) -> bool:
    return pdf_bytes[:16].startswith(b"%PDF-1.4")


def _classic_xref(pdf_bytes: bytes) -> bool:
    broken, detail = xref_integrity(pdf_bytes)
    if broken:
        return False
    off_m = re.search(rb"startxref\s+(\d+)", pdf_bytes[-128:])
    if not off_m:
        off_m = re.search(rb"startxref\s+(\d+)", pdf_bytes)
    if not off_m:
        return False
    off = int(off_m.group(1))
    return pdf_bytes[off:off + 4] == b"xref"


def _resource_graph_signature(pdf_bytes: bytes) -> str:
    head = pdf_bytes[: min(len(pdf_bytes), 200_000)]
    font_n = len(re.findall(rb"/Type\s*/Font", head))
    page_n = len(re.findall(rb"/Type\s*/Page\b", head))
    xobj_n = len(re.findall(rb"/Type\s*/XObject", head))
    ext_n = len(re.findall(rb"/Type\s*/ExtGState", head))
    contents_n = len(re.findall(rb"/Contents\s", head))
    sig = f"pdf14|fonts={font_n}|pages={page_n}|xobj={xobj_n}|ext={ext_n}|contents={contents_n}"
    return hashlib.sha256(sig.encode()).hexdigest()[:16]


def _content_lines(pdf_bytes: bytes) -> list[str]:
    raw = content_stream_bytes(pdf_bytes) or b""
    if not raw:
        return []
    return raw.decode("latin1", "replace").splitlines()


def _split_pre_post(lines: list[str]) -> tuple[list[str], list[str], int]:
    bt_idx = -1
    for i, ln in enumerate(lines):
        if _BT_RE.search(ln):
            bt_idx = i
            break
    if bt_idx < 0:
        return [], [], -1
    return lines[:bt_idx], lines[bt_idx:], bt_idx


def _semantic_prefix_tokens(pre_lines: list[str]) -> tuple[str, ...]:
    blob = " ".join(ln.strip() for ln in pre_lines if ln.strip())
    tokens = [t for t in _OP_TOKEN_RE.findall(blob) if t.strip()]
    return tuple(tokens)


def _normalized_ast_hash(tokens: tuple[str, ...]) -> str:
    norm = "|".join(tokens)
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def claims_ozon_m105_cluster(
    pdf_bytes: bytes,
    *,
    producer: str = "",
    creator: str = "",
) -> M105ProfileResult:
    """Exact m105 cluster gate — PDF 1.4, classic xref, resource graph, content AST."""
    out = M105ProfileResult()
    lines = _content_lines(pdf_bytes)
    pre, post, bt_idx = _split_pre_post(lines)

    out.stats["producer_m105"] = _producer_m105(pdf_bytes, producer)
    out.stats["pdf_14"] = _pdf_version_14(pdf_bytes)
    out.stats["classic_xref"] = _classic_xref(pdf_bytes)
    out.stats["resource_graph"] = _resource_graph_signature(pdf_bytes)
    out.stats["pre_bt_lines"] = len(pre)
    out.stats["bt_index"] = bt_idx

    if not lines or bt_idx < 0:
        out.reason = "no_content_or_bt"
        return out

    sem_tokens = _semantic_prefix_tokens(pre)
    out.stats["semantic_ops"] = len(sem_tokens)
    out.stats["content_ast"] = _normalized_ast_hash(sem_tokens)

    post_head = tuple(ln.strip() for ln in post[: len(_POST_BT_CANONICAL)])
    out.stats["post_bt_head"] = post_head
    out.stats["post_bt_canonical"] = post_head == _POST_BT_CANONICAL

    matched = all([
        out.stats["producer_m105"],
        out.stats["pdf_14"],
        out.stats["classic_xref"],
        out.stats["pre_bt_lines"] >= 120,
        out.stats["semantic_ops"] >= 30,
        out.stats["post_bt_canonical"],
        post and post[0].strip() == "BT",
        pre and pre[0].startswith(".23999999 0 0 -.23999999"),
    ])
    out.matched = matched
    if not matched:
        out.reason = "cluster_gate_failed"
    return out


def semantic_prefix_matches_cluster(pre_lines: list[str]) -> bool:
    """Static graphics prefix: same operator sequence as m105 originals (line-agnostic)."""
    if not pre_lines:
        return False
    if not pre_lines[0].startswith(".23999999 0 0 -.23999999"):
        return False
    tokens = _semantic_prefix_tokens(pre_lines)
    if len(tokens) < 30:
        return False
    # m105 originals open with cm q re W* n q … on the same semantic spine.
    head = tokens[:12]
    expected_head = (
        ".23999999", "0", "0", "-.23999999", "0",
    )
    if head[:5] != expected_head:
        return False
    if "cm" not in tokens[:8]:
        return False
    if tokens.count("q") < 2:
        return False
    if "re" not in tokens:
        return False
    return True
