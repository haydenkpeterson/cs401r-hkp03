"""
Run churn_training_skeleton.py on a local feature CSV, for development only.

The training script loads data exclusively from the Feature Store offline store
via Athena. This helper swaps that loader for a CSV reader from the outside, so
the script can be exercised without the Lab 2 stack running.

    python tests/run_training_local.py features.csv --artifacts-bucket unused \
        --max-depth 6 --eta 0.2 --num-round 200

The CSV needs customer_id, the 11 feature columns, churn_label and loyalty_tier
(the columns the Athena query returns). Do not pass --register or --mlflow-arn:
a model trained on a local file must not reach the registry or the experiment log.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import churn_training_skeleton as train  # noqa: E402


def main():
    if len(sys.argv) < 2 or not sys.argv[1].endswith(".csv"):
        sys.exit(__doc__)
    if any(a in sys.argv for a in ("--register", "--mlflow-arn")):
        sys.exit("Refusing --register / --mlflow-arn on local data.")
    path = sys.argv.pop(1)
    train.load_features_from_feature_store = lambda *args, **kwargs: pd.read_csv(path)
    train.main()


if __name__ == "__main__":
    main()
