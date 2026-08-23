from __future__ import annotations

import json

import pytest

from arena.adapter import check_structural_bytes
from arena.generator import default_state, offline_plans, update_strategy
from arena.ingest_external import ingest_folder
from arena.synthetic import (
    ALLOWED_MUTATIONS,
    MutationPlan,
    build_pdf,
    write_candidate,
)


def test_factory_base_is_structurally_clean():
    result = check_structural_bytes(build_pdf())
    assert result.error is None
    assert not result.all_codes


@pytest.mark.parametrize("mutation", sorted(ALLOWED_MUTATIONS))
def test_each_whitelisted_mutation_builds_and_audits_without_crashing(mutation):
    plan = MutationPlan((mutation,))
    pdf_bytes = build_pdf(plan)
    result = check_structural_bytes(pdf_bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert plan.expected_codes
    assert result.error is None


def test_unknown_mutation_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        MutationPlan(("visual_receipt_forgery",))


def test_candidate_manifest_contains_no_visual_content(tmp_path):
    plan = MutationPlan(("page_count_conflict",), "test")
    manifest = write_candidate(tmp_path, 1, 1, plan)
    saved = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert saved["visual_content"] is False
    assert saved["mutations"] == ["page_count_conflict"]


def test_misses_increase_generator_weight():
    state = default_state()
    update_strategy(
        state,
        [
            {
                "caught": False,
                "mutations": ["page_count_conflict"],
                "signature": "page_count_conflict",
            }
        ],
    )
    assert state["weights"]["page_count_conflict"] > 1.0


def test_offline_generator_is_deterministic_and_allowlisted():
    first = offline_plans(default_state(), count=5, seed=123)
    second = offline_plans(default_state(), count=5, seed=123)
    assert first == second
    assert all(set(plan.mutations) <= ALLOWED_MUTATIONS for plan in first)


def test_external_ingest_scores_existing_files_only(tmp_path):
    pdf_path = tmp_path / "existing.pdf"
    pdf_path.write_bytes(build_pdf(MutationPlan(("xref_object_mismatch",))))
    report = ingest_folder(tmp_path, limit=5)
    assert report["scanned"] == 1
    assert report["evaluations"][0]["file"] == str(pdf_path)
    assert "check_ms" in report["evaluations"][0]
    assert report["evaluations"][0]["unique"] is True
    assert report["caught"] + report["missed"] + report["errors"] + report["unknown"] == 1


def test_dashboard_trend_says_who_got_better():
    from arena.dashboard_server import _trend

    trend = _trend(
        [
            {"round": 1, "caught": 8, "missed": 0},
            {"round": 2, "caught": 7, "missed": 1},
        ]
    )
    assert trend["generator"] == "up"
    assert trend["validator"] == "down"


def test_russian_receipt_reason_uses_flag_text():
    from arena.explain_ru import describe_receipt

    row = describe_receipt(
        path=r"C:\tmp\output\alfa_sbp\check.pdf",
        bank="Альфа-Банк",
        verdict="FAKE",
        flags=[
            "[ALFA_OPERATION_IDENTITY_CONFLICT] номер операции уже встречался в другом файле"
        ],
        caught=True,
    )
    assert row["bank"] == "Альфа-Банк"
    assert row["submethod"] == "СБП"
    assert row["result"] == "Пойман"
    assert "номер операции" in row["why"]
