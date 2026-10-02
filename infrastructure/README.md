# infrastructure/ - Terraform for the NorthStar platform (Labs 1-2)

Six modules wired together by `environments/dev` (real AWS) and
`environments/local` (LocalStack). See the repository README for how to run
the full pipeline.

Check formatting and validity before every apply:

```bash
cd environments/dev
terraform init
terraform fmt -check -recursive ../..   # no output = pass
terraform validate                      # exits 0
```

Both must still pass when you submit — that is 5 of the 15 points in B1.

## Layout

```
modules/vpc/            aws_vpc, public + private aws_subnet, aws_internet_gateway,
                        aws_eip + aws_nat_gateway (optional), public + private
                        aws_route_table and associations, aws_security_group
modules/storage/        aws_s3_bucket + public_access_block, versioning,
                        server_side_encryption_configuration,
                        lifecycle_configuration (optional), aws_s3_object x4
modules/iam/            MLEngineer, DataEngineer, ModelMonitor: aws_iam_role,
                        aws_iam_policy, aws_iam_role_policy_attachment each
modules/sagemaker/      aws_sagemaker_domain, aws_sagemaker_user_profile
modules/glue/           aws_glue_catalog_database, aws_glue_crawler, aws_glue_job x2,
                        aws_glue_connection + aws_security_group, aws_s3_object x2
modules/feature_store/  aws_sagemaker_feature_group
```

Each module contains **only** its designated resources — that is graded.

## The rule that catches people

**No hardcoded names.** The rubric runs:

```bash
grep -rn '"northstar-dev"' infrastructure/modules/
```

and expects nothing. Build names from `var.project` and `var.environment`
(`"${var.project}-${var.environment}-data"`), and give every variable a
`description` — that is also graded.
