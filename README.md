# NorthStar Retail AI Platform - CS 401R

Infrastructure and data pipeline for the NorthStar ML platform, built in Terraform on AWS (`us-east-1`).

| Lab | What it adds |
|-----|--------------|
| 1 | VPC, data bucket, MLEngineer role, SageMaker Studio domain |
| 2 | Private subnet + NAT Gateway, DataEngineer and ModelMonitor roles, S3 lifecycle rules, Glue ingestion pipeline, SageMaker Feature Store |

## Repository layout

```
infrastructure/
  modules/
    vpc/            VPC; public subnet (NAT anchor); private subnet (SageMaker, Glue); NAT Gateway + EIP; route tables
    storage/        data bucket: versioning, encryption, public access block, 4 prefixes, 5 lifecycle rules
    iam/            MLEngineer, DataEngineer, ModelMonitor roles and policies
    sagemaker/      Studio domain (private subnet, VpcOnly egress) and user profile
    glue/           catalog database, raw crawler, transform + feature-engineer jobs, NETWORK connection, job scripts upload
    feature_store/  customer feature group (online + offline store)
  environments/
    dev/            real AWS; remote state in S3 (scripts/bootstrap-state.sh)
    local/          LocalStack (vpc, storage, iam only; NAT and lifecycle rules disabled)
glue-scripts/       transform.py, feature_engineer.py - uploaded to artifacts/glue/ on apply
scripts/            verify-lab2.sh, teardown-lab2.sh, bootstrap-state.sh, check-secrets.sh
docs/               ADR, diagrams, data contract, and the evidence output for each lab
```

## Lab 2 additions

**Network.** SageMaker Studio and the Glue job workers run in `northstar-dev-private-1` (`10.0.1.0/24`). Its route table sends `0.0.0.0/0` to a NAT Gateway in the public subnet, so outbound calls to S3 and AWS APIs work but nothing can connect inbound. The domain uses `VpcOnly`, so Studio traffic also goes through the VPC.

**Identity.** Three roles divide the bucket's prefixes:

| Role | Trusted by | Writes | Reads |
|------|-----------|--------|-------|
| `northstar-dev-MLEngineer` | SageMaker | `artifacts/`, `features/` | `artifacts/`, `features/` |
| `northstar-dev-DataEngineer` | Glue, Lambda, SageMaker | `raw/`, `processed/`, `features/`, Feature Store | the above + `artifacts/glue/` (job scripts) |
| `northstar-dev-ModelMonitor` | SageMaker | CloudWatch metrics and alarms | `artifacts/` |

**Retention.** Lifecycle rules expire `raw/` objects after 90 days and `datacapture/` objects after 7. Old object versions are expired after 30 days (`raw/`, `processed/`) or 60 days (`features/`).

**Pipeline.** All steps run as DataEngineer:

```
raw/customers/ (CSV)
  -> northstar-dev-raw-crawler        -> catalog table northstar_dev.customers
  -> northstar-dev-transform          -> processed/customers/  (Parquet, one row per transaction)
  -> northstar-dev-feature-engineer   -> features/customers/   (Parquet, one row per customer)
                                      -> Feature Store northstar-dev-customer-features
                                           (offline copy in features/offline-store/)
```

The transform job trims, types, imputes, and deduplicates on `transaction_id`. The feature job splits each customer's history at `FEATURE_CUTOFF` (2026-04-01): 13 features are computed from purchases on or before that date, and `churn_label` comes only from the 90 days after it. See [docs/lab2-data-contract.md](docs/lab2-data-contract.md) and [docs/lab2-data-lineage.png](docs/lab2-data-lineage.png).

## Running it end to end

Prerequisites: Terraform >= 1.5, AWS CLI v2, Docker (for LocalStack), and Python with `pandas` and `pyarrow` (for the verify script). The state bucket must already exist (`scripts/bootstrap-state.sh`). New accounts also need the SageMaker Studio service-linked role (see `modules/sagemaker/main.tf`).

```bash
# 1. Validate locally (free)
terraform -chdir=infrastructure/environments/dev fmt -check -recursive ../..
make local-validate LOCAL_OUT=docs/lab2-localstack-output.txt

# 2. Deploy (about 15 minutes; the NAT Gateway bills from here on)
cd infrastructure/environments/dev
terraform init
terraform plan
terraform apply 2>&1 | tee ../../../docs/lab2-extend-output.txt
cd ../../..

# 3. Land the raw data and register its schema
BUCKET=$(terraform -chdir=infrastructure/environments/dev output -raw s3_bucket_name)
aws s3 cp northstar-raw-sample.csv "s3://${BUCKET}/raw/customers/northstar-raw-sample.csv"
aws glue start-crawler --name northstar-dev-raw-crawler
aws glue get-crawler --name northstar-dev-raw-crawler --query 'Crawler.State'   # wait for READY

# 4. Transform, then engineer features (check each run reaches SUCCEEDED before the next)
aws glue start-job-run --job-name northstar-dev-transform
aws glue get-job-runs --job-name northstar-dev-transform --query 'JobRuns[0].JobRunState'
aws glue start-job-run --job-name northstar-dev-feature-engineer
aws glue get-job-runs --job-name northstar-dev-feature-engineer --query 'JobRuns[0].JobRunState'

# 5. Verify against the rubric
bash scripts/verify-lab2.sh

# 6. Tear down - terraform destroy alone leaves billable and blocking resources behind
bash scripts/teardown-lab2.sh
```

Editing a script in `glue-scripts/` and re-running `terraform apply` uploads the new version. The jobs pick it up on their next run.

## Cost

The NAT Gateway (about $0.045/hour) is the only resource that bills while idle. Glue runs cost a few cents each (2 G.1X workers, 2 to 3 minutes per job), and Feature Store and S3 cost cents at this data size. `scripts/teardown-lab2.sh` removes everything, including the resources AWS creates outside Terraform's state, and then checks with live API calls that nothing billable remains.
