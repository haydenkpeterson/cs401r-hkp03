# Lab 1 — Monthly Cost Estimate

NorthStar Retail AI platform, Lab 1 foundation only (VPC, S3, IAM, SageMaker
Studio, remote state). Region `us-east-1`. Steady state, meaning the platform
as it sits after `terraform apply` with one ML engineer using it — no training
jobs, no endpoints, no production traffic. Those arrive in later labs.

All unit prices were taken from the AWS Price List API on 2026-09-16, which is
the same data behind the AWS Pricing Calculator. The exact SKUs are cited under
each line so the numbers can be re-checked rather than taken on faith.

## Summary

| Component | Monthly Estimate | Key Assumptions | One Optimization |
|---|---|---|---|
| SageMaker Studio | $2.00 | 1 JupyterLab space, `ml.t3.medium` at $0.05/hr, 2 hrs/day × 20 weekdays = 40 hrs | Shut the space down after every session — idle-running costs $36.50/mo |
| S3 storage (data bucket) | $0.12 | 5 GB across `raw/ processed/ features/ artifacts/` at $0.023/GB-Mo | Lifecycle rule expiring noncurrent versions after 90 days |
| Internet Gateway | $0.00 | Gateway itself is free; ~1 GB/mo egress, inside the 100 GB free tier ($0.09/GB after) | S3 VPC gateway endpoint keeps bucket traffic off the IGW entirely |
| DynamoDB (state lock) | $0.00 | On-demand; ~100 Terraform runs/mo ≈ 500 writes + 500 reads; < 1 KB stored | Already minimal — on-demand beats provisioned at this volume |
| S3 state bucket | $0.00 | ~50 KB state file × ~100 retained versions ≈ 5 MB at $0.023/GB-Mo | Same lifecycle rule; state versions accumulate on every apply |
| **Total** | **$2.12** | | |

Rounded to the cent. Three rows are genuinely sub-cent rather than actually
zero; they are shown as $0.00 because that is what lands on the bill.

## How each line was derived

### SageMaker Studio — $2.00

The only component with meaningful cost, and the only one billed by the hour.

- SKU `USE1-Studio:JupyterLab-ml.t3.medium` = **$0.05/hr**.
- Assumption: one engineer, one JupyterLab space, roughly two hours of active
  notebook work per weekday. 2 × 20 = 40 hrs/month.
- 40 hrs × $0.05 = **$2.00/month**.

The Domain and the user profile themselves cost nothing. Billing starts when a
space is *running* and stops when it is shut down — which is exactly why the
lab requires the shutdown screenshot.

Not included, because Lab 1 never provisions them: the EBS volume attached to a
Studio space and the EFS filesystem Studio creates for home directories. Both
are near-zero at this scale, but both survive a stopped app and are the usual
source of a surprise dollar or two.

### S3 storage — $0.12

- SKU `TimedStorage-ByteHrs`, first 50 TB tier = **$0.023/GB-Mo**.
- Assumption: 5 GB total. The four prefixes are empty at the end of Lab 1
  (they hold zero-byte placeholder objects), so this is a forward-looking
  figure for early Lab 2 data — a few churn extracts and a feature set.
- 5 GB × $0.023 = **$0.115**, rounds to $0.12.
- Request charges (PUT $0.005/1,000, GET $0.0004/1,000) are under a cent at
  this volume and are omitted.

Versioning is enabled, so every overwrite retains the prior version and is
billed as a separate object. At 5 GB that is noise; at 500 GB of reprocessed
feature sets it is not, which is what the lifecycle optimization addresses.

### Internet Gateway — $0.00

- The Internet Gateway resource itself has **no hourly charge**. This is worth
  stating plainly because the lab's template table suggests a $0.01/GB figure;
  the actual billed item is EC2 data transfer out, SKU `DataTransfer-Out-Bytes`
  at **$0.09/GB** for the first 10 TB — not $0.01.
- Assumption: ~1 GB/month egress. Studio's heavy traffic is *inbound* (pulling
  container images from ECR), and inbound transfer is free. Outbound is just
  the Studio UI session.
- The AWS free tier covers 100 GB/month of egress, so **$0.00**. Without it,
  1 GB × $0.09 = $0.09.

### DynamoDB state lock — $0.00

- On-demand: **$0.625 per million write request units**, **$0.125 per million
  read request units**.
- Assumption: ~100 Terraform operations/month, each taking and releasing one
  lock — call it 500 writes and 500 reads.
- 0.0005 M × $0.625 + 0.0005 M × $0.125 = **$0.000375**.
- The table holds a single lock item well under 1 KB, inside the 25 GB free
  storage allowance.

Effectively free, which is the point: the lock costs nothing and prevents two
applies from corrupting one state file.

### S3 state bucket — $0.00

- Same $0.023/GB-Mo rate.
- Assumption: a ~50 KB `dev/terraform.tfstate`, versioned, with ~100 retained
  versions ≈ 5 MB.
- 0.005 GB × $0.023 = **$0.000115**.

## The optimization, quantified

**Shut down the JupyterLab space at the end of every session.**

This is the single highest-leverage cost control in Lab 1, because Studio is
~94% of the total bill and is billed on wall-clock time, not usage.

| Scenario | Hours/month | Cost |
|---|---|---|
| Space shut down after each session (2 hrs/day, weekdays) | 40 | $2.00 |
| Space left running continuously | 730 | $36.50 |
| **Savings** | | **$34.50/month** |

A forgotten space costs **18× the intended spend**, and turns a $2.12 platform
into a $36.62 one. On a fixed course credit budget that is the difference
between the credits lasting seven labs and running out partway through.

The second-order version of this, worth doing in Lab 2: an S3 VPC gateway
endpoint. It costs nothing, and it keeps bucket traffic off the internet path
entirely — which matters much more once Lab 2 introduces a NAT Gateway, where
the same traffic would otherwise be billed at $0.045/GB processing on top of
the NAT's own $0.045/hr (~$32.85/month) standing charge.
