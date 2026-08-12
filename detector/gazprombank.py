"""

Газпромбанк — v1.0 future-safe full replacement validator.



Legacy: gpb_legacy.py. Engine: detector/gpb_v1/.

Excluded Sber corpus hashes route to Sber validator (spec §2).

"""



from __future__ import annotations



import hashlib



from .gpb_profiles import is_excluded_sber_hash, detect_emitter

from .gpb_v1.engine import VALIDATOR_VERSION, analyze as analyze_v1

from .gpb_v1.rollout import apply_rollout



__all__ = ["analyze", "VALIDATOR_VERSION", "analyze_v1"]





def _reroute_sber(pdf_bytes: bytes, file_hash: str, reason: str) -> dict:

    from .sber import analyze as analyze_sber



    result = analyze_sber(pdf_bytes, file_hash)

    details = dict(result.get("details") or {})

    details["gpb_reroute"] = {"target": "sber", "reason": reason}

    result["details"] = details

    return result





def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:

    if not file_hash:

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()



    if is_excluded_sber_hash(file_hash):

        return _reroute_sber(pdf_bytes, file_hash, "excluded_sber_corpus_sha")



    try:

        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        text = doc[0].get_text() if doc.page_count else ""

        doc.close()

    except Exception:

        text = ""



    if detect_emitter(text, pdf_bytes, file_hash) == "sber":

        return _reroute_sber(pdf_bytes, file_hash, "emitter_sber_not_gpb")



    v1 = analyze_v1(pdf_bytes, file_hash)

    if v1.get("details", {}).get("reroute_bank") == "sber":

        return _reroute_sber(pdf_bytes, file_hash, "pipeline_emitter_sber")



    return apply_rollout(v1, pdf_bytes, file_hash)

