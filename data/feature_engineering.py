"""Lab 2's feature logic as pure pandas functions, so it can be unit tested.

glue-scripts/feature_engineer.py computes these in PySpark, which is awkward to
test in isolation. These functions compute exactly the same thing: same windows
(purchase_date > T - N days, counting T itself), same definitions.
tests/test_data.py checks them against the real pipeline output, so the two
cannot drift apart unnoticed.

Every window is measured backwards from the snapshot date (T, the feature
cutoff). Purchases after T are ignored: they are the outcome window, and using
them would leak the label into the features.
"""

import pandas as pd

N_CATEGORIES = 8.0            # denominator for category_diversity_score
NO_PURCHASE_RECENCY = 999.0   # recency for a customer with no purchases on or before T
UNKNOWN_CATEGORY = "unknown"  # the transform's fill value, not a ninth category


def _in_observation_window(transactions, snapshot_date):
    """Transactions on or before T, with purchase_date as dates."""
    tx = transactions.copy()
    tx["purchase_date"] = pd.to_datetime(tx["purchase_date"]).dt.normalize()
    return tx[tx["purchase_date"] <= pd.Timestamp(snapshot_date)]


def _within(tx, snapshot_date, days):
    """True for rows in the N days before T, counting T: (T - N, T]."""
    return tx["purchase_date"] > pd.Timestamp(snapshot_date) - pd.Timedelta(days=days)


def compute_recency_features(transactions, snapshot_date, customers=None,
                             sentinel=NO_PURCHASE_RECENCY):
    """days_since_last_purchase and customer_tenure_days, one row per customer.

    Pass `customers` to include customers with no purchases: their recency is
    `sentinel` and their tenure is 0.
    """
    tx = _in_observation_window(transactions, snapshot_date)
    t = pd.Timestamp(snapshot_date)
    grouped = tx.groupby("customer_id")["purchase_date"]
    out = pd.DataFrame({
        "days_since_last_purchase": (t - grouped.max()).dt.days.astype(float),
        "customer_tenure_days": (t - grouped.min()).dt.days.astype(float),
    }).reset_index()
    if customers is not None:
        out = customers[["customer_id"]].merge(out, on="customer_id", how="left")
        out["days_since_last_purchase"] = out["days_since_last_purchase"].astype(float).fillna(sentinel)
        out["customer_tenure_days"] = out["customer_tenure_days"].astype(float).fillna(0.0)
    return out


def compute_frequency_features(transactions, snapshot_date):
    """purchase_frequency_30d / 90d / 180d: orders in the N days before T."""
    tx = _in_observation_window(transactions, snapshot_date)
    out = pd.DataFrame(index=tx["customer_id"].drop_duplicates())
    for days in (30, 90, 180):
        out[f"purchase_frequency_{days}d"] = (
            tx[_within(tx, snapshot_date, days)].groupby("customer_id").size())
    return out.fillna(0.0).astype(float).reset_index()


def compute_monetary_features(transactions, snapshot_date):
    """avg_order_value, total_spend_90d, total_lifetime_value, avg_basket_size_6m.

    avg_basket_size_6m is ITEMS per order over the last 180 days, not dollars,
    and 0 for a customer with no orders in those 180 days.
    """
    tx = _in_observation_window(transactions, snapshot_date)
    value = tx.groupby("customer_id")["order_value"]
    out = pd.DataFrame({
        "avg_order_value": value.mean().astype(float),
        "total_lifetime_value": value.sum().astype(float),
    })
    out["total_spend_90d"] = tx[_within(tx, snapshot_date, 90)].groupby("customer_id")["order_value"].sum()
    out["avg_basket_size_6m"] = tx[_within(tx, snapshot_date, 180)].groupby("customer_id")["num_items"].mean()
    return out.fillna(0.0).astype(float).reset_index()


def compute_behavioral_features(transactions, snapshot_date=None):
    """category_diversity_score (distinct real categories / 8) and
    online_to_store_ratio (share of orders placed online)."""
    tx = transactions if snapshot_date is None else _in_observation_window(transactions, snapshot_date)
    known = tx[tx["product_category"] != UNKNOWN_CATEGORY]
    out = pd.DataFrame(index=tx["customer_id"].drop_duplicates())
    out["category_diversity_score"] = known.groupby("customer_id")["product_category"].nunique() / N_CATEGORIES
    out["online_to_store_ratio"] = (tx["channel"] == "online").groupby(tx["customer_id"]).mean()
    return out.fillna(0.0).astype(float).reset_index()


def build_churn_feature_set(customers, transactions, snapshot_date):
    """One row per customer in `customers`, with every feature.

    Null strategy: customers with no purchases on or before T get the recency
    sentinel and 0 for everything else, so no feature is ever null.
    """
    features = compute_recency_features(transactions, snapshot_date, customers)
    for part in (compute_frequency_features(transactions, snapshot_date),
                 compute_monetary_features(transactions, snapshot_date),
                 compute_behavioral_features(transactions, snapshot_date)):
        features = features.merge(part, on="customer_id", how="left")
    return features.fillna(0.0)
