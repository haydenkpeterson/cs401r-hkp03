# Lab 4 XOps Assessment

## Pipeline Stage Mapping

**Tool: AWS CodePipeline.** The platform already runs on AWS, the stack is defined in `pipeline.yaml`, and CodeBuild runs under an IAM role, so no AWS keys have to be stored in GitHub.

Five phases run inside three CodePipeline stages. A stage is a hand-off point, so separate stages for each phase would only mean passing the model between CodeBuild projects with no benefit.

| Phase | CodePipeline stage | Where it runs |
|---|---|---|
| 1. Source | `Source` | GitHub connection, triggered by a push to `main` |
| 2. Test | `Build` | `buildspec.yml` `pre_build`: `test_data.py`, `test_features.py` |
| 3. Build | `Build` | `buildspec.yml` `build`: upserts and runs the SageMaker Pipeline, which trains on spot |
| 4. Evaluate | `Build` | `evaluate_model()` raises inside training on a failed gate; then `test_model.py` and `test_fairness.py` run in `build` |
| 5. Register | `Build` (SageMaker Pipeline step) | `RegisterModel` as `PendingManualApproval` |
| Human decision | `ManualApproval` | SNS-notified approval action |

Register runs inside the SageMaker Pipeline, before `test_model.py`. If a CodeBuild test then fails, `post_build` sets that package to `Rejected`, so a red build leaves nothing approvable.

**Push trigger:** pushes did not start runs at first, because the AWS Connector for GitHub app was not installed on the account. `pipeline.yaml` now declares the trigger explicitly, and with the app installed, commit `828cb08` started by webhook. Earlier runs in `lab4-pipeline-runs.txt` were started with `StartPipelineExecution`, which is why commit `4d8544b` has no build. Its failing test is also in `b78da64`, which is the failed build in `lab4-failure-demo.txt`.

## Champion-Challenger

A challenger replaces the champion only if **all** of these hold on the same 3,000-customer test split:

1. Challenger AUC >= champion AUC + **0.005**
2. Precision@10% >= **0.50** and recall@10% >= **0.25**
3. Lift 95% CI over the recency-only baseline has a lower bound > **0**

A challenger with AUC below champion AUC - **0.02** fails the build (`test_no_regression_against_champion`). Between those two lines it stays registered but does not replace the champion. A person still makes the final approval.

## Retraining Triggers

Designed, not deployed.

**(a) Scheduled.** Amazon EventBridge Scheduler, `cron(0 6 ? * MON *)` (Mondays 06:00 UTC), starts the `northstar-dev-feature-engineer` Glue job. When it succeeds, an EventBridge rule on the Glue job state change calls `StartPipelineExecution` on `northstar-pipeline`.

**(b) Performance-based.** A CloudWatch alarm fires when the 7-day rolling production AUC, published as a custom metric, falls below **0.74** (champion 0.7848 minus 0.045) for 2 consecutive daily periods. EventBridge routes the alarm state change to `StartPipelineExecution` on `northstar-pipeline`. Churn labels take 90 days to arrive, so the metric lags by that long; Lab 6 adds drift monitoring as the earlier signal.

## DataOps Maturity

> **TODO (your words).** Fill in the four lines using the chapter's Level 0-4 model:
>
> Current level: [0/1/2/3/4]
> Evidence: [specific artifacts]
> Gap to Level [N+1]: [the specific missing capability]
> Top priority investment: [one concrete tool or practice]
>
> Facts you can cite (all exist in the repo):
> - `glue-scripts/transform.py`, `glue-scripts/feature_engineer.py`, and the `infrastructure/modules/glue/` Terraform: the pipeline is code.
> - `docs/lab2-data-contract.md`: a written contract for `processed/customers`.
> - `tests/test_data.py`: 28 tests run on every build, including freshness (under 48 hours) and a recomputation that catches post-cutoff leakage. See `docs/lab4-build-green.log`.
> - Glue jobs and the crawler are started by hand; nothing schedules them.
> - Data quality is only checked when CI runs, not when data lands.
> - No automated drift detection yet (Lab 6).

## MLOps Maturity

> **TODO (your words).** Same four lines. Facts you can cite:
> - `buildspec.yml`, `pipeline.yaml`, `models/churn/pipeline_definition.py`: a push trains, tests, and registers with no manual steps.
> - `docs/lab4-pipeline-runs.txt`: every run. `docs/lab4-build-green.log`: 77 tests passed, including `champion v3 auc=0.7848; candidate auc=0.7848`.
> - `docs/lab4-failure-demo.txt`: a failing test stopped in `PRE_BUILD`, no new version, and the alarm reached SNS.
> - `docs/lab4-model-package.json`: lineage (commit SHA, data URI, timestamp, metrics) on the package. It was written by hand after the run, not by the pipeline.
> - `docs/lab4-mlflow-runs.txt`: 6 tracked runs, logged from the Lab 3 script. Pipeline runs do not log to MLflow.
> - Approval is manual; there is no automated deployment (Lab 5) and no monitoring in production (Lab 6).
> - Retraining triggers above are designed, not deployed.
