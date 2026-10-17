# NorthStar Retail AI Platform - CS 401R

Terraform code for the NorthStar machine learning platform on AWS.

## Modules

| Module | What it does |
|--------|--------------|
| `vpc` | The network. Lab 2 added a private subnet and a NAT Gateway, so SageMaker and Glue can reach the internet but the internet cannot reach them. |
| `storage` | The S3 bucket. Lab 2 added rules that delete old data automatically. |
| `iam` | The roles. Lab 2 added DataEngineer (runs the data pipeline) and ModelMonitor (only watches). |
| `sagemaker` | SageMaker Studio. Lab 2 moved it into the private subnet. |
| `glue` | **New in Lab 2.** The crawler and the two jobs that clean the data and make features. |
| `feature_store` | **New in Lab 2.** Stores one row of features per customer for model training. |

## How the data pipeline works

1. Raw purchase data (CSV) is uploaded to `raw/customers/`.
2. The **crawler** reads the file and records its columns.
3. The **transform** job cleans the data and saves it to `processed/customers/`.
4. The **feature-engineer** job makes one row per customer and saves it to `features/customers/` and Feature Store.

## How to run it

```bash
# 1. Create the infrastructure
cd infrastructure/environments/dev
terraform init
terraform apply
cd ../../..

# 2. Upload the data and run the crawler (wait until it says READY)
aws s3 cp northstar-raw-sample.csv s3://$(terraform -chdir=infrastructure/environments/dev output -raw s3_bucket_name)/raw/customers/
aws glue start-crawler --name northstar-dev-raw-crawler
aws glue get-crawler --name northstar-dev-raw-crawler --query 'Crawler.State'

# 3. Run the two jobs, one at a time (wait until each says SUCCEEDED)
aws glue start-job-run --job-name northstar-dev-transform
aws glue get-job-runs --job-name northstar-dev-transform --query 'JobRuns[0].JobRunState'
aws glue start-job-run --job-name northstar-dev-feature-engineer
aws glue get-job-runs --job-name northstar-dev-feature-engineer --query 'JobRuns[0].JobRunState'

# 4. Check the results
bash scripts/verify-lab2.sh

# 5. Delete everything when finished (the NAT Gateway costs money every hour)
bash scripts/teardown-lab2.sh
```

## Lab 3: Models

| File | What it does |
|------|--------------|
| `churn_training_skeleton.py` | Trains the churn model (XGBoost) on Feature Store data pulled with Athena, logs each run to the MLflow App, and registers the final model |
| `select_high_risk_customers.py` | Scores customers with the trained model and saves the high-risk ones for offers |
| `offer_rag.py` | Track B: writes retention offers with RAG over `northstar-policy-docs/` (Titan embeddings, FAISS, Claude Haiku) |
| `evaluation_harness.py` | Scores the offers with RAGAS |
| `notebooks/lab3-demo.ipynb` | Demo: offers for the model's high-risk customers |

### How to run it

```bash
pip install -r requirements-lab3.txt
BUCKET=$(terraform -chdir=infrastructure/environments/dev output -raw s3_bucket_name)

# 1. Train (the Lab 2 stack must be up and the offline store filled)
python churn_training_skeleton.py --artifacts-bucket "$BUCKET" \
    --max-depth 3 --eta 0.05 --num-round 600 --run-name my-run \
    --mlflow-arn "$MLFLOW_APP_ARN" --output-data-dir docs/lab3-evidence --register

# 2. Pick high-risk customers for offers
python select_high_risk_customers.py --artifacts-bucket "$BUCKET" --model-dir ./model

# 3. Evaluate the offer system
python evaluation_harness.py --track B
python tests/offer_guardrail_checks.py

# 4. Export evidence, then clean up
bash scripts/collect-lab3-evidence.sh --track B
bash scripts/teardown-lab3.sh
```

### Where things land

- **Model:** `./model/` locally, `s3://<bucket>/artifacts/models/churn/` in S3, and the Model Registry group `northstar-churn-models` (status PendingManualApproval)
- **Experiment runs:** MLflow App `northstar-mlflow`, experiment `northstar-churn`
- **Athena results:** `s3://<bucket>/artifacts/athena-results/`
- **Evidence for grading:** `docs/lab3-evidence/`, `docs/lab3-evaluation-report.md`, `docs/lab3-model-design.md`
