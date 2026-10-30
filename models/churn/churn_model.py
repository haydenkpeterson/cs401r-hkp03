"""Your Lab 3 churn model, packaged for the Lab 4 pipeline.

YOU WRITE THIS FILE. The pipeline's training job runs train_sagemaker.py
(beside this file; do not edit it), which imports this module and calls
train(). Everything the job needs from you goes through the three names below.

Contract (train_sagemaker.py checks it in the first seconds of the job):

    FEATURE_COLUMNS   list[str]   model input columns, in order
    LABEL             str         "churn_label"
    train(df, seed=42) -> (xgboost.Booster, dict)

`df` is the full labeled feature table: every column of your Lab 2 output,
including `loyalty_tier` for slice evaluation. It is already loaded. Do not
query Athena or the Feature Store from here; the training container stages
the data for you and has no business making service calls for its input.

The metrics dict must include the four numbers the CI gate in
tests/test_model.py reads. Your Lab 3 evaluate_model() already returns them:

    precision_top10, recall_top10      gated at 0.50 / 0.25
    lift_ci_low, lift_ci_high          bootstrap 95% CI on AUC lift over the
                                       recency-only baseline; lift_ci_low > 0

Include anything else you reported in Lab 3 (auc_roc, baseline_auc,
positive_rate_val, slice results). It is all written to evaluation_metrics.json
and attached to the registered model.

What runs in the container: the SageMaker XGBoost 1.7-1 image ships pandas,
numpy, scikit-learn, xgboost and boto3. It does NOT ship mlflow or sagemaker,
so do not import them at the top of this file. MLflow tracking stays in your
Lab 3 script.

Only this directory (models/churn/) is uploaded to the training job, so the
code must live here. `import churn_training_skeleton` will fail inside the
container even though it works on your laptop. Copy the functions you need.

Test it locally before pushing:

    python models/churn/train_sagemaker.py \
        --train-channel <dir containing your features CSV or Parquet> \
        --model-dir /tmp/model --output-data-dir /tmp/out
"""

# Keeps Lab 3 annotations like `-> tuple[np.ndarray, np.ndarray]` from being
# evaluated, whatever Python the training container runs.
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

# Must match the columns your Lab 3 model was trained on, in the same order.
FEATURE_COLUMNS = [
    "days_since_last_purchase",
    "customer_tenure_days",
    "purchase_frequency_30d",
    "purchase_frequency_90d",
    "purchase_frequency_180d",
    "avg_order_value",
    "total_spend_90d",
    "total_lifetime_value",
    "avg_basket_size_6m",
    "category_diversity_score",
    "online_to_store_ratio",
]

LABEL = "churn_label"
SLICE_COLUMN = "loyalty_tier"
BASELINE_FEATURE = "days_since_last_purchase"

# The Lab 3 model registered as xgb-d3-eta0.05-final: shallow, slow trees, which
# beat the depth-6 reference on every metric in the MLflow experiment.
HYPERPARAMS = {
    "max_depth": 3,
    "eta": 0.05,
    "min_child_weight": 5,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
}
NUM_ROUND = 600
EARLY_STOPPING_ROUNDS = 20
TEST_SIZE = 0.30

# The recency-only baseline is a fixed reference, not something to tune.
BASELINE_PARAMS = {"objective": "binary:logistic", "eval_metric": "auc",
                   "max_depth": 4, "eta": 0.1, "subsample": 0.9, "colsample_bytree": 0.9}
BASELINE_NUM_ROUND = 200

EVAL_THRESHOLDS = {"precision_top10": 0.50, "recall_top10": 0.25}
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 42
MIN_SLICE_POSITIVES = 30


def preprocess_features(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """(rows with a label, X, y). Missing features stay NaN for XGBoost's native
    handling; a -1 sentinel would read as a real value for recency. Lab 2's
    feature job refuses to write nulls, so none are expected."""
    df = df.dropna(subset=[LABEL])
    return df, df[FEATURE_COLUMNS].astype(float).values, df[LABEL].values.astype(int)


def train_model(X_train, y_train, X_val, y_val, seed: int) -> xgb.Booster:
    """XGBoost on the 11 features. scale_pos_weight comes from the training split
    (negatives / positives, about 3.545) rather than being hardcoded."""
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_COLUMNS)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLUMNS)
    spw = float((y_train == 0).sum() / max((y_train == 1).sum(), 1))
    params = {
        "objective": "binary:logistic",
        # eval_metric order matters: XGBoost early-stops on the LAST one.
        "eval_metric": ["logloss", "auc"],
        "scale_pos_weight": spw,
        "seed": seed,
        **HYPERPARAMS,
    }
    return xgb.train(params, dtrain, num_boost_round=NUM_ROUND,
                     evals=[(dtrain, "train"), (dval, "validation")],
                     early_stopping_rounds=EARLY_STOPPING_ROUNDS, verbose_eval=50)


def train_recency_baseline(X_train, y_train, X_val, seed: int) -> np.ndarray:
    """A model on days_since_last_purchase alone: same rows, scored on the same
    test rows, so the lift measures what the other features added."""
    i = FEATURE_COLUMNS.index(BASELINE_FEATURE)
    dtr = xgb.DMatrix(X_train[:, [i]], label=y_train, feature_names=[BASELINE_FEATURE])
    dva = xgb.DMatrix(X_val[:, [i]], feature_names=[BASELINE_FEATURE])
    spw = float((y_train == 0).sum() / max((y_train == 1).sum(), 1))
    params = {**BASELINE_PARAMS, "scale_pos_weight": spw, "seed": seed}
    return xgb.train(params, dtr, num_boost_round=BASELINE_NUM_ROUND).predict(dva)


def bootstrap_lift_ci(y_true, proba, baseline_proba, n=BOOTSTRAP_N, seed=BOOTSTRAP_SEED,
                      alpha=0.05) -> tuple[float, float]:
    """Paired percentile CI on (model AUC - baseline AUC): each replicate resamples
    the rows once and scores both models on those same rows."""
    rng = np.random.default_rng(seed)
    idx = np.arange(len(y_true))
    diffs = []
    for _ in range(n):
        s = rng.choice(idx, size=len(idx), replace=True)
        ys = y_true[s]
        if len(np.unique(ys)) < 2:
            continue
        diffs.append(roc_auc_score(ys, proba[s]) - roc_auc_score(ys, baseline_proba[s]))
    if len(diffs) < n // 2:
        raise ValueError("Too few usable bootstrap replicates to form a confidence interval.")
    return float(np.quantile(diffs, alpha / 2)), float(np.quantile(diffs, 1 - alpha / 2))


def evaluate_slices(y_val, proba, tiers, threshold: float) -> dict:
    """AUC, recall@10% and n per loyalty tier, using the same global top-10% cutoff
    as the headline metric: the campaign contacts the top 10% of all customers."""
    tiers = np.asarray(tiers)
    contacted = proba >= threshold
    slices = {}
    for tier in sorted(set(tiers)):
        m = tiers == tier
        y, p, c = y_val[m], proba[m], contacted[m]
        positives = int(y.sum())
        slices[tier] = {
            "n": int(m.sum()),
            "positives": positives,
            "auc": round(float(roc_auc_score(y, p)), 4) if 0 < positives < len(y) else None,
            "recall_top10": round(float(y[c].sum() / positives), 4) if positives else None,
            "too_small": positives < MIN_SLICE_POSITIVES,
        }
    return slices


def evaluate_model(model, X_val, y_val, baseline_proba, tiers) -> dict:
    """The Lab 3 gates. Raises on a miss, which fails the training step, so a model
    that misses a gate is never registered."""
    proba = model.predict(xgb.DMatrix(X_val, feature_names=FEATURE_COLUMNS))
    auc = roc_auc_score(y_val, proba)
    threshold = float(np.percentile(proba, 90))
    top = proba >= threshold
    precision = float(y_val[top].mean())
    recall = float(y_val[top].sum() / y_val.sum())
    baseline_auc = roc_auc_score(y_val, baseline_proba)
    ci_low, ci_high = bootstrap_lift_ci(y_val, proba, baseline_proba)

    metrics = {
        "auc_roc": round(float(auc), 4),
        "baseline_auc_roc": round(float(baseline_auc), 4),
        "auc_lift_over_baseline": round(float(auc - baseline_auc), 4),
        "auc_lift_ci_low": round(ci_low, 4),
        "auc_lift_ci_high": round(ci_high, 4),
        "precision_top10": round(precision, 4),
        "recall_top10": round(recall, 4),
        "positive_rate_val": round(float(y_val.mean()), 4),
        "n_val_samples": int(len(y_val)),
        "top10_threshold": round(threshold, 6),
        "best_iteration": int(model.best_iteration),
        "xgboost_version": xgb.__version__,
        "slice_results": evaluate_slices(y_val, proba, tiers, threshold),
    }

    failures = [f"{k}={metrics[k]:.4f} < {v}" for k, v in EVAL_THRESHOLDS.items()
                if metrics[k] < v]
    if ci_low <= 0:
        failures.append(f"lift 95% CI [{ci_low:.4f}, {ci_high:.4f}] includes zero")
    if failures:
        raise ValueError(f"Model failed evaluation gates: {'; '.join(failures)}")
    return metrics


def train(df: pd.DataFrame, seed: int = 42):
    """Train the churn model on `df` and return (booster, metrics)."""
    df, X, y = preprocess_features(df)
    # The split's random_state is the seed; the tier is split on the same indices
    # so each test row's prediction can be attributed to its tier.
    X_train, X_val, y_train, y_val, _, tier_val = train_test_split(
        X, y, df[SLICE_COLUMN].to_numpy(dtype=object),
        test_size=TEST_SIZE, random_state=seed, stratify=y)
    print(f"Train: {len(X_train):,} | Test: {len(X_val):,}")

    model = train_model(X_train, y_train, X_val, y_val, seed)
    baseline_proba = train_recency_baseline(X_train, y_train, X_val, seed)
    metrics = evaluate_model(model, X_val, y_val, baseline_proba, tier_val)
    return model, metrics
