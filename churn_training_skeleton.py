"""
NorthStar Retail — Churn Prediction Training Script (Skeleton)
CS 401R Lab 3 Starter Kit

This script is the SageMaker XGBoost training entry point for the NorthStar
churn prediction model. It reads features from the SageMaker Feature Store,
trains an XGBoost classifier, tracks the run in a SageMaker MLflow App, and
registers the model in the Model Registry.

Experiment tracking needs two packages that are NOT in the training container:

    pip install mlflow sagemaker-mlflow

`sagemaker-mlflow` is the SigV4 auth plugin for arn:aws:sagemaker:... tracking
URIs. Install `mlflow` alone and you get a connection error that never mentions
credentials. See track_run() for the cost warning about the OTHER MLflow
product -- read it before you create anything.

Usage (local testing):
    python churn_training_skeleton.py \
        --feature-group-name northstar-dev-customer-features \
        --artifacts-bucket northstar-dev-data-<account> \
        --max-depth 6 --eta 0.1 --num-round 200 \
        --mlflow-arn arn:aws:sagemaker:us-east-1:<account>:mlflow-app/app-XXXX \
        --run-name xgb-depth6-eta0.1

Usage (SageMaker training job — parameters passed via hyperparameter dict):
    Configured via the SageMaker Python SDK Estimator.
"""

import argparse
import json
import os
import pickle
from datetime import datetime, timezone

import boto3
import numpy as np
import pandas as pd

# The Feature Store query goes through boto3 (Athena + SageMaker APIs) rather
# than the SageMaker Python SDK. The SDK's FeatureGroup.athena_query() is a thin
# wrapper over the same calls, and the SDK's feature_store module needs
# sagemaker<3, which does not install cleanly on every Python version.
import tarfile
import time

import xgboost as xgb
from sklearn.metrics import confusion_matrix, roc_auc_score
from sklearn.model_selection import train_test_split

# ── Argument Parsing ───────────────────────────────────────────────────────────
# SageMaker passes hyperparameters as CLI arguments.

def parse_args():
    parser = argparse.ArgumentParser(description="NorthStar churn prediction training")

    # Data configuration
    # Names come from Lab 2's Terraform: `terraform output -raw feature_group_name`
    # and `terraform output -raw s3_bucket_name`. Do not invent new ones.
    parser.add_argument("--feature-group-name", type=str,
                        default="northstar-dev-customer-features",
                        help="SageMaker Feature Store feature group name (Lab 2 output)")
    # These dates bound the INGEST batch, not the feature window. Lab 2 stamps
    # event_time with the wall-clock time its Glue job ran (time.time()), not
    # with the feature cutoff T = 2026-04-01 -- T was already enforced when the
    # features were computed. A window that ends before your Lab 2 run (the old
    # default here was 2026-06-01) matches zero rows. These defaults match the
    # reference implementation and cover any Lab 2 run during the semester.
    parser.add_argument("--training-start-date", type=str, default="2026-01-01",
                        help="Earliest Lab 2 ingest date to include (YYYY-MM-DD)")
    parser.add_argument("--training-end-date", type=str, default="2027-01-01",
                        help="Latest Lab 2 ingest date to include (YYYY-MM-DD)")
    parser.add_argument("--artifacts-bucket", type=str, required=True,
                        help="Your Lab 1 data bucket, northstar-dev-data-<account>. "
                             "Athena results and model artifacts go under its artifacts/ "
                             "prefix, the only prefix your MLEngineer role can write")
    parser.add_argument("--local-data-path", type=str, default=None,
                        help="Path to local feature CSV for development testing (bypasses Feature Store)")

    # XGBoost hyperparameters
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--eta", type=float, default=0.1)
    parser.add_argument("--num-round", type=int, default=200)
    parser.add_argument("--min-child-weight", type=int, default=5)
    parser.add_argument("--subsample", type=float, default=0.8)
    parser.add_argument("--colsample-bytree", type=float, default=0.8)
    parser.add_argument("--scale-pos-weight", type=float, default=None,
                        help=(
                            "XGBoost positive-class weight. Leave unset and it is computed "
                            "from YOUR training split as negatives/positives, which is what "
                            "you want. The reference 10,000-customer dataset is 22.0%% "
                            "churners, giving (1 - 0.220) / 0.220 = 3.545. Passing a value "
                            "tuned for a different class balance will quietly skew your "
                            "precision/recall trade-off, so only override this deliberately."
                        ))
    # Experiment tracking (Task 1, 5 points)
    parser.add_argument("--mlflow-arn", type=str,
                        default=os.environ.get("MLFLOW_APP_ARN"),
                        help=(
                            "ARN of your SageMaker MLflow APP, e.g. "
                            "arn:aws:sagemaker:us-east-1:<account>:mlflow-app/app-XXXX. "
                            "Create it once with `aws sagemaker create-mlflow-app`. "
                            "This is NOT an MLflow Tracking Server -- see the warning "
                            "on track_run() below. Omit to skip tracking."
                        ))
    parser.add_argument("--mlflow-experiment", type=str, default="northstar-churn",
                        help="MLflow experiment name; runs group under this")
    parser.add_argument("--run-name", type=str, default=None,
                        help="Name for this run. Make it descriptive -- 'run3' tells "
                             "you nothing three weeks later.")

    parser.add_argument("--include-churn-risk-score", action="store_true",
                        help="Add churn_risk_score (a recency heuristic) as an input. "
                             "Off by default; the lab requires reporting results "
                             "with and without it if you use it.")

    # Model Registry. Only the run you choose as final should register.
    parser.add_argument("--register", action="store_true",
                        help="Register this run's model in the Model Registry "
                             "(PendingManualApproval). Refused if a gate fails.")
    parser.add_argument("--model-package-group", type=str,
                        default="northstar-churn-models",
                        help="Lab 5 deploys from this group by name; do not change it")
    parser.add_argument("--inference-image", type=str,
                        default=os.environ.get(
                            "INFERENCE_IMAGE",
                            "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-xgboost:1.7-1"),
                        help="Serving container recorded in the model package")
    parser.add_argument("--region", type=str,
                        default=os.environ.get("AWS_REGION", "us-east-1"))

    parser.add_argument("--model-dir", type=str,
                        default=os.environ.get("SM_MODEL_DIR", "./model"))
    parser.add_argument("--output-data-dir", type=str,
                        default=os.environ.get("SM_OUTPUT_DATA_DIR", "./output"))

    return parser.parse_args()


# ── Feature Store Loading ──────────────────────────────────────────────────────

# These are exactly the features your Lab 2 pipeline wrote to the Feature
# Group. If a name here does not match your feature group, the Athena query
# below will fail - check `aws sagemaker describe-feature-group` first.
#
# Note what is NOT in this list: churn_label (the target) and customer_id
# (an identifier, not a signal). Including either as an input is leakage.
FEATURE_COLUMNS = [
    # Recency and tenure
    "days_since_last_purchase",
    "customer_tenure_days",
    # Frequency
    "purchase_frequency_30d",
    "purchase_frequency_90d",
    "purchase_frequency_180d",
    # Monetary
    "avg_order_value",
    "total_spend_90d",
    "total_lifetime_value",
    "avg_basket_size_6m",
    # Behavioural - these are the features that catch churners who still
    # look active on recency alone. Drop them and your model collapses
    # toward the recency-only baseline.
    "category_diversity_score",
    "online_to_store_ratio",
]

# churn_risk_score is available in the feature group but deliberately excluded
# here: it is a pure recency heuristic and doubles as the baseline you must
# beat. If you add it, report your metrics both with and without it.
BASELINE_COLUMN = "churn_risk_score"

# The recency-only baseline model uses just this one feature. Task 1 requires
# you to train it and show your full model beats it by a margin whose 95%
# confidence interval excludes zero. There is no fixed AUC-lift threshold: a
# ">= 0.03 lift" gate lived here until 2026-08-02 and was removed because 0.03
# is smaller than the metric's own run-to-run standard deviation, so it failed
# on 21% of splits regardless of model quality. See EVAL_THRESHOLDS below.
BASELINE_FEATURE = "days_since_last_purchase"

LABEL_COLUMN = "churn_label"

# Not a feature. This is the column Task 1's slice evaluation groups by, so it
# has to come back from the query even though it never enters the model. Keep it
# out of FEATURE_COLUMNS: loyalty_tier correlates with spend, and feeding it in
# both leaks and makes the per-tier fairness check circular.
SLICE_COLUMN = "loyalty_tier"


def load_features_from_feature_store(feature_group_name: str,
                                     start_date: str,
                                     end_date: str,
                                     artifacts_bucket: str,
                                     region: str) -> pd.DataFrame:
    """
    Load features from the SageMaker Feature Store offline store using Athena.

    Args:
        feature_group_name: your Lab 2 feature group
        start_date, end_date: ISO dates (YYYY-MM-DD) bounding the event_time range
        artifacts_bucket: S3 bucket that Athena writes its result set to. Athena
            will not run a query without an output location, so this has to be
            threaded in from --artifacts-bucket rather than assumed.

    Runs under YOUR credentials, not MLEngineer: that role has no Athena or
    Glue catalog permissions, by design.
    """
    # event_time was written as Fractional (epoch seconds) by the Lab 2 job, so
    # the date bounds must be converted before comparison. Passing ISO strings
    # straight into the query fails with TYPE_MISMATCH rather than returning
    # rows, so at least the failure is loud.
    start_epoch = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    end_epoch = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()

    # The offline store's Glue table name is generated by Feature Store
    # (<feature-group>-<timestamp>), so read it from the feature group.
    sm = boto3.client("sagemaker", region_name=region)
    catalog = sm.describe_feature_group(FeatureGroupName=feature_group_name)[
        "OfflineStoreConfig"]["DataCatalogConfig"]
    table_name, database = catalog["TableName"], catalog["Database"]
    print(f"Querying offline store {database}.{table_name} via Athena")

    # Things the query below gets right:
    #
    # Two things in the query below are easy to get wrong, so read them:
    #
    # 1. event_time is Fractional - Unix epoch SECONDS, not an ISO string.
    #    Comparing it to '2026-04-01' fails the query outright with:
    #      TYPE_MISMATCH: Cannot check if double is BETWEEN varchar(10)...
    #    Convert your date bounds to epoch seconds before substituting them.
    #
    # 2. The offline store is append-only. Re-running the Lab 2 feature job
    #    writes a SECOND record for every customer, and a naive SELECT then
    #    returns duplicate customers with stale feature values. Deduplicate
    #    with a window function keyed on customer_id, keeping the most recent
    #    event_time. Filtering on a global MAX(write_time) does NOT work -
    #    it keeps only the customers written in the final microsecond.
    #
    #    The offline store also soft-deletes: rows carry is_deleted, and
    #    deleted records must be excluded.
    #
    # 3. The outer SELECT must ORDER BY customer_id, and this is the one people
    #    skip because it looks cosmetic. It is not. Athena parallelises the scan
    #    across the offline store's Parquet objects and returns rows in whatever
    #    order the splits happen to finish, which varies from run to run.
    #    train_test_split(random_state=42) is deterministic only for a GIVEN row
    #    order -- so without ORDER BY, the identical data produces a different
    #    train/test split, and therefore different metrics, on every single run.
    #
    #    This was measured, not theorised: four runs on byte-identical data
    #    produced AUC between 0.7276 and 0.7431, and a Platinum-slice AUC
    #    between 0.430 and 0.700. An entire "the model is worse than random on
    #    your best customers" finding turned out to be an artefact of row order.
    #
    #    The rn = 1 filter guarantees customer_id is unique here, so ordering on
    #    it is a TOTAL order and the pipeline becomes reproducible.
    #
    #    If your metrics move between runs and your data did not, this is why.

    #    loyalty_tier is selected but is NOT in FEATURE_COLUMNS, and that is
    #    deliberate. It is not an input to the model - it is the column Task 1's
    #    slice evaluation groups by. Keep it out of the feature matrix (see
    #    preprocess_features, which selects FEATURE_COLUMNS explicitly) and
    #    carry it alongside X and y through the split so each row's prediction
    #    can still be attributed to a tier:
    #
    #        X_train, X_val, y_train, y_val, tier_train, tier_val = \
    #            train_test_split(X, y, df[SLICE_COLUMN], test_size=0.30,
    #                             random_state=42, stratify=y)
    #
    #    Split X and y without it and you cannot line the tiers back up.

    query_string = f"""
        WITH ranked AS (
            SELECT
                customer_id,
                {", ".join(FEATURE_COLUMNS)},
                {LABEL_COLUMN},
                {SLICE_COLUMN},
                event_time,
                ROW_NUMBER() OVER (
                    PARTITION BY customer_id
                    ORDER BY event_time DESC, write_time DESC
                ) AS rn
            FROM "{table_name}"
            WHERE event_time BETWEEN {start_epoch} AND {end_epoch}
              AND NOT is_deleted
        )
        SELECT
            customer_id,
            {", ".join(FEATURE_COLUMNS)},
            {LABEL_COLUMN},
            {SLICE_COLUMN}
        FROM ranked
        WHERE rn = 1
        ORDER BY customer_id
    """

    athena = boto3.client("athena", region_name=region)
    output_location = f"s3://{artifacts_bucket}/artifacts/athena-results/"
    qid = athena.start_query_execution(
        QueryString=query_string,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": output_location},
    )["QueryExecutionId"]

    while True:
        status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if status["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)
    if status["State"] != "SUCCEEDED":
        raise RuntimeError(f"Athena query {qid} {status['State']}: "
                           f"{status.get('StateChangeReason', '')}")

    # Athena writes the full result set as CSV to the output location.
    obj = boto3.client("s3", region_name=region).get_object(
        Bucket=artifacts_bucket, Key=f"artifacts/athena-results/{qid}.csv")
    df = pd.read_csv(obj["Body"])
    print(f"Loaded {len(df):,} customers from the offline store (query {qid})")
    if df.empty:
        raise RuntimeError("Offline store returned no rows. The offline store lags "
                           "PutRecord by ~15 minutes, and event_time must fall inside "
                           "--training-start-date/--training-end-date.")
    return df


def load_features_local(path: str) -> pd.DataFrame:
    """Load features from a local CSV file (development mode)."""
    print(f"Loading features from local file: {path}")
    df = pd.read_csv(path)
    missing = [c for c in FEATURE_COLUMNS + [LABEL_COLUMN] if c not in df.columns]
    if missing:
        raise ValueError(f"Local data missing required columns: {missing}")
    # Not fatal - the model trains fine without it - but Task 1's slice
    # evaluation cannot be done at all, so fail the task rather than the run.
    if SLICE_COLUMN not in df.columns:
        print(f"WARNING: '{SLICE_COLUMN}' not in local data — Task 1 slice "
              f"evaluation will not be possible with this file")
    return df


# ── Feature Preprocessing ──────────────────────────────────────────────────────

def preprocess_features(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """
    Clean and prepare features for XGBoost training.
    Returns (X, y) arrays.
    """
    print(f"Preprocessing {len(df):,} samples...")

    # Drop rows where label is missing
    df = df.dropna(subset=[LABEL_COLUMN])

    # Missing values: none are expected. Lab 2's feature job refuses to write a
    # null feature, so this is a fallback only. NaN is left in place for
    # XGBoost's native handling (each split learns which branch missing values
    # take), rather than a -1 sentinel that reads as a real value for features
    # like days_since_last_purchase.
    n_missing = int(df[FEATURE_COLUMNS].isna().sum().sum())
    if n_missing:
        print(f"  WARNING: {n_missing} missing feature values; left as NaN for XGBoost")
    X = df[FEATURE_COLUMNS].astype(float).values
    y = df[LABEL_COLUMN].values.astype(int)

    print(f"  Positive class rate: {y.mean():.1%}")
    print(f"  Feature matrix shape: {X.shape}")

    return X, y


# ── Model Training ─────────────────────────────────────────────────────────────

def train_model(X_train: np.ndarray,
                y_train: np.ndarray,
                X_val: np.ndarray,
                y_val: np.ndarray,
                args) -> xgb.Booster:
    """Train the XGBoost churn model."""

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_COLUMNS)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLUMNS)

    # Class imbalance, computed from the training split rather than hardcoded.
    # On the reference dataset this lands at 3.545.
    spw = (args.scale_pos_weight if args.scale_pos_weight is not None
           else float((y_train == 0).sum() / max((y_train == 1).sum(), 1)))

    # Record the RESOLVED value so track_run() can log what was actually used.
    # Logging args.scale_pos_weight instead would log None on every run that
    # let it compute itself -- which is most of them -- and your MLflow
    # comparison would be missing the one parameter most likely to explain a
    # precision/recall difference between runs.
    args.resolved_scale_pos_weight = spw

    params = {
        # eval_metric ORDER MATTERS. XGBoost early-stops on the LAST metric in
        # this list, not the first. This used to read ["auc", "logloss"], which
        # silently made logloss the early-stopping criterion: under
        # scale_pos_weight the reweighted logloss keeps improving long after
        # ranking quality peaks, so training ran the full 200 rounds instead of
        # stopping near round 31 and validation AUC came out 0.7603 instead of
        # 0.7822. Measured across 50 splits, that cost the model the promotion
        # gate on 28% of them -- a student doing everything right was told their
        # features did not beat recency. Keep "auc" last (defect 49).
        "objective": "binary:logistic",
        "eval_metric": ["logloss", "auc"],
        "max_depth": args.max_depth,
        "eta": args.eta,
        "min_child_weight": args.min_child_weight,
        "subsample": args.subsample,
        "colsample_bytree": args.colsample_bytree,
        "scale_pos_weight": spw,
        "seed": 42,
        "verbosity": 1,
    }

    print(f"\nTraining XGBoost with params: {json.dumps(params, indent=2)}")

    model = xgb.train(
        params=params,
        dtrain=dtrain,
        num_boost_round=args.num_round,
        evals=[(dtrain, "train"), (dval, "validation")],
        early_stopping_rounds=20,
        verbose_eval=25,
    )

    return model


# ── Evaluation ─────────────────────────────────────────────────────────────────

EVAL_THRESHOLDS = {
    "precision_top10":   0.50,   # Minimum precision @ top 10% scored customers
    "recall_top10":      0.25,   # Minimum recall @ top 10% scored customers
    # Note the recall ceiling: with ~22% positives, targeting the top 10% of
    # customers caps achievable recall near 0.45. Hitting 0.25 means capturing
    # roughly half of what is reachable within that contact budget.
}

# There is deliberately NO absolute AUC threshold. One used to live here
# (auc_roc >= 0.72) and it was removed on 2026-08-02: measured across 200
# random train/test splits of the same data, the reference model fell below
# 0.72 on 58% of them. A gate the reference clears by luck of the shuffle
# grades your random seed, not your model. Report AUC; do not gate on it.
#
# The baseline gate is an INTERVAL, not a threshold: the 95% CI on
# (your AUC - recency-only baseline AUC) must exclude zero.
# BASELINE_FEATURE is defined once, near FEATURE_COLUMNS above.
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 42


def train_recency_baseline(X_train: np.ndarray,
                           y_train: np.ndarray,
                           X_val: np.ndarray) -> np.ndarray:
    """Train the recency-only baseline and score the validation split.

    The baseline is a model over `days_since_last_purchase` ALONE, trained on
    the same training rows and scored on the same validation rows as the full
    model. That is what makes the comparison fair.

    It is deliberately NOT a constant predictor. A constant prediction has an
    AUC of exactly 0.5 by construction, so "beating" it proves only that your
    model is better than a coin flip. The question Lab 3 asks is whether your
    feature engineering beats the rule the business already has for free:
    "contact whoever has not purchased in a while."
    """
    i = FEATURE_COLUMNS.index(BASELINE_FEATURE)
    dtr = xgb.DMatrix(X_train[:, [i]], label=y_train, feature_names=[BASELINE_FEATURE])
    dva = xgb.DMatrix(X_val[:, [i]], feature_names=[BASELINE_FEATURE])
    spw = float((y_train == 0).sum() / max((y_train == 1).sum(), 1))
    params = {
        "objective": "binary:logistic", "eval_metric": "auc",
        "max_depth": 4, "eta": 0.1, "subsample": 0.9,
        "colsample_bytree": 0.9, "scale_pos_weight": spw, "seed": 42,
    }
    return xgb.train(params, dtr, num_boost_round=200).predict(dva)


def bootstrap_lift_ci(y_true: np.ndarray,
                      proba: np.ndarray,
                      baseline_proba: np.ndarray,
                      n: int = BOOTSTRAP_N,
                      seed: int = BOOTSTRAP_SEED,
                      alpha: float = 0.05) -> tuple[float, float]:
    """Percentile CI for (model AUC - baseline AUC), by resampling the val set.

    PAIRED: each replicate resamples row indices once and scores BOTH models on
    those same rows, so the interval is on the difference and the correlation
    between the two models is preserved. Resampling them independently breaks
    the pairing and inflates the interval, which would make a real improvement
    look inconclusive.

    Replicates whose resample happens to be single-class are skipped, because
    AUC is undefined there.

    The seed is fixed so the gate is reproducible: the same split must always
    produce the same verdict.
    """
    rng = np.random.default_rng(seed)
    y_true = np.asarray(y_true)
    idx = np.arange(len(y_true))
    diffs = []
    for _ in range(n):
        s = rng.choice(idx, size=len(idx), replace=True)
        ys = y_true[s]
        if len(np.unique(ys)) < 2:
            continue
        diffs.append(roc_auc_score(ys, proba[s]) - roc_auc_score(ys, baseline_proba[s]))
    if len(diffs) < n // 2:
        raise ValueError(
            "Too few usable bootstrap replicates to form a confidence interval. "
            "Your validation set is too small or too imbalanced to support this gate."
        )
    d = np.sort(diffs)
    return float(np.quantile(d, alpha / 2)), float(np.quantile(d, 1 - alpha / 2))


def evaluate_model(model: xgb.Booster,
                   X_val: np.ndarray,
                   y_val: np.ndarray,
                   baseline_proba: np.ndarray) -> tuple[dict, np.ndarray]:
    """
    Evaluate the trained model against required thresholds.
    Returns (metrics, validation scores). metrics["gates_passed"] is 1 only if
    every threshold and the lift CI pass.
    """
    dval = xgb.DMatrix(X_val, feature_names=FEATURE_COLUMNS)
    y_pred_proba = model.predict(dval)

    auc_roc = roc_auc_score(y_val, y_pred_proba)

    # Precision and recall @ top 10%
    top10_threshold = np.percentile(y_pred_proba, 90)
    top10_mask = y_pred_proba >= top10_threshold
    precision_top10 = y_val[top10_mask].mean() if top10_mask.sum() > 0 else 0.0
    recall_top10 = y_val[top10_mask].sum() / y_val.sum() if y_val.sum() > 0 else 0.0

    # Baseline: a model trained on days_since_last_purchase ALONE.
    #
    # This used to be `np.full_like(y_pred_proba, y_val.mean())` - a constant
    # prediction, whose AUC is exactly 0.5 by definition. Beating a coin flip
    # is not evidence that your feature engineering did anything, and it is not
    # what Lab 3 asks for. The comparison that matters is against recency,
    # because recency is the rule the business already has for free.
    #
    baseline_auc = roc_auc_score(y_val, baseline_proba)
    auc_vs_baseline = auc_roc - baseline_auc

    lift_ci_low, lift_ci_high = bootstrap_lift_ci(
        y_val, y_pred_proba, baseline_proba)

    metrics = {
        "auc_roc": round(float(auc_roc), 4),
        "precision_top10": round(float(precision_top10), 4),
        "recall_top10": round(float(recall_top10), 4),
        "auc_vs_baseline": round(float(auc_vs_baseline), 4),
        "baseline_auc": round(float(baseline_auc), 4),
        "lift_ci_low": round(float(lift_ci_low), 4),
        "lift_ci_high": round(float(lift_ci_high), 4),
        "positive_rate_val": round(float(y_val.mean()), 4),
        "n_val_samples": int(len(y_val)),
        # The operating point: score cutoff for the top 10% of customers.
        "top10_threshold": round(float(top10_threshold), 6),
        "eval_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    print("\n── Evaluation Results ──────────────────────────────")
    failures = []
    for metric, threshold in EVAL_THRESHOLDS.items():
        value = metrics[metric]
        status = "✓ PASS" if value >= threshold else "✗ FAIL"
        print(f"  {metric:25s}: {value:.4f}  (threshold: {threshold:.4f})  {status}")
        if value < threshold:
            failures.append(f"{metric}={value:.4f} < {threshold}")

    # The baseline gate: the interval must exclude zero.
    ci_status = "\u2713 PASS" if lift_ci_low > 0 else "\u2717 FAIL"
    print(f"  {'auc_lift 95% CI':25s}: [{lift_ci_low:.4f}, {lift_ci_high:.4f}]"
          f"  (must exclude 0)  {ci_status}")
    if lift_ci_low <= 0:
        failures.append(
            f"auc_lift 95% CI [{lift_ci_low:.4f}, {lift_ci_high:.4f}] includes "
            f"zero - no evidence the model beats the recency-only baseline")

    # A failing run is still an experiment worth recording, so the failures are
    # returned instead of raised: main() logs the run to MLflow either way and
    # refuses only the Model Registry step.
    if failures:
        print(f"  GATES FAILED: {'; '.join(failures)}. Will not register.")
    else:
        print("  All thresholds passed ✓")
    metrics["gates_passed"] = int(not failures)

    return metrics, y_pred_proba


# ── Slice Evaluation ───────────────────────────────────────────────────────────

# A slice needs enough churners for its AUC and recall to mean anything. On an
# earlier, smaller version of this data a Platinum slice with ~2 test churners
# swung between AUC 0.00 and 1.00 depending only on the split.
MIN_SLICE_POSITIVES = 30


def evaluate_slices(y_val: np.ndarray,
                    y_pred_proba: np.ndarray,
                    slice_column: pd.Series,
                    top10_threshold: float) -> dict:
    """
    AUC, recall@10% and n per slice (loyalty tier).

    Recall uses the SAME global top-10% cutoff as the aggregate metric: the
    retention campaign contacts the top 10% of all customers, so a tier's recall
    is the share of its churners that campaign reaches. Flags slices whose
    recall is more than 10pp below aggregate, and slices too small to support a
    claim (fewer than MIN_SLICE_POSITIVES churners).
    """
    slice_column = np.asarray(slice_column)
    contacted = y_pred_proba >= top10_threshold
    aggregate_recall = y_val[contacted].sum() / y_val.sum()

    slice_results = {}
    for tier in sorted(set(slice_column)):
        m = slice_column == tier
        y, p, c = y_val[m], y_pred_proba[m], contacted[m]
        positives = int(y.sum())
        recall = float(y[c].sum() / positives) if positives else float("nan")
        slice_results[tier] = {
            "n": int(m.sum()),
            "positives": positives,
            "auc": float(roc_auc_score(y, p)) if 0 < positives < len(y) else float("nan"),
            "recall_top10": recall,
            "contacted": int(c.sum()),
            "too_small": positives < MIN_SLICE_POSITIVES,
            "recall_gap_flag": bool(recall < aggregate_recall - 0.10),
        }

    sized = {t: r for t, r in slice_results.items() if not r["too_small"]}
    weakest = min(sized, key=lambda t: sized[t]["auc"]) if sized else None

    print(f"\n── Slice evaluation by {SLICE_COLUMN} (aggregate recall@10% "
          f"{aggregate_recall:.3f}) ──")
    print(f"  {'tier':10s} {'n':>5s} {'churners':>8s} {'AUC':>7s} {'recall@10%':>10s} {'contacted':>9s}  notes")
    for tier, r in slice_results.items():
        notes = []
        if r["too_small"]:
            notes.append(f"too small (<{MIN_SLICE_POSITIVES} churners)")
        if r["recall_gap_flag"]:
            notes.append("recall >10pp below aggregate")
        if tier == weakest:
            notes.append("weakest AUC")
        print(f"  {tier:10s} {r['n']:5d} {r['positives']:8d} {r['auc']:7.3f} "
              f"{r['recall_top10']:10.3f} {r['contacted']:9d}  {'; '.join(notes)}")

    return {"aggregate_recall_top10": float(aggregate_recall),
            "weakest_tier": weakest, "tiers": slice_results}


def save_diagnostics(model: xgb.Booster, y_val: np.ndarray, y_pred_proba: np.ndarray,
                     top10_threshold: float, out_dir: str) -> dict:
    """Confusion matrix at the top-10% operating point, and a feature importance plot."""
    pred = (y_pred_proba >= top10_threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_val, pred, labels=[0, 1]).ravel()
    cm = {"threshold": float(top10_threshold), "tn": int(tn), "fp": int(fp),
          "fn": int(fn), "tp": int(tp)}
    print(f"\n── Confusion matrix at top-10% cutoff (score >= {top10_threshold:.4f}) ──")
    print(f"                 predicted stay   predicted churn")
    print(f"  actual stay    {tn:14d}   {fp:15d}")
    print(f"  actual churn   {fn:14d}   {tp:15d}")

    # Gain = average loss reduction from splits on a feature; a better measure
    # of signal than "weight" (split count), which favours continuous features.
    gain = model.get_score(importance_type="gain")
    importance = {f: float(gain.get(f, 0.0)) for f in FEATURE_COLUMNS}
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        items = sorted(importance.items(), key=lambda kv: kv[1])
        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.barh([k for k, _ in items], [v for _, v in items], color="#2F6DB5")
        ax.set_xlabel("Average gain per split")
        ax.set_title("Churn model feature importance (gain)")
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, "feature_importance.png"), dpi=130)
        plt.close(fig)
    except ImportError:
        print("  (matplotlib not installed; skipping feature importance plot)")

    with open(os.path.join(out_dir, "diagnostics.json"), "w") as f:
        json.dump({"confusion_matrix": cm, "feature_importance_gain": importance}, f, indent=2)
    return {"confusion_matrix": cm, "feature_importance_gain": importance}


# ── Experiment Tracking (MLflow App) ───────────────────────────────────────────

def track_run(args, metrics: dict, scale_pos_weight: float,
              slices: dict, data_source: str) -> str | None:
    """
    Log this training run to your SageMaker MLflow App.

    Worth 5 points in Task 1: >=3 runs, each with logged params AND metrics,
    retrievable via mlflow.search_runs.

    ###########################################################################
    #  THERE ARE TWO MLflow PRODUCTS ON SAGEMAKER. USE THE APP.               #
    #                                                                         #
    #    CreateMlflowApp            serverless   NO ADDITIONAL CHARGE   <-- ok #
    #    CreateMlflowTrackingServer $0.60/hour   until you delete it    <-- NO #
    #                                                                         #
    #  $0.60/hr breaches the entire $10 course budget in 16.7 hours and costs #
    #  about $43 over a weekend -- more per hour than any endpoint in this    #
    #  course. It is not an endpoint, so "did I delete my endpoints?" will    #
    #  not find it. Most tutorials describe the Tracking Server because it    #
    #  shipped first. If anything asks you to choose a size (Small/Medium),   #
    #  you are on the wrong product.                                          #
    ###########################################################################

    Two things that fail in ways the error does not explain:

      1. `create-mlflow-app` postdates many installed AWS CLIs. An old CLI
         says "Invalid choice: 'create-mlflow-app'", which reads like a typo
         rather than a version problem. Check `aws --version` and upgrade.

      2. You need BOTH `mlflow` and `sagemaker-mlflow` installed. The second
         is the SigV4 auth plugin for arn:aws:sagemaker:... tracking URIs.
         Without it you get a connection error that never mentions credentials.

    Returns the MLflow run ID (recorded on the registered model), or None.
    """
    if not args.mlflow_arn:
        print("\n(no --mlflow-arn given; skipping experiment tracking)")
        return None

    import mlflow

    mlflow.set_tracking_uri(args.mlflow_arn)   # the App ARN, verbatim
    mlflow.set_experiment(args.mlflow_experiment)

    with mlflow.start_run(run_name=args.run_name) as run:
        mlflow.log_params({
            "max_depth": args.max_depth,
            "eta": args.eta,
            "num_round": args.num_round,
            "min_child_weight": args.min_child_weight,
            "subsample": args.subsample,
            "colsample_bytree": args.colsample_bytree,
            "scale_pos_weight": round(scale_pos_weight, 4),
            "include_churn_risk_score": args.include_churn_risk_score,
            "n_features": len(FEATURE_COLUMNS),
            "xgboost_version": xgb.__version__,
            "data_source": data_source,
        })
        mlflow.log_metrics({k: v for k, v in metrics.items()
                            if isinstance(v, (int, float)) and not isinstance(v, bool)})
        for tier, r in slices["tiers"].items():
            mlflow.log_metrics({f"{tier}_auc": r["auc"],
                                f"{tier}_recall_top10": r["recall_top10"],
                                f"{tier}_n": r["n"]})
        for name in ("diagnostics.json", "feature_importance.png", "evaluation_metrics.json"):
            path = os.path.join(args.output_data_dir, name)
            if os.path.exists(path):
                mlflow.log_artifact(path)
        print(f"\n✓ Logged MLflow run {run.info.run_id} to experiment "
              f"'{args.mlflow_experiment}'")
        return run.info.run_id

    # Notes kept from the starter kit:
    #
    # LOG THE XGBOOST VERSION AS A PARAM. Lab 3 documents that identical data
    # and an identical split produce different metrics on XGBoost 3.2.0 vs 1.7
    # (the SageMaker training container is 1.7). If you train some runs locally
    # and some through SageMaker and do not record the version, you will end up
    # comparing two things that were never comparable and cannot tell why.
    #
    # THREE RUNS IS THE FLOOR, NOT THE GOAL. Three runs with identical
    # hyperparameters and different seeds is the same experiment three times;
    # it earns 2 of 5. Vary something you can defend, and be able to say what
    # the variation did to the metrics.


# ── Model Saving & Registry ────────────────────────────────────────────────────

def save_model(model: xgb.Booster, metrics: dict, args) -> str:
    """Save the model and its metadata to --model-dir, and package model.tar.gz.

    The tarball holds the model under the name the SageMaker XGBoost serving
    container loads ("xgboost-model"), in XGBoost's JSON format.
    """
    os.makedirs(args.model_dir, exist_ok=True)
    model_path = os.path.join(args.model_dir, "xgboost-model")
    model.save_model(model_path + ".json")
    os.replace(model_path + ".json", model_path)

    metadata = {
        "feature_columns": FEATURE_COLUMNS,
        "label_column": LABEL_COLUMN,
        "hyperparameters": {
            "max_depth": args.max_depth, "eta": args.eta, "num_round": args.num_round,
            "min_child_weight": args.min_child_weight, "subsample": args.subsample,
            "colsample_bytree": args.colsample_bytree,
            "scale_pos_weight": getattr(args, "resolved_scale_pos_weight", None),
        },
        "xgboost_version": xgb.__version__,
        "evaluation_metrics": metrics,
        "training_date": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(args.model_dir, "model_metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    tar_path = os.path.join(args.model_dir, "model.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model_path, arcname="xgboost-model")
        tar.add(os.path.join(args.model_dir, "model_metadata.json"),
                arcname="model_metadata.json")
    print(f"\n✓ Model saved to {args.model_dir}")
    return tar_path


def register_model(tar_path: str, metrics: dict, slices: dict,
                   mlflow_run_id: str | None, data_source: str, args) -> str:
    """Upload the model and register it as PendingManualApproval. Never Approved."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"artifacts/models/churn/{stamp}/model.tar.gz"
    boto3.client("s3", region_name=args.region).upload_file(tar_path, args.artifacts_bucket, key)
    model_data_url = f"s3://{args.artifacts_bucket}/{key}"

    sm = boto3.client("sagemaker", region_name=args.region)
    try:
        sm.describe_model_package_group(ModelPackageGroupName=args.model_package_group)
    except sm.exceptions.ClientError:
        sm.create_model_package_group(
            ModelPackageGroupName=args.model_package_group,
            ModelPackageGroupDescription="NorthStar churn prediction models (XGBoost)",
        )

    properties = {k: str(v) for k, v in metrics.items() if k != "eval_timestamp"}
    properties.update({
        "xgboost_version": xgb.__version__,
        "data_source": data_source,
        "mlflow_run_id": mlflow_run_id or "none",
        "weakest_tier": str(slices["weakest_tier"]),
        "max_depth": str(args.max_depth), "eta": str(args.eta),
        "num_round": str(args.num_round),
    })
    arn = sm.create_model_package(
        ModelPackageGroupName=args.model_package_group,
        ModelPackageDescription=(
            f"XGBoost churn model, {len(FEATURE_COLUMNS)} features. "
            f"AUC {metrics['auc_roc']:.4f} vs recency-only {metrics['baseline_auc']:.4f} "
            f"(lift 95% CI [{metrics['lift_ci_low']:.4f}, {metrics['lift_ci_high']:.4f}]); "
            f"precision@10% {metrics['precision_top10']:.4f}, "
            f"recall@10% {metrics['recall_top10']:.4f}."),
        InferenceSpecification={
            "Containers": [{"Image": args.inference_image, "ModelDataUrl": model_data_url}],
            "SupportedContentTypes": ["text/csv"],
            "SupportedResponseMIMETypes": ["text/csv"],
        },
        ModelApprovalStatus="PendingManualApproval",
        CustomerMetadataProperties=properties,
    )["ModelPackageArn"]
    print(f"✓ Registered {arn} (PendingManualApproval)")
    return arn


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    os.makedirs(args.model_dir, exist_ok=True)
    os.makedirs(args.output_data_dir, exist_ok=True)

    print("=" * 60)
    print("NorthStar Churn Prediction — Training Script")
    print("=" * 60)

    if args.include_churn_risk_score:
        # Must happen before loading so the query selects it too.
        FEATURE_COLUMNS.append(BASELINE_COLUMN)

    # 1. Load features
    if args.local_data_path:
        df = load_features_local(args.local_data_path)
        data_source = f"local:{os.path.basename(args.local_data_path)}"
    else:
        df = load_features_from_feature_store(
            args.feature_group_name,
            args.training_start_date,
            args.training_end_date,
            args.artifacts_bucket,
            args.region,
        )
        data_source = f"feature-store:{args.feature_group_name}"

    # 2. Preprocess
    df = df.dropna(subset=[LABEL_COLUMN])
    X, y = preprocess_features(df)

    # 3. Train/test split. test_size=0.30 matches the reference run (6,999 train
    # / 3,000 test). The tier column is split on the same indices so every test
    # row's prediction can be attributed to its tier.
    X_train, X_val, y_train, y_val, tier_train, tier_val = train_test_split(
        X, y, df[SLICE_COLUMN].to_numpy(dtype=object), test_size=0.30, random_state=42, stratify=y
    )
    print(f"\nTrain: {len(X_train):,} | Test: {len(X_val):,}")

    # 4. Train
    model = train_model(X_train, y_train, X_val, y_val, args)

    # 5. Evaluate: gates, slices, confusion matrix, feature importance
    baseline_proba = train_recency_baseline(X_train, y_train, X_val)
    metrics, y_pred_proba = evaluate_model(model, X_val, y_val, baseline_proba)
    slices = evaluate_slices(y_val, y_pred_proba, tier_val, metrics["top10_threshold"])
    diagnostics = save_diagnostics(model, y_val, y_pred_proba,
                                   metrics["top10_threshold"], args.output_data_dir)
    metrics["best_iteration"] = int(model.best_iteration)

    # 6. Write outputs. SageMaker also collects these as job output; that is
    #    job lineage, NOT experiment tracking.
    with open(os.path.join(args.output_data_dir, "evaluation_metrics.json"), "w") as f:
        json.dump({**metrics, "slices": slices,
                   "confusion_matrix": diagnostics["confusion_matrix"]}, f, indent=2)
    tar_path = save_model(model, metrics, args)

    # 7. Track this run in the MLflow App (every run, pass or fail)
    run_id = track_run(args, metrics, args.resolved_scale_pos_weight, slices, data_source)

    # 8. Register only when asked, and only if every gate passed
    if args.register:
        if metrics["gates_passed"]:
            register_model(tar_path, metrics, slices, run_id, data_source, args)
        else:
            print("\n✗ Not registering: this run failed an evaluation gate.")

    print("\n" + "=" * 60)
    print(f"Training complete. AUC-ROC: {metrics['auc_roc']:.4f} "
          f"(xgboost {xgb.__version__})")
    print("=" * 60)


if __name__ == "__main__":
    main()
