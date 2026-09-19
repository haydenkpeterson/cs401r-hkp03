## ADR-001: NorthStar Platform Foundation

### Status

Accepted

### Context

NorthStar is building a platform for three AI systems, not just one model. Each of the systems
shares the same data and the same infrastructure. NorthStar loses about 18% of its customers a year, which makes it a big enough issue to build out infrastructure right now.

We need the identity model from day one because of security. Three systems and
several roles will end up touching the same data. If everyone starts with full
access you can't take it away later without it breaking.

The storage tiers have to exist from day one for the same reason. Raw customer
data is under GDPR and a 24-month retention rule and model artifacts are not. If
they all sit in one bucket with no structure, there is a problem.
### Decision

**VPC.** One VPC at 10.0.0.0/16, one public subnet at 10.0.100.0/24 in
us-east-1a, and an internet gateway. We need outbound internet so Studio can
pull its container images and reach S3 and the NorthStar data. Inbound is locked
to the VPC CIDR so that nothing from outside our own AWS can touch the model.
One AZ is fine for development, but it will not hold up for the customer service
agent, which has a 99.5% uptime requirement.

**S3.** One bucket with four prefixes: `raw/`, `processed/`, `features/`,
`artifacts/`. One bucket means we don't have to configure four separate buckets with the same retention rule.
The prefixes are what access control attaches to, and that is what lets Lab 2
give `raw/`, `processed/` and `features/` to a DataEngineer role while the ML
role keeps `artifacts/`. Versioning is on so that a bad transform does not
destroy the version underneath it.

**IAM.** One role, `northstar-dev-MLEngineer`, trusted by SageMaker. It can read
and write `artifacts/` and `features/` and nothing else. It cannot touch `raw/`
or `processed/`, because ingesting and cleaning data is data engineering work
and the ML role is not related to data engineering. Separation of roles.

### Consequences

#### What this makes easy

- The whole environment rebuilds from one terraform. 19 resources very quickly.
- IAM roles are scoped from the start. No rescinding privileges.
- One VPC and AZ, which keeps things light for dev work.

#### What this makes harder

- Need a future implementation for production environment. ie multiple AZ's and redundancies in place to hit our target 99.5% availability.
- Studio sits in a public subnet that can send data anywhere if compromised.
- SSE-S3 gives no per-key audit trail and no way to revoke by key.

#### What would cause you to revisit this decision

- Our model going to production, which needs multiple Availability zones.
- More roles than we can reasonably audit as individual policies.
- Costs ballooning past $85,000 a month, which would need us to scale down.

### Alternative Considered

We thought about keeping the engineered features in NorthStar's existing
Snowflake warehouse instead of in S3. That is a real option. Snowflake is
already running, already fed by nightly ETL, and the data team already knows how
to query it, so we could have done the feature work where the data already lives
and skipped a storage tier.

We did not because SageMaker reads training data from S3 directly. Every
training run would have to export out of Snowflake first, which costs egress and
adds a step that can drift out of sync with the warehouse. Model artifacts are
binary files and do not belong in a relational warehouse anyway, so we would
still need S3 and would end up running two storage systems with two different
access models. Keeping features next to artifacts means one permission model
covers both.

### AWS Service Selection

- **Networking isolation model** - A VPC with one public subnet, because Studio
  needs to reach out for container images while nothing on the internet should
  be able to reach in to customer data.
- **Storage design** - S3 with one bucket and four stage prefixes, because
  SageMaker reads from S3 directly and the prefixes give us the per-role
  boundary that the retention and GDPR rules need.
- **Identity model** - IAM roles assumed by services instead of long-lived keys,
  because three systems share one data store and a role that cannot write to
  `raw/` cannot corrupt the data the churn model is measured on.
- **ML development environment** - SageMaker Studio, because it gives us
  notebooks, training and the model registry in one place, and it only bills
  while a space is actually running.
