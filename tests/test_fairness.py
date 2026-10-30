"""
NorthStar Retail - Fairness Check (manual slice evaluation)
CS 401R Lab 4, Task 1

Reads the per-tier results train() puts in evaluation_metrics.json and compares
recall across loyalty tiers. A recall gap above 10 percentage points is FLAGGED,
not blocked: the warning lands in the build log's warnings summary so the human
approver sees it before promoting the model.

Run locally (after the local training run in the lab handout):
    pytest tests/test_fairness.py -v -rw --eval-metrics-path /tmp/out/evaluation_metrics.json
"""

import json
import os
import warnings
from pathlib import Path

import pytest

TIERS = {"Bronze", "Silver", "Gold", "Platinum"}
MAX_RECALL_GAP = 0.10


@pytest.fixture(scope="module")
def slices():
    path = os.environ.get("EVAL_METRICS_PATH", "/tmp/eval_metrics.json")
    if not Path(path).exists():
        pytest.skip(f"Evaluation metrics not found at {path}.")
    with open(path) as f:
        metrics = json.load(f)
    assert "slice_results" in metrics, "train() must put slice_results in its metrics dict"
    return metrics["slice_results"]


def test_every_tier_is_evaluated(slices):
    assert set(slices) == TIERS, f"Expected results for {sorted(TIERS)}, got {sorted(slices)}"


def test_every_tier_reports_n_auc_and_recall(slices):
    for tier, result in slices.items():
        assert result["n"] > 0, f"{tier} has no test customers"
        assert result["auc"] is not None, f"{tier} has no AUC"
        assert result["recall_top10"] is not None, f"{tier} has no recall"


def test_slice_sizes_add_up_to_the_test_set(slices):
    """Each test customer belongs to exactly one tier."""
    path = os.environ.get("EVAL_METRICS_PATH", "/tmp/eval_metrics.json")
    with open(path) as f:
        n_test = json.load(f)["n_val_samples"]
    assert sum(r["n"] for r in slices.values()) == n_test


def test_recall_gap_is_flagged(slices):
    """Flag, do not block. Tiers with too few churners are excluded from the gap,
    because their recall rests on a handful of customers."""
    sized = {t: r["recall_top10"] for t, r in slices.items() if not r["too_small"]}
    assert len(sized) >= 2, "Need at least two tiers large enough to compare"
    high, low = max(sized, key=sized.get), min(sized, key=sized.get)
    gap = sized[high] - sized[low]
    if gap > MAX_RECALL_GAP:
        warnings.warn(
            f"FAIRNESS FLAG: recall@10% gap {gap:.3f} exceeds {MAX_RECALL_GAP} "
            f"({high} {sized[high]:.3f} vs {low} {sized[low]:.3f})"
        )
