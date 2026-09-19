## ADR-001: NorthStar Platform Foundation

> ⚠️ **SCAFFOLD — DELETE EVERY BLOCKQUOTE BEFORE SUBMITTING.**
> Every `>` block in this file is a prompt for you, not content. The reference
> tables at the bottom go too. Target length is 700–1000 words of your own
> prose. Ask me to strip the scaffolding once you've filled it in and I'll
> leave only your writing.

### Status

Accepted


### Context

> **Write ~150 words.** Set up the problem before any solution appears.
>
> Answer these:
> 1. What is NorthStar building, and what business problem drives it? (The
>    churn number and where it comes from.)
> 2. Why does a platform shared by *three different* AI systems need an
>    identity model on day one, rather than added later once things work?
> 3. Why does the storage tier structure have to exist before any data lands
>    in it? Think about what happens if raw PII and model artifacts share one
>    undifferentiated bucket and you later need per-role access.
> 4. What constraints are fixed from the outset? (Budget, regulation, latency.)
>
> Do not describe your solution here. Context is the situation any reasonable
> engineer would face; the Decision section is where your choices go.


### Decision

> **Write ~250 words.** This is the heart of the ADR and carries 4 rubric
> points for referencing NorthStar-specific requirements. A rationale that
> would read identically for any company scores zero here — every "because"
> must trace to something in the NorthStar case.
>
> Cover three things, and justify each:
>
> **VPC topology** — one VPC at 10.0.0.0/16, a single public subnet at
> 10.0.100.0/24 in us-east-1a, IGW, and a security group admitting only
> intra-VPC traffic.
> - Why does Studio need outbound internet at all?
> - Why is inbound restricted to the VPC CIDR when the subnet is public?
> - Why is a single AZ acceptable *for Lab 1* but not for the finished
>   platform? Name which of the three systems breaks first and why.
>
> **S3 prefix design** — one bucket, four prefixes (`raw/`, `processed/`,
> `features/`, `artifacts/`).
> - Why one bucket with prefixes instead of four buckets?
> - What does the stage split buy you that a flat bucket does not? Tie this to
>   who is allowed to touch which stage.
> - Why is versioning on, in terms of a specific failure you can name?
>
> **IAM role model** — one role today (`northstar-dev-MLEngineer`), trusted by
> `sagemaker.amazonaws.com`, with object access scoped to `artifacts/` and
> `features/` only.
> - What is this role deliberately *unable* to do, and why does that matter
>   given who else will use this platform?
> - Why are `ListBucket` and the object actions in separate statements? (The
>   trailing-wildcard trap is a real, specific failure — explain it.)


### Consequences

#### What this makes easy

> **Write ~100 words, 3–4 bullets.** Rubric demands each consequence cite a
> number, name a constraint, or identify a failure mode. "It's simpler" earns
> nothing; "the /16 leaves 65,280 addresses free for Lab 2's private subnets"
> earns the point.
>
> Candidates — pick the strongest and make them concrete:
> - Adding the DataEngineer and ModelMonitor roles in Lab 2 is a policy change
>   against prefixes that already exist. What does that avoid?
> - One bucket means one place to apply the 24-month retention rule.
> - Address space headroom.
> - Whole environment rebuilds from one command — you measured this.

#### What this makes harder

> **Write ~120 words, 3–4 bullets.** Be genuinely critical here. A section
> that finds no real downsides reads as not having thought about it.
>
> Candidates:
> - Single AZ, single subnet. Which system's availability target does this
>   make unmeetable, and by how much?
> - Studio in a public subnet with unrestricted egress. What is the actual
>   exposure, given what data this platform will hold?
> - Prefix-scoped IAM is only as good as the ARN patterns. What breaks silently
>   if someone widens one?
> - SSE-S3 rather than a KMS CMK. What can't you do that a regulator might ask
>   for? Who at NorthStar asks?

#### What would cause you to revisit this decision

> **Write ~100 words, 3–4 bullets.** Each should name a *trigger* — a
> threshold, event, or date — not a vague "if things change."
>
> Candidates: the agent going to production against its availability target;
> real customer PII landing in `raw/`; role count growing past what per-role
> policies handle cleanly; request rates against a single prefix; cost crossing
> some fraction of the monthly budget.


### Alternative Considered

> **Write ~120 words.** 2 rubric points. It must be an approach that could
> plausibly have worked — if the rejection reason is obvious, it's a strawman
> and scores poorly.
>
> Pick ONE and argue it honestly:
> - **One AWS account per AI system**, isolated via AWS Organizations. Strong
>   candidate: real isolation, real blast-radius reduction, genuinely used in
>   industry. The rejection hinges on the churn model and the offer generator
>   needing the *same* customer features — say what duplicating that pipeline
>   would cost you in consistency and audit surface.
> - **A bucket per data stage** instead of prefixes.
> - **Private subnet + NAT Gateway from day one** (what Lab 2 does). Rejection
>   is partly cost — you have the NAT number in your cost estimate.
>
> State what you rejected, why it could have worked, and the specific reason
> you didn't choose it.


### AWS Service Selection

> **One sentence each, with the deciding reason.** 2 points, and the rubric
> checks all four are present. "It's the standard choice" is not a reason.

- **Networking isolation model** —
- **Storage design** —
- **Identity model** —
- **ML development environment** —

---

> ## REFERENCE — DELETE THIS WHOLE SECTION BEFORE SUBMITTING
>
> ### NorthStar facts (from the case)
> | Fact | Value |
> |---|---|
> | Churn problem | $128.5M/yr = 2.1M customers × 18% × $340 LTV |
> | Churn model | weekly batch, scores due Monday 6 AM ET; target 18% → 14% |
> | Offer generation | RAG; **< 2 second** response; redemption 6% → 12% |
> | Service agent | 14,000 contacts/day, 62% routine; **99.5% availability** 8 AM–10 PM |
> | Regulation | GDPR, CCPA, FCRA/ECOA; **24-month** raw data retention |
> | Platform budget | **$85,000/month**; your personal credits $200 |
> | Clickstream | ~90,000 events/hour peak |
> | Stakeholders | Maya Chen (CDO), Sarah Okafor (Chief Privacy Officer) |
>
> ### What you actually built (use these numbers)
> | Fact | Value |
> |---|---|
> | VPC | 10.0.0.0/16 = 65,536 addresses |
> | Public subnet | 10.0.100.0/24 = 256 addresses (251 usable) → 65,280 free |
> | AZ | us-east-1a only |
> | Security group | inbound all traffic from 10.0.0.0/16 only; egress 0.0.0.0/0 |
> | Bucket | one, 4 prefixes, versioning on, SSE-S3, all 4 public-access blocks |
> | IAM | `raw/` PutObject simulates as **implicitDeny**; artifacts/features allowed |
> | Rebuild | 19 resources, apply clean, destroy in 54s |
> | Cost | $2.12/month; Studio is ~94%; idle space would be $36.50/month |
> | NAT (Lab 2) | ~$32.85/month standing + $0.045/GB processing |
>
> ### Useful arithmetic
> - 99.5% availability ≈ **3.6 hours** of allowed downtime per 30-day month.
>   A single-AZ deployment cannot promise that — an AZ outage exceeds the whole
>   monthly budget in one event.
> - S3 limits: 3,500 PUT/s and 5,500 GET/s **per prefix**. Clickstream at
>   90,000 events/hour ≈ 25/s, so prefixes are not a bottleneck yet.
> - Studio at $0.05/hr: 40 hrs/month = $2.00; 730 hrs = $36.50.
>
> ### Rubric (12 points)
> | Item | Pts | What earns it |
> |---|---|---|
> | NorthStar-specific requirements | 4 | names churn scoring, LLM serving, or the three-system platform — not generic reasoning |
> | Consequences concrete | 4 | every consequence cites a number, names a constraint, or identifies a failure mode |
> | Alternative meaningful | 2 | could plausibly work; rejection reason is specific |
> | Service selection covers 4 | 2 | one sentence per component with the deciding reason |
