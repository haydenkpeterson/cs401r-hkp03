# Lab 4 XOps Assessment

## Pipeline Stage Mapping

**Tool: AWS CodePipeline**, because the platform already runs on AWS and CodeBuild uses an IAM role, so no AWS keys are stored in GitHub. Five phases run in three stages; a stage per phase would only add hand-offs between CodeBuild projects.

| Phase          | CodePipeline stage | Where                                                                    |
| -------------- | ------------------ | ------------------------------------------------------------------------ |
| 1. Source      | `Source`           | Push to `main` through the GitHub connection                             |
| 2. Test        | `Build`            | `buildspec.yml` `pre_build`: `test_data.py`, `test_features.py`          |
| 3. Build       | `Build`            | `buildspec.yml` `build`: SageMaker Pipeline trains on spot               |
| 4. Evaluate    | `Build`            | Gates in `evaluate_model()`, then `test_model.py` and `test_fairness.py` |
| 5. Register    | `Build`            | SageMaker Pipeline `RegisterModel`, `PendingManualApproval`              |
| Human decision | `ManualApproval`   | SNS-notified approval                                                    |

Note: push triggers only worked once the GitHub app was installed, so `828cb08` was the first run started by a push. Commit `4d8544b` has no build; its failing test is also in `b78da64`, the failed build in `lab4-failure-demo.txt`.

## Champion-Challenger

A challenger replaces the champion only if all of these hold on the same test split:

1. AUC >= champion AUC + **0.005**
2. Precision@10% >= **0.50** and recall@10% >= **0.25**
3. Lift 95% CI lower bound > **0**

## Retraining Triggers

Designed, not deployed.

**(a) Scheduled:** Amazon EventBridge Scheduler, `cron(0 6 ? * MON *)`, runs the feature Glue job, then starts `northstar-pipeline`.

**(b) Performance-based:** a CloudWatch alarm fires when 7-day rolling production AUC falls below **0.74** for 2 consecutive days. EventBridge routes the alarm to start `northstar-pipeline`.

## DataOps Maturity

> Current level: 2
>
> Evidence: The pipeline is glue code (`glue-scripts/`, `infrastructure/modules/glue/`), and our data contract sets the quality rules (`docs/lab2-data-contract.md`). We run an automatic test suite every build (`tests/test_data.py`) and each of those passed (28 passed in `docs/lab4-build-green.log`).
>
> Gap to Level 3: We start glue jobs by hand and our data is only checked for quality when our CI runs, not when we receive new data.
>
> Top priority investment: Use Amazon EventBridge to start the pipeline and a trigger for the glue jobs to run when new data is in raw/.

## MLOps Maturity

> Current level: 3
>
> Evidence: Every push to main trains, tests and registers a model automatically (`buildspec.yml`, `pipeline.yaml`). Our latest build passed all 77 tests, and the regression test against the champion (`champion v3 auc=0.7848; candidate auc=0.7848` in `docs/lab4-build-green.log`). When we pushed a failing test the build stopped in pre build, no new model was registered, and the alarm sent us an email (`docs/lab4-failure-demo.txt`). Each registered model also keeps its commit, data and metrics (`docs/lab4-model-package.json`).
>
> Gap to Level 4: We still approve models by hand, nothing deploys an approved model, and nothing watches the model in production. Our retraining triggers are only designed but are not running yet.
>
> Top priority investment: Add SageMaker Model Monitor with a CloudWatch alarm that uses EventBridge to start northstar-pipeline.
