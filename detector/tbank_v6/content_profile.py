"""T-Bank page-content structure vs MediaBox height.

Genuine OpenPDF/Jasper receipts use a fixed BT/Tm operator count per page
height. SEQ rebuilds often insert an extra text block (BT+1 / Tm+1) while
keeping glyph mosaic intact.

Also: genuine sender names never carry leading ASCII spaces before the
«Отправитель» label; SEQ phone templates pad abbreviated names («     Дамир С.»).
"""

from __future__ import annotations

import hashlib
import re
import zlib
from dataclasses import dataclass, field

from ..nbsp_padding import CODE as NBSP_CODE
from ..nbsp_padding import find_trailing_nbsp_padding, padding_detail
from ..structure import content_skeleton_hash
from .types import V6Flag

try:
    import fitz
except ImportError:
    fitz = None

# MediaBox height → (bt_count, tm_count, n_atlas)
_BT_TM_BY_HEIGHT: dict[int, tuple[int, int, int]] = {
    411: (20, 19, 11),
    431: (22, 21, 40),
    451: (24, 23, 12),
    471: (26, 25, 8),
    473: (26, 26, 1),
    519: (30, 31, 48),
    539: (32, 33, 8),
}

# Decoded /Contents length envelopes (min, max, n)
_CONTENT_LEN_BY_HEIGHT: dict[int, tuple[int, int, int]] = {
    411: (2799, 2816, 11),
    431: (3083, 3155, 40),
    451: (3389, 3430, 12),
    471: (3629, 3739, 8),
    519: (4366, 4489, 48),
    539: (4612, 4637, 8),
}

# Exact decoded /Contents lengths (envelope gaps = SEQ).
_CONTENT_LEN_EXACT_BY_HEIGHT: dict[int, tuple[frozenset[int], int]] = {
    411: (frozenset({2799, 2801, 2804, 2807, 2808, 2809, 2812, 2813, 2814, 2816}), 22),
    431: (frozenset({
        3083, 3129, 3130, 3131, 3132, 3133, 3135, 3136, 3137, 3138, 3139, 3140,
        3141, 3142, 3143, 3144, 3145, 3146, 3149, 3151, 3152, 3153, 3155,
    }), 80),
    451: (frozenset({3389, 3401, 3404, 3405, 3416, 3418, 3420, 3423, 3424, 3426, 3430}), 24),
    471: (frozenset({3629, 3649, 3660, 3667, 3670, 3680, 3738, 3739}), 16),
    519: (frozenset({
        4366, 4367, 4369, 4375, 4378, 4379, 4380, 4382, 4383, 4384, 4385, 4386,
        4387, 4388, 4390, 4394, 4396, 4399, 4400, 4403, 4405, 4406, 4407, 4408,
        4422, 4434, 4436, 4450, 4475, 4489,
    }), 110),
    539: (frozenset({4612, 4613, 4616, 4622, 4626, 4632, 4637}), 16),
}

# Exact structure content-skeleton hashes by height (SEQ clones operator
# skeleton but breaks full skeleton when rewriting literals).
_CONTENT_SKEL_EXACT_BY_HEIGHT: dict[int, tuple[frozenset[str], int]] = {
    411: (frozenset({
        "1c81ddd10aca349b", "36ce27f3b310a3ab", "40cbb6fcdf212acb", "6d45476438464489",
        "83cff763ecb35cfd", "906fd504307f71f0", "9c6e58966ab3836c", "abe4e11e8e73aa8a",
        "d05d60d182e2253f", "eb6a95cdba8284b5",
    }), 22),
    431: (frozenset({
        "00bd390d3d2a26a4", "086fb233dd2f31b6", "0b0605d514066dc0", "106e4735c35522e9",
        "23a57d988ce25fa1", "2b8c520805157140", "2d11a0d85ddbe4a3", "305ec4388795698d",
        "3ed4b95b181a2eb8", "410882301bd47d1b", "456f165174859784", "49a07fe2936b0f67",
        "51bd617c8042c02a", "5b405fe67b3b85da", "5bc1e5622f4e4a31", "649397da2f2e1baf",
        "69cd6349a0d3d377", "6d5e5e913e108ddb", "6e5b3975f5d27a7f", "76624e5aff36c28b",
        "856cb9044927aa8e", "85713e96b6f3ab09", "8f2e005d1c265d70", "9ffe0fec058be8df",
        "a20909e96cf850ca", "ad49d19be76e2eb7", "c2ab6a394ccb4507", "c599ba3dbb6f5cb8",
        "c6f644140eecabb5", "c86302aeb8060492", "d043e50c7cee6877", "d768062901f322c8",
        "dad1e195d75eb90d", "deb3962abe40a872", "e6552ab72a06050b", "ec3155098e489a9c",
    }), 80),
    451: (frozenset({
        "28ad1f022decc681", "2bf00e5b8180f374", "35aacae29228a37b", "480af89d1ba27c93",
        "584a4ce5e91ba899", "61e6e9e467d367d1", "809fc38dbd9afe35", "95074184f74949c2",
        "c33723f55bd09631", "cab2dc2692250c60", "cc0881b14c42ac9f",
    }), 24),
    471: (frozenset({
        "2cdedffa9f0b55a2", "32ad3698d34c24e0", "66cf8326841cd8c8", "6b0e101252b8ad11",
        "c25eaf4a833dd1ee", "d668211fcb07790e", "e291cd9db4db3a09", "f146f9d00c3c8947",
    }), 16),
    # SBP h=519: SEQ CLEAN 181730 hit glyf/cmap/ff2/content-len twin but
    # structure-skeleton 2301af04a0fa013b ∉ genuines (0/110).
    519: (frozenset({
        "05bb3cabbf17b416", "07fb69f3866abee9", "0c50232911516e00", "17749a7827947852",
        "191710404a566b33", "1e32e1c9caabe969", "245d925479bcdcc3", "2787aeaa42530c51",
        "319ec8c8c87891e2", "339cac40353c4c6b", "4442110fb85fca4c", "483172a2fd1f5777",
        "491ed0ab7be180ed", "4c94a96de57414d2", "4ca11399761ced95", "4eeeab6635d55447",
        "5781083049a4f393", "5ce6033fe6be00c6", "66749472db543e13", "723a532a2828f486",
        "7de4f362e3c13fe7", "7fc006b28f657bf3", "827e5227bddcad4f", "83897b52dfb2bf95",
        "92a67cfdc421ae6a", "95e7996b0cdacdfa", "9c56d562798fb173", "a6957036306e2811",
        "aa523a1e4e4202c4", "ac25f423d2cbc6ee", "b11c4fe67192211d", "b91f30091e63b0f4",
        "bddd856cefb10061", "c4f580e5fae0965f", "cf0da10887d7a3f8", "cf423baae91090bb",
        "cfb5fa7915009b0c", "d67493705a0d2311", "d8d7dbfe708b42fa", "d9cbe656f8a49feb",
        "dab9095ee92596b9", "df50923296755525", "e7731409b092f8eb", "e9d76a057e4a89f3",
        "eb220b7e1ac4d84b", "eb8f7449cd8139f9", "f2689f84ff3b6324", "f334bdf35be4e671",
        "f3c229d9e4ede91a", "f4f74fcc8a22e9ee", "f7ebd2b646506622", "fb23ff2117abb55c",
    }), 110),
    539: (frozenset({
        "1c7931f650ae851e", "2735b80bd9124548", "4c7fb9dc845f316c", "84a204ca6f1cd582",
        "a2d6d71ada1ff0bd", "acfd71331cc65b6e", "db60c7ed10763b8d",
    }), 16),
}

# Operator-only /Contents skeleton (numbers+strings stripped) by MediaBox height.
# Built from чеки/т банк OpenPDF (n=128). SEQ rebuilds insert extra Td/Tj blocks
# while keeping BT/Tm counts inside the numeric atlas.
_OP_SKEL_BY_HEIGHT: dict[int, tuple[frozenset[str], int]] = {
    411: (frozenset({"1667b862e7178c52"}), 11),
    431: (frozenset({"4515a2838a2c31a4", "81c54ede1f8e1bfb"}), 40),
    451: (frozenset({"170c7d875a43dabb", "35a7aa7d4c7f05f4"}), 12),
    471: (frozenset({
        "17073048ee30cda9", "bac7ecd51afd8fc2",
        "c1c013af48403182", "f60cf552b28f299f",
    }), 8),
    519: (frozenset({
        "bf08026b305519ee", "c7fbd19941336d2b",
        "e73d714d0c505afc", "ea666aec91ae65ac",
    }), 48),
    539: (frozenset({"adf47b42269736e8"}), 8),
}

_MIN_ATLAS = 5
_CONTENT_SLACK = 10
# Max ascending consecutive 2-byte CID run inside one (...)Tj.
# Genuines ≤4; SEQ gibberish-name rebuilds emit runs ≥8.
_CID_RUN_HARD = 6
_CYRILLIC_VOWELS = frozenset("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
# Jasper OpenPDF: after each Tm, at most two Td ops before the next ET.
# SEQ rebuilds insert extra Td/Tj positioning inside a BT block (observed ≥4).
# This is an emitter invariant, not an atlas whitelist of skeleton hashes.
_TD_RUN_AFTER_TM_HARD = 3
# «Клиенту Т-Банка» OpenPDF h=431: decoded /Contents 3129–3155 (n=76).
# SEQ CLEAN 181001 = 3128 (1 B underfloor) while coarse height atlas still fits.
_CLIENT_TBANK_CONTENT_LEN = (431, 3129, 3155, 76)
_CLIENT_CONTENT_SLACK = 0


@dataclass
class CheckResult:
    flags: list[V6Flag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _mediabox_height(pdf_bytes: bytes) -> int | None:
    m = re.search(
        rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]",
        pdf_bytes or b"",
    )
    if not m:
        return None
    try:
        return int(round(float(m.group(4))))
    except ValueError:
        return None


def _page_content(pdf_bytes: bytes) -> bytes:
    for m in re.finditer(rb"/Contents\s+(\d+)\s+\d+\s+R", pdf_bytes or b""):
        onum = int(m.group(1))
        om = re.search(
            rf"(?m)^{onum}\s+0\s+obj\b(.*?)endobj".encode(),
            pdf_bytes,
            re.S,
        )
        if not om:
            continue
        sm = re.search(rb"stream\r?\n(.*?)\n?endstream", om.group(1), re.S)
        if not sm:
            continue
        raw = sm.group(1)
        try:
            return zlib.decompress(raw)
        except Exception:
            return raw
    return b""


def _pdf_text(pdf_bytes: bytes) -> str:
    if not fitz:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return text or ""
    except Exception:
        return ""


_TJ_STR_RE = re.compile(rb"\(((?:\\.|[^\\()])*)\)\s*Tj")


def _unescape_pdf_string(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(raw):
        if raw[i] == 0x5C and i + 1 < len(raw):
            nxt = raw[i + 1]
            simple = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            if 0x30 <= nxt <= 0x37:
                j = i + 1
                val = 0
                while j < len(raw) and j < i + 4 and 0x30 <= raw[j] <= 0x37:
                    val = val * 8 + (raw[j] - 0x30)
                    j += 1
                out.append(val & 0xFF)
                i = j
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(raw[i])
        i += 1
    return bytes(out)


def _max_ascending_cid_run(content: bytes) -> int:
    """Longest strictly ascending consecutive CID run in a single Tj string.

    Identity-H style 2-byte CIDs. SEQ name-rebuilds paste monotonic CID
    ladders (gibberish) that genuine Jasper receipts never emit.
    """
    best = 0
    for m in _TJ_STR_RE.finditer(content or b""):
        body = _unescape_pdf_string(m.group(1))
        if len(body) < 8 or len(body) % 2:
            continue
        cids = [(body[i] << 8) | body[i + 1] for i in range(0, len(body), 2)]
        run = 1
        for i in range(1, len(cids)):
            if cids[i] == cids[i - 1] + 1:
                run += 1
                if run > best:
                    best = run
            else:
                run = 1
    return best


def _operator_skeleton_hash(content: bytes) -> str:
    """Stable hash of content operators with numbers/strings removed."""
    skel = re.sub(rb"\((?:\\.|[^\\()])*\)", b"()", content or b"")
    skel = re.sub(rb"<[^>]*>", b"<>", skel)
    skel = re.sub(rb"[-+]?\d*\.?\d+", b"#", skel)
    return hashlib.sha256(skel).hexdigest()[:16]


def _max_td_run_after_tm(content: bytes) -> int:
    """Longest Td-operator count between a Tm and the following ET."""
    best = 0
    for part in re.split(rb"\bTm\b", content or b"")[1:]:
        block = part.split(b"ET", 1)[0]
        best = max(best, len(re.findall(rb"\bTd\b", block)))
    return best


def _strip_pdf_strings(content: bytes) -> bytes:
    out = re.sub(rb"\((?:\\.|[^\\()])*\)", b"()", content or b"")
    return re.sub(rb"<[^>]*>", b"<>", out)


def _td_tj_interleave_count(content: bytes) -> int:
    """BT blocks where after Tm a Tj/TJ sits between two Td ops.

    OpenPDF genuines (n=270) never emit text between the paired Td
    positioning ops; SEQ SBP rebuilds insert Tj into that pair.
    """
    body = _strip_pdf_strings(content)
    bad = 0
    for block in re.findall(rb"BT\b(.*?)ET\b", body, flags=re.S):
        ops = re.findall(rb"\b(Tm|Td|Tj|TJ)\b", block)
        i = 0
        while i < len(ops):
            if ops[i] != b"Tm":
                i += 1
                continue
            seen_td = 0
            tj_after_td = False
            j = i + 1
            while j < len(ops) and ops[j] != b"Tm":
                op = ops[j]
                if op == b"Td":
                    if seen_td >= 1 and tj_after_td:
                        bad += 1
                        break
                    seen_td += 1
                elif op in (b"Tj", b"TJ") and seen_td >= 1:
                    tj_after_td = True
                j += 1
            i = j if j > i else i + 1
    return bad


def _max_cyrillic_consonant_run(value: str) -> int:
    best = 0
    run = 0
    for char in value:
        is_cyrillic = ("А" <= char <= "я") or char in "Ёё"
        if is_cyrillic and char not in _CYRILLIC_VOWELS:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _max_cyrillic_alphabet_run(value: str) -> int:
    best = 0
    run = 1
    prev: int | None = None
    for char in (value or "").lower():
        if not (("а" <= char <= "я") or char == "ё"):
            prev = None
            run = 1
            continue
        code = ord(char)
        if prev is not None and code == prev + 1:
            run += 1
            best = max(best, run)
        else:
            run = 1
        prev = code
    return best


def check_content_profile(pdf_bytes: bytes) -> CheckResult:
    out = CheckResult()
    if b"OpenPDF" not in (pdf_bytes or b""):
        return out
    height = _mediabox_height(pdf_bytes)
    dec = _page_content(pdf_bytes)
    out.stats["mediabox_height"] = height
    out.stats["content_decoded_len"] = len(dec)
    if height is None or not dec:
        return out

    bt = len(re.findall(rb"\bBT\b", dec))
    tm = len(re.findall(rb"\sTm\b", dec))
    out.stats["bt_count"] = bt
    out.stats["tm_count"] = tm
    cid_run = _max_ascending_cid_run(dec)
    out.stats["max_ascending_cid_run"] = cid_run
    if cid_run >= _CID_RUN_HARD:
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_CID_SEQUENCE_ANOMALY",
            detail=(
                f"в одном Tj подряд {cid_run} ascending CID "
                f"(HARD≥{_CID_RUN_HARD}; эталон оригиналов ≤4) — "
                f"пересборка имени/поля монотонной лестницей глифов"
            ),
            tier="A",
            group="B5_font_rebuilder",
            rule_id="TBANK_CONTENT_CID_SEQUENCE_ANOMALY",
        ))

    # Jasper/OpenPDF always emits "\nET"; SEQ rebuilders sometimes leave " ET"
    # or blank line(s) before ET (including CRLF padding: \n\r\n...\r\nET).
    space_et = len(re.findall(rb" ET\b", dec))
    dblnl_et = len(re.findall(rb"(?:\r?\n[ \t]*){2,}ET\b", dec))
    out.stats["content_space_before_et"] = space_et
    out.stats["content_blank_line_before_et"] = dblnl_et
    if space_et or dblnl_et:
        bits = []
        if space_et:
            bits.append(f"« ET»×{space_et}")
        if dblnl_et:
            bits.append(f"пустая строка перед ET×{dblnl_et}")
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_ET_WHITESPACE_ANOMALY",
            detail=(
                f"в /Contents аномальный whitespace перед ET ({', '.join(bits)}); "
                f"у Jasper/OpenPDF только «\\nET» — след ручной/чужой сериализации"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_ET_WHITESPACE_ANOMALY",
        ))

    # Jasper never indents numeric/operator lines (0/128 OpenPDF). SEQ pretty-prints
    # content like «   36 415 Td» / «      0 g».
    indented = len(re.findall(rb"(?m)^[ \t]+\-?[\d.]", dec))
    out.stats["content_indented_operand_lines"] = indented
    if indented:
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_INDENTED_OPERAND",
            detail=(
                f"в /Contents {indented} строк(и) с leading whitespace перед числом "
                f"(пример «   36 415 Td»); у Jasper/OpenPDF операнды с начала строки — "
                f"pretty-print/чужой сериализатор"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_INDENTED_OPERAND",
        ))

    # Jasper emits «Tj\n» with no trailing spaces. SEQ phone shells leave
    # «Tj   » / «Tj » padding (0/128 genuines; CLEAN-miss 187647/559/535).
    tj_trail = len(re.findall(rb"Tj[ \t]+", dec))
    out.stats["content_tj_trailing_whitespace"] = tj_trail
    if tj_trail:
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_TJ_TRAILING_WHITESPACE",
            detail=(
                f"в /Contents после Tj есть trailing ASCII-spaces/tabs "
                f"({tj_trail} вхожд.); у Jasper/OpenPDF только «Tj\\n» — "
                f"след правки content stream"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_TJ_TRAILING_WHITESPACE",
        ))

    # OpenPDF never writes unnecessary trailing zeros in fractional literals
    # (e.g. 187.10 instead of 187.1). 0/128 genuines; CLEAN-miss 187803.
    _tmp_nums = re.sub(rb"\((?:\\.|[^\\)])*\)", b"()", dec)
    trail_zero_floats = [
        m.decode("latin1", "replace")
        for m in re.findall(rb"(?<![\d.])(-?\d+\.\d+)(?![\d])", _tmp_nums)
        if (frac := m.split(b".", 1)[1]) and len(frac) >= 2 and frac.endswith(b"0")
    ]
    out.stats["content_float_trailing_zeros"] = trail_zero_floats[:8]
    if trail_zero_floats:
        sample = ", ".join(trail_zero_floats[:4])
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_FLOAT_TRAILING_ZERO",
            detail=(
                f"в /Contents float с лишним trailing zero в дробной части "
                f"({sample}"
                f"{'…' if len(trail_zero_floats) > 4 else ''}); "
                f"OpenPDF пишет краткую форму (187.1, не 187.10) — "
                f"чужой пересчёт Tm/координат"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_FLOAT_TRAILING_ZERO",
        ))

    skel = _operator_skeleton_hash(dec)
    out.stats["content_operator_skeleton"] = skel
    skel_atlas = _OP_SKEL_BY_HEIGHT.get(height)
    if skel_atlas:
        allowed, n_atlas = skel_atlas
        out.stats["content_operator_skeleton_atlas"] = {
            "n_atlas": n_atlas,
            "allowed_n": len(allowed),
        }
        # Telemetry only — demoted from HARD. Finite operator-skeleton atlas
        # by height FP's on future genuine layout variants (same class as
        # CONTENT_SKELETON_EXACT_UNKNOWN).
        if n_atlas >= _MIN_ATLAS and skel not in allowed:
            out.flags.append(V6Flag(
                code="TBANK_CONTENT_OPERATOR_SKELETON_UNKNOWN",
                detail=(
                    f"operator-skeleton /Contents {skel} вне корпуса "
                    f"height={height} (atlas {len(allowed)} вариантов, n={n_atlas}) — "
                    f"чужой content positioning / пересборка layout "
                    f"(IGNORED: atlas novelty, not 0-FP)"
                ),
                tier="IGNORE",
                group="B1_serializer_container",
                rule_id="TBANK_CONTENT_OPERATOR_SKELETON_UNKNOWN",
            ))

    td_run = _max_td_run_after_tm(dec)
    out.stats["max_td_run_after_tm"] = td_run
    if td_run >= _TD_RUN_AFTER_TM_HARD:
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_TD_RUN_ANOMALY",
            detail=(
                f"после Tm до ET подряд {td_run} операторов Td "
                f"(HARD≥{_TD_RUN_AFTER_TM_HARD}; у Jasper/OpenPDF ≤2) — "
                f"лишний positioning/Td·Tj block внутри text object"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_TD_RUN_ANOMALY",
        ))

    # Logo positioning law: each `q S 0 0 S x y cm /imgN Do Q` requires a
    # matching ±S 0 Td pair. Jasper emits this for img1 (S=28) and img3 (S=175).
    # SEQ try_006 kept img3 cm=175 but replaced ±175 Td with sentinel -500 -500.
    tds = [
        (float(a), float(b))
        for a, b in re.findall(rb"([\d.-]+)\s+([\d.-]+)\s+Td", dec)
    ]
    out.stats["td_count"] = len(tds)
    out.stats["td_ops"] = [(round(x, 3), round(y, 3)) for x, y in tds]
    if any(x == -500.0 and y == -500.0 for x, y in tds):
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_TD_SENTINEL",
            detail=(
                "в /Contents есть Td -500 -500 — sentinel чужого layout engine; "
                "у Jasper/OpenPDF IB Receipt таких координат нет (0/56 gated)"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_TD_SENTINEL",
        ))

    # Jasper: cm = [a 0 0 d tx ty]; Td pair uses ±a (x-scale), even when a≠d
    # (img3 is always a=175, d=63.23 on gated genuines).
    img_scales: list[tuple[str, float, float]] = []
    for m in re.finditer(
        rb"q\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)"
        rb"\s+cm\s+/(img\d+)\s+Do",
        dec,
    ):
        a, b, c, d = (float(m.group(i)) for i in range(1, 5))
        if abs(b) > 1e-6 or abs(c) > 1e-6:
            continue
        img_scales.append((m.group(7).decode("latin1", "replace"), a, d))
    out.stats["img_cm_scales"] = [
        {"name": n, "a": a, "d": d} for n, a, d in img_scales
    ]
    missing_pairs: list[str] = []
    for name, a, d in img_scales:
        s = round(a, 3)
        has_pos = any(abs(x - s) < 1e-3 and abs(y) < 1e-3 for x, y in tds)
        has_neg = any(abs(x + s) < 1e-3 and abs(y) < 1e-3 for x, y in tds)
        if not (has_pos and has_neg):
            missing_pairs.append(f"{name}:a={s} (d={d:g})")
    if missing_pairs:
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_IMG_TD_SCALE_MISMATCH",
            detail=(
                "для Do-картинки нет парного Td ±a 0 по cm.a "
                f"({', '.join(missing_pairs)}); у Jasper каждая imgN с "
                f"cm=[a 0 0 d …] имеет «a 0 Td» и «-a 0 Td»"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_IMG_TD_SCALE_MISMATCH",
        ))

    # Text rendering mode: Jasper ruble stroke uses exactly Tr=2 then Tr=0.
    # SEQ inserts Tr=3 (invisible) — never observed on gated genuines (0/56).
    tr_vals = [int(x) for x in re.findall(rb"\b(\d+)\s+Tr\b", dec)]
    out.stats["tr_values"] = tr_vals
    bad_tr = sorted({t for t in tr_vals if t not in (0, 2)})
    if bad_tr:
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_TR_MODE_ANOMALY",
            detail=(
                f"в /Contents Tr-режимы {bad_tr} вне Jasper-алфавита {{0,2}}; "
                f"наблюдалось Tr={tr_vals} (у gated genuines всегда [2, 0])"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_TR_MODE_ANOMALY",
        ))
    elif tr_vals and tr_vals != [2, 0]:
        # Extra 0/2 toggles still structural vs singleton [2,0] corpus law.
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_TR_MODE_ANOMALY",
            detail=(
                f"в /Contents последовательность Tr={tr_vals} ≠ [2, 0]; "
                f"у Jasper/OpenPDF IB Receipt ровно один stroke-блок рубля"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_TR_MODE_ANOMALY",
        ))

    td_tj = _td_tj_interleave_count(dec)
    out.stats["td_tj_interleave_blocks"] = td_tj
    if td_tj:
        out.flags.append(V6Flag(
            code="TBANK_CONTENT_TD_TJ_INTERLEAVE",
            detail=(
                f"в /Contents {td_tj} BT-блок(ов) с Tj/TJ между парой Td "
                f"после Tm; у Jasper/OpenPDF парный Td·Td без текста внутри — "
                f"SEQ-пересборка positioning/text object"
            ),
            tier="A",
            group="B4_text_layout",
            rule_id="TBANK_CONTENT_TD_TJ_INTERLEAVE",
        ))

    profile = _BT_TM_BY_HEIGHT.get(height)
    if profile:
        exp_bt, exp_tm, n_atlas = profile
        out.stats["bt_tm_atlas"] = {
            "bt": exp_bt, "tm": exp_tm, "n_atlas": n_atlas,
        }
        # Exact BT/Tm is stable per MediaBox height in OpenPDF genuines
        # (h=431→22/21 n=40; h=519→30/31 n=48). SEQ CLEAN 180628 = 30/32.
        if n_atlas >= _MIN_ATLAS and (bt != exp_bt or tm != exp_tm):
            out.flags.append(V6Flag(
                code="TBANK_CONTENT_BT_TM_PROFILE",
                detail=(
                    f"content BT={bt}/Tm={tm} вне корпуса height={height} "
                    f"(atlas BT={exp_bt}/Tm={exp_tm}, n={n_atlas}) — "
                    f"чужой content positioning / пересборка layout"
                ),
                tier="A",
                group="B1_serializer_container",
                rule_id="TBANK_CONTENT_BT_TM_PROFILE",
            ))

    cl_env = _CONTENT_LEN_BY_HEIGHT.get(height)
    if cl_env:
        lo, hi, n_atlas = cl_env
        out.stats["content_len_atlas"] = {"lo": lo, "hi": hi, "n_atlas": n_atlas}
        if n_atlas >= _MIN_ATLAS:
            hard_lo, hard_hi = lo - _CONTENT_SLACK, hi + _CONTENT_SLACK
            if len(dec) < hard_lo or len(dec) > hard_hi:
                side = "больше" if len(dec) > hard_hi else "меньше"
                out.flags.append(V6Flag(
                    code="TBANK_CONTENT_SIZE_STRONG_OUTLIER",
                    detail=(
                        f"decoded /Contents {len(dec)} B — {side} корпуса "
                        f"height={height} (atlas {lo}–{hi}, n={n_atlas}; "
                        f"band {hard_lo}–{hard_hi}) — novelty size, не структура"
                    ),
                    tier="B",
                    group="B1_serializer_container",
                    rule_id="TBANK_CONTENT_SIZE_STRONG_OUTLIER",
                ))

    cl_exact = _CONTENT_LEN_EXACT_BY_HEIGHT.get(height)
    if cl_exact:
        allowed_lens, n_atlas = cl_exact
        out.stats["content_len_exact_atlas"] = {
            "n_atlas": n_atlas, "allowed_n": len(allowed_lens), "len": len(dec),
        }
        if n_atlas >= _MIN_ATLAS and len(dec) not in allowed_lens:
            out.flags.append(V6Flag(
                code="TBANK_CONTENT_LEN_EXACT_UNKNOWN",
                detail=(
                    f"decoded /Contents {len(dec)} B вне точного корпуса "
                    f"height={height} (allowed={sorted(allowed_lens)}, "
                    f"n={n_atlas}) — SEQ content в зазоре envelope"
                ),
                tier="A",
                group="B1_serializer_container",
                rule_id="TBANK_CONTENT_LEN_EXACT_UNKNOWN",
            ))

    struct_skel = content_skeleton_hash(pdf_bytes)
    out.stats["content_structure_skeleton"] = struct_skel
    sk_exact = _CONTENT_SKEL_EXACT_BY_HEIGHT.get(height)
    if sk_exact and struct_skel:
        allowed_sk, n_atlas = sk_exact
        out.stats["content_structure_skeleton_atlas"] = {
            "n_atlas": n_atlas, "allowed_n": len(allowed_sk),
        }
        if n_atlas >= _MIN_ATLAS and struct_skel not in allowed_sk:
            out.flags.append(V6Flag(
                code="TBANK_CONTENT_SKELETON_EXACT_UNKNOWN",
                detail=(
                    f"content-skeleton {struct_skel} вне точного корпуса "
                    f"height={height} (atlas {len(allowed_sk)} вариантов, "
                    f"n={n_atlas}) — SEQ переписал literals при том же "
                    f"operator-skeleton"
                ),
                tier="A",
                group="B1_serializer_container",
                rule_id="TBANK_CONTENT_SKELETON_EXACT_UNKNOWN",
            ))

    text = _pdf_text(pdf_bytes)
    if text:
        exp_h, clo, chi, cn = _CLIENT_TBANK_CONTENT_LEN
        if (
            height == exp_h
            and "Клиенту Т-Банка" in text
            and cn >= _MIN_ATLAS
        ):
            hard_lo = clo - _CLIENT_CONTENT_SLACK
            hard_hi = chi + _CLIENT_CONTENT_SLACK
            out.stats["client_tbank_content_len_atlas"] = {
                "lo": clo, "hi": chi, "n_atlas": cn,
            }
            if len(dec) < hard_lo or len(dec) > hard_hi:
                side = "больше" if len(dec) > hard_hi else "меньше"
                out.flags.append(V6Flag(
                    code="TBANK_CLIENT_CONTENT_SIZE_OUTLIER",
                    detail=(
                        f"decoded /Contents {len(dec)} B — {side} корпуса "
                        f"«Клиенту Т-Банка» height={height} "
                        f"(atlas {clo}–{chi}, n={cn}) — чужой content stream / "
                        f"пересборка layout"
                    ),
                    tier="A",
                    group="B1_serializer_container",
                    rule_id="TBANK_CLIENT_CONTENT_SIZE_OUTLIER",
                ))

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        party_runs: list[tuple[str, str, int]] = []
        party_alpha: list[tuple[str, str, int]] = []
        # SBP/phone: value is the line *before* the label; card shells put the
        # party name on the line *after* «Отправитель»/«Получатель».
        _PARTY_SKIP = {
            "сумма", "комиссия", "итого", "перевод", "статус", "успешно",
            "отправитель", "получатель", "телефон получателя", "банк получателя",
            "карта получателя", "идентификатор операции", "счет списания",
            "счёт списания", "сбп", "на карту", "по номеру телефона",
        }
        for index, label in enumerate(lines):
            if label not in {"Отправитель", "Получатель"}:
                continue
            candidates: list[str] = []
            if index > 0:
                candidates.append(lines[index - 1])
            if index + 1 < len(lines):
                candidates.append(lines[index + 1])
            for value in candidates:
                if value.lower() in _PARTY_SKIP or value[:1].isdigit():
                    continue
                letters = sum(
                    ("А" <= char <= "я") or char in "Ёё"
                    for char in value
                )
                if letters < 6:
                    continue
                run = _max_cyrillic_consonant_run(value)
                alpha = _max_cyrillic_alphabet_run(value)
                party_runs.append((label, value[:50], run))
                party_alpha.append((label, value[:50], alpha))
                # Party consonant/alphabet-run HARDs removed — gibberish-name
                # heuristics (not structural); keep stats only.
        out.stats["party_name_consonant_runs"] = party_runs
        out.stats["party_name_alphabet_runs"] = party_alpha

        leading_zero_amount = re.search(
            r"(?:^|\n)Итого\n(0\d[\d\s.,]*\s*i)\b",
            text,
        )
        out.stats["amount_leading_zero"] = (
            leading_zero_amount.group(1) if leading_zero_amount else ""
        )
        if leading_zero_amount:
            value = leading_zero_amount.group(1)
            out.flags.append(V6Flag(
                code="TBANK_AMOUNT_LEADING_ZERO",
                detail=(
                    f"Итого записано с ведущим нулём: {value!r}; "
                    f"в OpenPDF-корпусе денежное поле не zero-pad'ится"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_AMOUNT_LEADING_ZERO",
            ))

        pads = re.findall(
            r"\n( {2,})([^\n]{1,80})\nОтправитель",
            text,
        )
        out.stats["sender_leading_spaces"] = [
            (len(sp), name[:40]) for sp, name in pads
        ]
        if pads:
            sp, name = pads[0]
            out.flags.append(V6Flag(
                code="TBANK_SENDER_LEADING_WHITESPACE",
                detail=(
                    f"имя отправителя с leading ASCII-spaces ({len(sp)} шт.) "
                    f"перед «Отправитель» (пример {name!r}) — "
                    f"пересборка/паддинг поля, не штатный layout"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_SENDER_LEADING_WHITESPACE",
            ))

        # Recipient value is the line after «Получатель». Genuines never pad it.
        recip = re.search(r"(?m)^Получатель\n( *\S[^\n]*)$", text)
        if recip and recip.group(1)[:1] == " ":
            val = recip.group(1)
            lead = len(val) - len(val.lstrip(" "))
            out.stats["recipient_leading_spaces"] = lead
            out.flags.append(V6Flag(
                code="TBANK_RECIPIENT_LEADING_WHITESPACE",
                detail=(
                    f"имя получателя с leading ASCII-spaces ({lead} шт.) "
                    f"после «Получатель» (пример {val[:40]!r}) — "
                    f"паддинг пересборки, не штатный Jasper layout"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_RECIPIENT_LEADING_WHITESPACE",
            ))

        # Any extracted text line with trailing ASCII spaces — never on OpenPDF genuines.
        trail_lines = [
            line for line in text.splitlines()
            if line and line != line.rstrip(" ")
        ]
        out.stats["text_trailing_space_lines"] = [
            repr(line[:50]) for line in trail_lines[:4]
        ]
        if trail_lines:
            sample = trail_lines[0]
            out.flags.append(V6Flag(
                code="TBANK_TEXT_TRAILING_WHITESPACE",
                detail=(
                    f"в тексте строка с trailing ASCII-spaces "
                    f"({len(sample) - len(sample.rstrip(' '))} шт.): "
                    f"{sample.rstrip()[:50]!r}… — паддинг/чужая сериализация, "
                    f"у Jasper/OpenPDF строкa trim'ится"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_TEXT_TRAILING_WHITESPACE",
            ))

        nbsp_hits = find_trailing_nbsp_padding(text)
        out.stats["text_trailing_nbsp_runs"] = [
            (hit.field, hit.count) for hit in nbsp_hits[:6]
        ]
        if nbsp_hits:
            out.flags.append(V6Flag(
                code=NBSP_CODE,
                detail=padding_detail(nbsp_hits),
                tier="A",
                group="B4_text_layout",
                rule_id=NBSP_CODE,
            ))

        amt_pads = re.findall(r"\n( {2,})(\d[\d\s.,]*\s*i)\b", text)
        # also Итого\n<spaces><amount>
        itogo = re.search(r"Итого\n( {2,})([^\n]+)", text)
        out.stats["amount_leading_spaces"] = [
            (len(sp), val[:20]) for sp, val in amt_pads[:4]
        ]
        if itogo or amt_pads:
            sp, val = (itogo.group(1), itogo.group(2)) if itogo else amt_pads[0]
            out.flags.append(V6Flag(
                code="TBANK_AMOUNT_LEADING_WHITESPACE",
                detail=(
                    f"сумма с leading ASCII-spaces ({len(sp)} шт.) "
                    f"(пример {val.strip()!r}) — паддинг пересборки, "
                    f"не штатный Jasper amount layout"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_AMOUNT_LEADING_WHITESPACE",
            ))

        # Channel ↔ MediaBox: only when height is a known shell of *another*
        # channel. Unknown future heights are skipped (atlas novelty).
        low = text.casefold()
        if "сбп" in low or "системы быстрых" in low:
            channel = "sbp"
        elif "телефон" in low:
            channel = "phone"
        elif "карт" in low:
            channel = "card"
        else:
            channel = ""
        channel_heights = {
            "card": frozenset({411, 431, 471}),
            "phone": frozenset({451, 471, 473}),
            "sbp": frozenset({519, 539}),
        }
        allowed = channel_heights.get(channel, frozenset())
        known_shells = frozenset().union(*channel_heights.values())
        out.stats["receipt_channel"] = channel
        if (
            channel
            and allowed
            and height in known_shells
            and height not in allowed
        ):
            out.flags.append(V6Flag(
                code="TBANK_CHANNEL_MEDIABOX_MISMATCH",
                detail=(
                    f"канал «{channel}» на чужом известном shell height={height} "
                    f"(для канала {sorted(allowed)}; known shells {sorted(known_shells)}) — "
                    f"текст канала на page shell другого канала"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_CHANNEL_MEDIABOX_MISMATCH",
            ))

        # Recipient phone field (phone-channel or SBP) always uses mobile DEF=9xx
        # in the OpenPDF corpus. SEQ templates emit landline-looking codes.
        phone_m = re.search(
            r"\+7 \((\d{3})\) (\d{3})-(\d{2})-(\d{2})",
            text,
        )
        if phone_m:
            out.stats["phone_def_code"] = phone_m.group(1)
            subscriber = "".join(phone_m.group(i) for i in (2, 3, 4))
            out.stats["phone_subscriber"] = subscriber
            if not phone_m.group(1).startswith("9"):
                out.flags.append(V6Flag(
                    code="TBANK_PHONE_DEF_NOT_MOBILE",
                    detail=(
                        f"телефон получателя DEF={phone_m.group(1)} "
                        f"(не 9xx); в OpenPDF-корпусе получатель всегда мобильный 9xx — "
                        f"синтетический номер SEQ-шаблона"
                    ),
                    tier="A",
                    group="B4_text_layout",
                    rule_id="TBANK_PHONE_DEF_NOT_MOBILE",
                ))
            # 7-digit subscriber all identical (111-11-11): 0/154 genuines.
            elif len(subscriber) == 7 and len(set(subscriber)) == 1:
                out.flags.append(V6Flag(
                    code="TBANK_PHONE_SUBSCRIBER_UNIFORM",
                    detail=(
                        f"телефон +7 ({phone_m.group(1)}) "
                        f"{phone_m.group(2)}-{phone_m.group(3)}-{phone_m.group(4)}: "
                        f"абонентская часть из одной цифры — SEQ phone-template"
                    ),
                    tier="A",
                    group="B4_text_layout",
                    rule_id="TBANK_PHONE_SUBSCRIBER_UNIFORM",
                ))

        # Card channel: SEQ last4 ladders 2345/4567. Diagnostic only —
        # genuines also have 3456 (Новая папка). Not HARD.
        if channel == "card":
            cards = re.findall(r"(\d{6})\*+(\d{4})", text)
            out.stats["card_last4"] = [last4 for _, last4 in cards]
            for bin6, last4 in cards:
                asc = sum(
                    1
                    for i in range(3)
                    if last4[i].isdigit()
                    and last4[i + 1].isdigit()
                    and int(last4[i + 1]) - int(last4[i]) == 1
                )
                if asc >= 3:
                    out.flags.append(V6Flag(
                        code="TBANK_CARD_LAST4_SEQUENTIAL",
                        detail=(
                            f"карта …{last4}: ascending last4 score={asc} — "
                            f"лестничный SEQ card-template (в OpenPDF «На карту» нет)"
                        ),
                        tier="A",
                        group="B4_text_layout",
                        rule_id="TBANK_CARD_LAST4_SEQUENTIAL",
                    ))
                    break
                # Null-pad BIN/last4 (220000******0000 / 200000******0000):
                # 0/166 card masks on OpenPDF genuines.
                if last4 == "0000" or bin6 in ("200000", "220000"):
                    out.flags.append(V6Flag(
                        code="TBANK_CARD_MASK_NULL_TEMPLATE",
                        detail=(
                            f"карта {bin6}******{last4}: нулевой BIN/last4 "
                            f"шаблон — в OpenPDF-корпусе таких масок нет"
                        ),
                        tier="A",
                        group="B4_text_layout",
                        rule_id="TBANK_CARD_MASK_NULL_TEMPLATE",
                    ))
                    break

        # Printed datetime seconds: OpenPDF genuines never show :00 (n=270).
        # SEQ card/phone shells round the clock to the minute.
        dt_m = re.search(
            r"(\d{2}\.\d{2}\.\d{4})  +(\d{2}:\d{2}:)(\d{2})",
            text,
        )
        if dt_m:
            out.stats["printed_datetime"] = dt_m.group(0)
            out.stats["printed_second"] = dt_m.group(3)
            if dt_m.group(3) == "00":
                out.flags.append(V6Flag(
                    code="TBANK_DATETIME_ZERO_SECONDS",
                    detail=(
                        f"время операции {dt_m.group(2)}{dt_m.group(3)} с "
                        f"нулевыми секундами; в OpenPDF-корпусе секунды всегда "
                        f"1–59 — минутное округление SEQ-шаблона"
                    ),
                    tier="A",
                    group="B4_text_layout",
                    rule_id="TBANK_DATETIME_ZERO_SECONDS",
                ))

        # Exact support contact on all OpenPDF genuines (n=270):
        # «Служба поддержки fb@tbank.ru». SEQ strips/corrupts ToUnicode so the
        # line becomes mojibake (Слуēба поддерēки …) and identify used to miss
        # the bank — treat missing/garbled issuer contact as HARD FAKE.
        _SUPPORT_EXACT = "Служба поддержки fb@tbank.ru"
        support = re.search(r"(?m)^Служба поддержки[^\n]*$", text)
        if support:
            line = support.group(0)
            out.stats["support_contact_line"] = line
            if line != _SUPPORT_EXACT:
                out.flags.append(V6Flag(
                    code="TBANK_SUPPORT_CONTACT_SPACING",
                    detail=(
                        f"строка поддержки {line!r} ≠ эталон "
                        f"«{_SUPPORT_EXACT}» — лишние пробелы/правка шаблона"
                    ),
                    tier="A",
                    group="B4_text_layout",
                    rule_id="TBANK_SUPPORT_CONTACT_SPACING",
                ))
        elif "fb@tbank.ru" not in text.lower():
            garbled = next(
                (
                    ln for ln in text.splitlines()
                    if "поддер" in ln.casefold() or "служ" in ln.casefold()
                ),
                "",
            )
            out.stats["support_contact_line"] = garbled or None
            out.stats["support_contact_missing"] = True
            detail = (
                "нет эталонной строки «Служба поддержки fb@tbank.ru»"
            )
            if garbled:
                detail += (
                    f"; вместо неё кракозябры {garbled!r} — ToUnicode/"
                    f"текст поддержки повреждён (SEQ)"
                )
            else:
                detail += " — контакт поддержки вырезан или сломан (SEQ)"
            out.flags.append(V6Flag(
                code="TBANK_SUPPORT_CONTACT_CORRUPTED",
                detail=detail,
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_SUPPORT_CONTACT_CORRUPTED",
            ))

        # Static JRXML labels. OpenPDF ToUnicode for template strings is exact
        # (133/133 genuines). SEQ that remaps CID→Latin (Перевiд) keeps the
        # visual but breaks the text layer. Missing «Перевод» on a receipt
        # that still has Итого/Статус/Квитанция is that generator break.
        receiptish = sum(
            1 for tok in ("Итого", "Статус", "Квитанция") if tok in text
        )
        if receiptish >= 2:
            first_line = next(
                (ln.strip() for ln in text.splitlines() if ln.strip()),
                "",
            )
            out.stats["date_line"] = first_line[:48]
            if not re.match(r"^\d{2}\.\d{2}\.\d{4}\b", first_line):
                out.flags.append(V6Flag(
                    code="TBANK_DATE_LINE_CORRUPTED",
                    detail=(
                        f"первая строка «{first_line}» не дата DD.MM.YYYY — "
                        f"Jasper IB/Receipt всегда печатает дату операции первой "
                        f"строкой; кракозябры = сломанный ToUnicode/CID"
                    ),
                    tier="A",
                    group="B4_text_layout",
                    rule_id="TBANK_DATE_LINE_CORRUPTED",
                ))
            if "Перевод" not in text:
                garbled = next(
                    (
                        ln.strip() for ln in text.splitlines()
                        if "перев" in ln.casefold() or "ерев" in ln.casefold()
                    ),
                    "",
                )
                out.flags.append(V6Flag(
                    code="TBANK_STATIC_LABEL_CORRUPTED",
                    detail=(
                        f"нет эталонного лейбла «Перевод»"
                        + (
                            f"; вместо него {garbled!r}"
                            if garbled else ""
                        )
                        + " — JRXML/ToUnicode сломан (SEQ glyph-slot)"
                    ),
                    tier="A",
                    group="B4_text_layout",
                    rule_id="TBANK_STATIC_LABEL_CORRUPTED",
                ))

        # Static label «Телефон получателя» — genuines never mojibake the T
        # (SEQ → «þелефон получателя» when transplanting Latin/Þ into slot).
        if (
            "Телефон получателя" not in text
            and re.search(r"(?i).елефон получателя", text)
        ):
            bad = next(
                (
                    ln for ln in text.splitlines()
                    if "елефон получателя" in ln.casefold()
                ),
                "",
            )
            out.flags.append(V6Flag(
                code="TBANK_STATIC_LABEL_CORRUPTED",
                detail=(
                    f"лейбл телефона получателя повреждён: {bad!r} "
                    f"≠ «Телефон получателя» — сломанный ToUnicode/glyph slot"
                ),
                tier="A",
                group="B4_text_layout",
                rule_id="TBANK_STATIC_LABEL_CORRUPTED",
            ))
    return out
