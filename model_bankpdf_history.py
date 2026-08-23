from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "analysis" / "bankpdf_history_dataset.json"
REPORT = ROOT / "analysis" / "bankpdf_history_model_report.json"

STATIC_NUMERIC = [
    "pdf_size",
    "object_count",
    "content_decoded_size",
    "content_raw_size",
    "font_decoded_size",
    "font_raw_size",
    "tounicode_decoded_size",
    "used_cid_count",
    "used_cid_min",
    "used_cid_max",
    "num_glyphs",
    "check_sum_adjustment",
    "nul_count",
    "mapped_cid_count",
    "unused_mapped_count",
    "sbp_lag_seconds",
    "operation_hour",
    "operation_minute",
    "operation_second",
    "amount_value",
    "fio_length",
]

STATIC_CATEGORICAL = [
    "producer",
    "sfnt_order",
    "nul_cids",
    "bank",
    "fio_initial",
    "sbp_flag_codes",
]

STATE_NUMERIC = [
    "gap_from_previous_seconds",
    "prior_submissions_60s",
    "prior_passes_60s",
    "prior_submissions_300s",
    "prior_passes_300s",
    "prior_same_pdf_sha_count",
    "prior_same_pdf_sha_pass",
    "prior_same_pdf_sha_fail",
    "prior_same_font_sha_count",
    "prior_same_font_sha_pass",
    "prior_same_font_sha_fail",
    "prior_same_content_sha_count",
    "prior_same_content_sha_pass",
    "prior_same_content_sha_fail",
    "prior_same_operation_id_count",
    "prior_same_sbp_id_count",
    "prior_same_phone_digits_count",
    "prior_same_account_count",
    "prior_same_operation_datetime_count",
]

STATE_CATEGORICAL = ["previous_verdict"]


def clean_numeric(value: Any) -> float:
    if value is None or value == "":
        return math.nan
    try:
        result = float(value)
        return result if math.isfinite(result) else math.nan
    except (TypeError, ValueError):
        return math.nan


def matrix(rows: list[dict[str, Any]], numeric: list[str], categorical: list[str]) -> np.ndarray:
    values: list[list[Any]] = []
    for row in rows:
        values.append(
            [clean_numeric(row.get(name)) for name in numeric]
            + [str(row.get(name) or "") for name in categorical]
        )
    return np.asarray(values, dtype=object)


def pipeline(numeric_count: int, categorical_count: int) -> Pipeline:
    numeric_indices = list(range(numeric_count))
    categorical_indices = list(range(numeric_count, numeric_count + categorical_count))
    transformer = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric_indices,
            ),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", min_frequency=2),
                categorical_indices,
            ),
        ]
    )
    return Pipeline(
        [
            ("transform", transformer),
            (
                "model",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=3000,
                    C=0.3,
                    solver="liblinear",
                    random_state=17,
                ),
            ),
        ]
    )


def metrics(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    predicted = (probabilities >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, predicted, average="binary", zero_division=0
    )
    return {
        "accuracy": accuracy_score(y_true, predicted),
        "balanced_accuracy": balanced_accuracy_score(y_true, predicted),
        "roc_auc": roc_auc_score(y_true, probabilities) if len(set(y_true)) == 2 else None,
        "average_precision": average_precision_score(y_true, probabilities),
        "pass_precision": precision,
        "pass_recall": recall,
        "pass_f1": f1,
        "confusion_matrix": confusion_matrix(y_true, predicted, labels=[0, 1]).tolist(),
    }


def grouped_cv(
    rows: list[dict[str, Any]],
    numeric: list[str],
    categorical: list[str],
) -> dict[str, Any]:
    X = matrix(rows, numeric, categorical)
    y = np.asarray([row["verdict"] == "PASS" for row in rows], dtype=int)
    groups = np.asarray([row.get("pdf_sha") or f"missing:{index}" for index, row in enumerate(rows)])
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=17)
    folds = []
    all_true: list[int] = []
    all_probability: list[float] = []
    for train_index, test_index in splitter.split(X, y, groups):
        model = pipeline(len(numeric), len(categorical))
        model.fit(X[train_index], y[train_index])
        probability = model.predict_proba(X[test_index])[:, 1]
        fold_metrics = metrics(y[test_index], probability)
        fold_metrics["test_size"] = len(test_index)
        fold_metrics["test_passes"] = int(y[test_index].sum())
        folds.append(fold_metrics)
        all_true.extend(y[test_index].tolist())
        all_probability.extend(probability.tolist())
    aggregate = metrics(np.asarray(all_true), np.asarray(all_probability))
    aggregate["folds"] = folds
    return aggregate


def temporal_test(
    rows: list[dict[str, Any]],
    numeric: list[str],
    categorical: list[str],
) -> dict[str, Any]:
    split = int(len(rows) * 0.7)
    train_rows, test_rows = rows[:split], rows[split:]
    X_train = matrix(train_rows, numeric, categorical)
    X_test = matrix(test_rows, numeric, categorical)
    y_train = np.asarray([row["verdict"] == "PASS" for row in train_rows], dtype=int)
    y_test = np.asarray([row["verdict"] == "PASS" for row in test_rows], dtype=int)
    model = pipeline(len(numeric), len(categorical))
    model.fit(X_train, y_train)
    probability = model.predict_proba(X_test)[:, 1]
    result = metrics(y_test, probability)
    result.update(
        {
            "train_size": len(train_rows),
            "train_passes": int(y_train.sum()),
            "test_size": len(test_rows),
            "test_passes": int(y_test.sum()),
            "split_at": test_rows[0].get("sent_at") if test_rows else "",
        }
    )
    return result


def pass_rate_groups(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[str(row.get(key) or "")][row["verdict"]] += 1
    result = []
    for value, counts in grouped.items():
        total = sum(counts.values())
        result.append(
            {
                "value": value,
                "total": total,
                "passes": counts["PASS"],
                "fails": counts["FAIL"],
                "pass_rate": counts["PASS"] / total,
            }
        )
    return sorted(result, key=lambda item: (-item["total"], item["value"]))


def numeric_bins(rows: list[dict[str, Any]], key: str, edges: list[float]) -> list[dict[str, Any]]:
    buckets = [Counter() for _ in range(len(edges) + 1)]
    for row in rows:
        value = clean_numeric(row.get(key))
        if math.isnan(value):
            continue
        index = next((i for i, edge in enumerate(edges) if value <= edge), len(edges))
        buckets[index][row["verdict"]] += 1
    result = []
    low = float("-inf")
    for index, counts in enumerate(buckets):
        high = edges[index] if index < len(edges) else float("inf")
        total = sum(counts.values())
        if total:
            result.append(
                {
                    "range": f"({low},{high}]",
                    "total": total,
                    "passes": counts["PASS"],
                    "pass_rate": counts["PASS"] / total,
                }
            )
        low = high
    return result


def duplicate_transitions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("pdf_sha"):
            grouped[row["pdf_sha"]].append(row)
    result = []
    for digest, members in grouped.items():
        if len(members) < 2:
            continue
        sequence = "".join("P" if member["verdict"] == "PASS" else "F" for member in members)
        result.append(
            {
                "pdf_sha": digest,
                "submissions": len(members),
                "sequence": sequence,
                "filenames": [member["filename"] for member in members],
                "times": [member["sent_at"] for member in members],
            }
        )
    return sorted(result, key=lambda item: (-item["submissions"], item["pdf_sha"]))


def main() -> None:
    all_rows = json.loads(DATASET.read_text(encoding="utf-8"))
    usable_rows = [
        row
        for row in all_rows
        if row.get("pdf_exists") and row.get("pdf_sha") and row.get("bytes_reliable")
    ]
    rows = [row for row in usable_rows if not row.get("reuse_notice")]
    y = np.asarray([row["verdict"] == "PASS" for row in rows], dtype=int)
    static_cv = grouped_cv(rows, STATIC_NUMERIC, STATIC_CATEGORICAL)
    full_cv = grouped_cv(
        rows,
        STATIC_NUMERIC + STATE_NUMERIC,
        STATIC_CATEGORICAL + STATE_CATEGORICAL,
    )
    report = {
        "all_usable_submissions": len(usable_rows),
        "excluded_cached_reuse_passes": len(usable_rows) - len(rows),
        "usable_submissions": len(rows),
        "passes": int(y.sum()),
        "fails": int(len(y) - y.sum()),
        "all_fail_baseline": {
            "accuracy": float((y == 0).mean()),
            "balanced_accuracy": 0.5,
            "average_precision": float(y.mean()),
        },
        "static_features_grouped_cv": static_cv,
        "static_plus_history_grouped_cv": full_cv,
        "static_features_temporal_test": temporal_test(rows, STATIC_NUMERIC, STATIC_CATEGORICAL),
        "static_plus_history_temporal_test": temporal_test(
            rows,
            STATIC_NUMERIC + STATE_NUMERIC,
            STATIC_CATEGORICAL + STATE_CATEGORICAL,
        ),
        "pass_rate_by_previous_verdict": pass_rate_groups(rows, "previous_verdict"),
        "pass_rate_by_prior_same_pdf_count": pass_rate_groups(rows, "prior_same_pdf_sha_count"),
        "pass_rate_by_prior_same_font_count": pass_rate_groups(rows, "prior_same_font_sha_count"),
        "pass_rate_by_bank": pass_rate_groups(rows, "bank"),
        "gap_bins": numeric_bins(rows, "gap_from_previous_seconds", [10, 20, 30, 60, 300, 1800]),
        "sbp_lag_bins": numeric_bins(rows, "sbp_lag_seconds", [0, 15, 30, 60, 120, 300, 3600]),
        "duplicate_pdf_sequences": duplicate_transitions(rows),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
