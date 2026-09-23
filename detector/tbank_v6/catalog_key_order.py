"""Catalog dictionary key order for T-Bank Jasper receipts.

Every genuine receipt in the T-Bank corpus writes the page catalog as
``/Names`` first and ``/Type/Catalog`` after it. The dictionary means the
same thing either way, but the bank program does not emit the reverse order.
A rebuild that puts ``/Type`` before ``/Names`` is a different serializer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..alfa_v2.pdfutil import objects
from .types import V6Flag

_TYPE_CATALOG = re.compile(rb"/Type\s*/Catalog\b")


@dataclass
class CheckResult:
    flags: list[V6Flag] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def check_catalog_key_order(pdf_bytes: bytes) -> CheckResult:
    out = CheckResult()
    catalogs = 0
    for obj in objects(pdf_bytes or b"").values():
        body = obj.dictionary or b""
        type_at = _TYPE_CATALOG.search(body)
        if type_at is None:
            continue
        catalogs += 1
        names_at = body.find(b"/Names")
        if names_at < 0:
            out.stats["catalog_names_linked"] = False
            continue
        names_before_type = names_at < type_at.start()
        out.stats["catalog_names_before_type"] = names_before_type
        if names_before_type:
            continue
        out.flags.append(V6Flag(
            code="TBANK_CATALOG_KEY_ORDER",
            detail=(
                "в словаре Catalog ключ /Type записан раньше /Names. "
                "Оригиналы Т-Банка всегда пишут /Names перед /Type/Catalog"
            ),
            group="container",
            rule_id="A-CONT-CATALOG-KEY-ORDER",
        ))
    out.stats["catalogs"] = catalogs
    return out
