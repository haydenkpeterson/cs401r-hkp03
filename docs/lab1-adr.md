## ADR-001: NorthStar Platform Foundation

### Status

Accepted

### Context

NorthStar is not building one model, it is building a platform that three AI
systems share: weekly churn scoring, an LLM/RAG offer generator, and a customer
service agent. The business case is churn: NorthStar loses about 18% of its 2.1M
active customers a year at roughly $340 of lifetime value each, a $128.5M annual
problem. That number sets the scope. A platform carrying that much value is not
a prototype, so the pieces that are painful to retrofit belong in place from the
start.

Identity is the first. Three systems and several roles will read and write the
same data, and if all of them start with broad access there is no way to narrow
it later without breaking what already works. Storage structure is the second.
Raw customer records fall under GDPR, CCPA and a 24-month retention rule while
model artifacts do not, so the two cannot share one undifferentiated bucket if
different people are to have different access. Both are cheaper to satisfy now
than to migrate into later.

### Decision

**VPC topology.** One VPC at 10.0.0.0/16 with a single public subnet at
10.0.100.0/24 in us-east-1a, an Internet Gateway, and a route for 0.0.0.0/0.
Studio needs outbound internet to pull container images and reach S3 and the
NorthStar source data, so the subnet has a path out. Inbound is restricted to the
VPC CIDR, so nothing outside our own AWS network can open a connection to Studio
even though the subnet is public. A single AZ is fine for a development
foundation but could not carry the service agent's 99.5% availability
requirement.

**S3 prefix design.** One bucket with four prefixes - `raw/`, `processed/`,
`features/`, `artifacts/` - not four separate buckets. One bucket keeps the
24-month retention rule in a single place, and the prefixes are the boundary
access control attaches to: the stage split is what lets Lab 2 hand `raw/`,
`processed/` and `features/` to a DataEngineer role while the ML role keeps
`artifacts/`. Versioning is on so a bad transform overwriting a processed dataset
leaves the prior version recoverable.

**IAM role model.** One role today, `northstar-dev-MLEngineer`, trusted by
`sagemaker.amazonaws.com`, with object access scoped to `artifacts/` and
`features/` only. It cannot write to `raw/` or `processed/`, and it holds no
permissions over networking or its own policies. This is separation of roles:
ingesting and cleaning source data is data engineering work, not machine
learning work, so the ML role has no business touching those stages and should
not be able to alter the inputs its own model is evaluated against. `ListBucket`
is granted on the bucket ARN in a separate statement from the object actions,
because a trailing wildcard on the bucket in the object statement would also
match `raw/*` and silently grant the write access the role is defined by not
having.

### Consequences

#### What this makes easy

- The environment rebuilds from one command: 19 resources applied cleanly and
  destroyed in 54 seconds, so testing a change costs minutes, not a console
  rebuild.
- Adding the DataEngineer and ModelMonitor roles in Lab 2 is a policy change
  against existing prefixes, not a data migration.
- The 24-month retention rule is configured in one place rather than kept
  consistent across four buckets.
- The /16 leaves 65,280 addresses unused after the public subnet, so Lab 2's
  private subnets need no re-addressing.

#### What this makes harder

- Everything sits in us-east-1a. The service agent's 99.5% target allows roughly
  3.6 hours of downtime a month, and one AZ outage would exceed that in a single
  event, so this topology cannot carry that system to production.
- Studio runs in a public subnet with unrestricted egress. Inbound is closed,
  but a compromised notebook could send data to any host on the internet, and
  this platform will hold PII for 2.1M customers.
- Prefix-scoped IAM is only as strong as its ARN patterns: widening one wildcard
  re-grants `raw/` access with no error and no obvious symptom.
- SSE-S3 encrypts at rest but gives no per-key audit trail and no key-level
  revocation, which the Chief Privacy Officer will ask about once real customer
  data lands.

#### What would cause you to revisit this decision

- The service agent moving to production against its 99.5% target, forcing
  multi-AZ.
- Real customer PII landing in `raw/`, which would justify a KMS customer
  managed key in place of SSE-S3.
- Role count growing past a handful, where per-role policies become harder to
  audit than permission boundaries.
- Platform cost reaching a material fraction of the $85,000/month budget, making
  the single-account, single-region design worth re-examining.

### Alternative Considered

We considered keeping engineered features in NorthStar's existing Snowflake
warehouse instead of S3 prefixes. This is a real option, not a hypothetical one:
Snowflake is already in production, already fed by nightly ETL, and the data team
already knows how to query it, so feature engineering could have happened where
the data lives and skipped a storage tier entirely.

We rejected it because SageMaker reads training data from S3 natively, so every
run would export from Snowflake first, paying egress and adding a step that can
drift out of sync with the warehouse. Model artifacts are binary objects that do
not belong in a relational warehouse, so we would need S3 anyway and would
maintain two storage systems with two access models. One bucket means one
permission model covers both.

### AWS Service Selection

- **Networking isolation model** - A VPC with a single public subnet, because
  Studio needs outbound access to pull container images while NorthStar's
  customer data requires that nothing on the public internet be able to initiate
  a connection inward.
- **Storage design** - S3 with one bucket and four stage prefixes, because
  SageMaker reads training data from S3 natively and the prefixes give the
  per-role access boundary that the 24-month retention and GDPR obligations
  require.
- **Identity model** - IAM roles assumed by services rather than long-lived user
  keys, because three AI systems sharing one data store need access scoped per
  stage, and a role that cannot write to `raw/` cannot corrupt the inputs the
  churn model is measured on.
- **ML development environment** - SageMaker Studio, because it gives the
  notebook, training and model registry workflow the churn model needs in one
  managed environment, and bills only while a space runs, keeping a $0.05/hr
  instance from becoming a standing cost.
