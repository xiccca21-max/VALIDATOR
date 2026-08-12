"""VTB v1.0 analyzer entry point."""



from __future__ import annotations



import hashlib



from .explain import build_expert_report

from .stages import run_pipeline

from .verdict import compute_verdict



VALIDATOR_VERSION = "1.0.0-future-safe"





def analyze(pdf_bytes: bytes, file_hash: str = "") -> dict:

    if not file_hash:

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()



    pipeline = run_pipeline(pdf_bytes, file_hash)

    verdict, emoji, score, forgery_flags = compute_verdict(pipeline)

    expert = build_expert_report(pipeline, verdict)



    details = {

        "file_hash": file_hash,

        "validator_version": VALIDATOR_VERSION,

        "engine": "vtb_v1",

        "bank_key": "vtb",

        "family": pipeline.family,

        "family_label": pipeline.stats.get("family_label", ""),

        "generator_path": pipeline.generator_path,

        "new_coherent_profile": pipeline.new_coherent_profile,

        "completed_checks": pipeline.completed_checks,

        "stats": pipeline.stats,

        "hard_count": len(pipeline.hard_flags),

        "known_fake_count": len(pipeline.known_fake_flags),

        "diagnostic_count": len(pipeline.diagnostics),

        "analysis_complete": pipeline.analysis_complete,

        "expert_report": expert,

        "user_message": (

            "Обнаружена подделка." if verdict == "ФЕЙК"

            else "Признаков подделки не найдено."

        ),

    }



    return {

        "verdict": verdict,

        "emoji": emoji,

        "score": score,

        "flags": forgery_flags,

        "details": details,

    }

