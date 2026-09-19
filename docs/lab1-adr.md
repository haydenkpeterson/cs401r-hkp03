## ADR-001: NorthStar Platform Foundation

### Status

Accepted

### Context

NorthStar is building a platform for three AI systems, not just one model:
churn scoring, an LLM offer generator, and a customer service agent. They all
share the same data and the same infrastructure.

The reason is churn. NorthStar loses about 18% of its customers a year, which
works out to a $128.5M problem. That is big enough that the platform can't be
thrown together now and fixed later.

We need the identity model from day one because of security. Three systems and
several roles will end up touching the same data. If everyone starts with full
access you can't take it away later without breaking things that already work.

The storage tiers have to exist from day one for the same reason. Raw customer
data is under GDPR and a 24-month retention rule and model artifacts are not. If
they all sit in one bucket with no structure, there is nothing for permissions
to attach to.

### Decision

**VPC.** One VPC at 10.0.0.0/16, one public subnet at 10.0.100.0/24 in
us-east-1a, and an internet gateway. We need outbound internet so Studio can
pull its container images and reach S3 and the NorthStar data. Inbound is locked
to the VPC CIDR so that nothing from outside our own AWS can touch the model.
One AZ is fine for development, but it will not hold up for the customer service
agent, which has a 99.5% uptime requirement.

**S3.** One bucket with four prefixes: `raw/`, `processed/`, `features/`,
`artifacts/`. One bucket means one place to apply the 24-month retention rule.
The prefixes are what access control attaches to, and that is what lets Lab 2
give `raw/`, `processed/` and `features/` to a DataEngineer role while the ML
role keeps `artifacts/`. Versioning is on so that a bad transform does not
destroy the version underneath it.

**IAM.** One role, `northstar-dev-MLEngineer`, trusted by SageMaker. It can read
and write `artifacts/` and `features/` and nothing else. It cannot touch `raw/`
or `processed/`, because ingesting and cleaning data is data engineering work
and the ML role is not related to data engineering. Separation of roles. It also
has no permissions over networking or over its own policies. `ListBucket` is in
its own statement, separate from the object actions. If you put the bucket
wildcard in the object statement it also matches `raw/*`, and you would silently
grant the exact write access this role is supposed to not have.

### Consequences

#### What this makes easy

- The whole environment rebuilds from one command. 19 resources, applied clean
  and destroyed in 54 seconds.
- Adding the DataEngineer and ModelMonitor roles in Lab 2 is just a policy
  change, because the prefixes already exist. No data migration.
- Retention is configured in one place instead of four.
- There is plenty of address space left over for the private subnets in Lab 2.

#### What this makes harder

- Everything is in one AZ. A 99.5% target gives the service agent about 3.6
  hours of downtime a month, and one AZ outage burns through that in a single
  event. This topology cannot run that system in production.
- Studio sits in a public subnet with open egress. Nothing can get in, but a
  compromised notebook could send data out to anywhere, and this platform will
  hold PII for millions of customers.
- The IAM model depends entirely on the ARN patterns. Widen one wildcard and
  `raw/` is writable again, with no error to tell you it happened.
- SSE-S3 gives no per-key audit trail and no way to revoke by key. The privacy
  officer will ask about that once real customer data lands.

#### What would cause you to revisit this decision

- The service agent going to production against its uptime target. That forces
  multi-AZ.
- Real customer PII landing in `raw/`. That justifies KMS instead of SSE-S3.
- More roles than we can reasonably audit as individual policies.
- Cost becoming a real share of the $85,000/month platform budget.

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
