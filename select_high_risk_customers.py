"""
Pick the customers the Task 1 churn model flags as high-risk, and build the
profiles the Track B offer system needs.

    python select_high_risk_customers.py \
        --artifacts-bucket "$(terraform -chdir=infrastructure/environments/dev output -raw s3_bucket_name)" \
        --model-dir ./model

1. Features come from the Feature Store offline store, through the same Athena
   query the training script uses.
2. Every customer is scored with the trained model (--model-dir), and the model's
   top 10% are flagged: the same operating point as precision/recall@10%.
3. top_categories is not a feature, so it is computed from the cleaned
   transactions in processed/customers/, using only purchases on or before the
   feature cutoff T. Later purchases are the outcome window and must not leak in.
4. The selection (the highest-scoring flagged customer in each tier, plus the
   next highest overall) is written to data/lab3_high_risk_customers.json, so the
   demo notebook runs without the AWS stack.
"""
import argparse
import io
import json
import os

import boto3
import numpy as np
import pandas as pd
import xgboost as xgb

import churn_training_skeleton as train

FEATURE_CUTOFF = pd.Timestamp("2026-04-01")   # T, as in glue-scripts/feature_engineer.py
TIERS = ["Bronze", "Silver", "Gold", "Platinum"]


def top_categories(bucket: str, prefix: str, region: str) -> dict[str, list[str]]:
    """Each customer's two most-purchased categories in the observation window."""
    s3 = boto3.client("s3", region_name=region)
    keys = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=prefix)
            for o in page.get("Contents", []) if o["Key"].endswith(".parquet")]
    tx = pd.concat(pd.read_parquet(io.BytesIO(s3.get_object(Bucket=bucket, Key=k)["Body"].read()))
                   for k in keys)
    tx = tx[(pd.to_datetime(tx["purchase_date"]) <= FEATURE_CUTOFF)
            & (tx["product_category"] != "unknown")]
    counts = (tx.groupby(["customer_id", "product_category"]).size()
                .reset_index(name="n")
                .sort_values(["customer_id", "n", "product_category"],
                             ascending=[True, False, True]))
    return counts.groupby("customer_id")["product_category"].apply(lambda s: list(s[:2])).to_dict()


def describe(row) -> str:
    """The request sent with each offer, built from the customer's own data."""
    ratio = row["online_to_store_ratio"]
    channel = "mostly online" if ratio > 0.6 else "mostly in store" if ratio < 0.4 else "online and in store"
    cats = " and ".join(c.lower() for c in row["top_categories"])
    return (f"Generate a retention offer for this at-risk {row['loyalty_tier']} member who shops "
            f"{channel} for {cats} and has not purchased in {int(row['days_since_last_purchase'])} days.")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    p.add_argument("--artifacts-bucket", required=True, help="Lab 1 data bucket (terraform output)")
    p.add_argument("--feature-group-name", default="northstar-dev-customer-features")
    p.add_argument("--processed-prefix", default="processed/customers/")
    p.add_argument("--model-dir", default="./model", help="output of churn_training_skeleton.py")
    p.add_argument("--flag-fraction", type=float, default=0.10)
    p.add_argument("--extra", type=int, default=1, help="customers beyond one per tier")
    p.add_argument("--output", default="data/lab3_high_risk_customers.json")
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = p.parse_args()

    meta = json.load(open(os.path.join(args.model_dir, "model_metadata.json")))
    feature_columns = meta["feature_columns"]
    model = xgb.Booster()
    model.load_model(os.path.join(args.model_dir, "xgboost-model"))

    df = train.load_features_from_feature_store(
        args.feature_group_name, "2026-01-01", "2027-01-01", args.artifacts_bucket, args.region)
    # Every profile field the offer needs is a feature, so it comes back from this query.
    df["churn_probability"] = model.predict(
        xgb.DMatrix(df[feature_columns].astype(float).values, feature_names=feature_columns))
    cutoff = np.quantile(df["churn_probability"], 1 - args.flag_fraction)
    flagged = df[df["churn_probability"] >= cutoff].sort_values("churn_probability", ascending=False)
    print(f"Model flags {len(flagged):,} of {len(df):,} customers (score >= {cutoff:.4f}); "
          f"by tier: {flagged['loyalty_tier'].value_counts().to_dict()}")

    cats = top_categories(args.artifacts_bucket, args.processed_prefix, args.region)
    flagged = flagged.assign(top_categories=flagged["customer_id"].map(cats))
    flagged = flagged[flagged["top_categories"].map(bool, na_action="ignore").fillna(False)]

    picks = [flagged[flagged["loyalty_tier"] == t].head(1) for t in TIERS]
    chosen = pd.concat([p for p in picks if len(p)])
    rest = flagged[~flagged["customer_id"].isin(chosen["customer_id"])].head(args.extra)
    chosen = pd.concat([chosen, rest]).sort_values("churn_probability", ascending=False)

    fields = ["loyalty_tier", "days_since_last_purchase", "total_lifetime_value", "avg_order_value",
              "category_diversity_score", "online_to_store_ratio"]
    out = []
    for _, r in chosen.iterrows():
        profile = {"churn_probability": round(float(r["churn_probability"]), 4),
                   **{f: (r[f] if f == "loyalty_tier" else round(float(r[f]), 4)) for f in fields},
                   "top_categories": list(r["top_categories"])}
        out.append({"customer_id": r["customer_id"], "question": describe({**profile}),
                    "customer_context": profile, "actual_churn_label": int(r["churn_label"])})

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump({"model": {"xgboost_version": meta.get("xgboost_version"),
                             "training_date": meta.get("training_date"),
                             "auc_roc": meta["evaluation_metrics"]["auc_roc"]},
                   "flag_rule": f"top {args.flag_fraction:.0%} of scores (>= {cutoff:.4f})",
                   "n_scored": int(len(df)), "n_flagged": int((df["churn_probability"] >= cutoff).sum()),
                   "customers": out}, f, indent=2)
    for c in out:
        cc = c["customer_context"]
        print(f"  {c['customer_id']}  p={cc['churn_probability']:.3f}  {cc['loyalty_tier']:8s} "
              f"{cc['top_categories']}  (actual churn: {c['actual_churn_label']})")
    print(f"Wrote {len(out)} profiles to {args.output}")


if __name__ == "__main__":
    main()
