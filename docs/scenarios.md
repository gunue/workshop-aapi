# Git-controlled scenario operations

The baseline uses one replica, `Recreate`, CPU requests 100m, limits 800m, and
`CHECKOUT_MODE=normal`. Each fixture has its own Route, Service and Deployment.
These disposable fixtures intentionally become unavailable during exercises.

| Scenario | Namespace | One field changed | Expected evidence |
| --- | --- | --- | --- |
| Startup | workshop-team-a | `runtime.yaml`: CHECKOUT_MODE → `invalid-demo-mode` | Pod exits 64; structured CHECKOUT_MODE error; Deployment unavailable |
| Routing | workshop-team-b | `service-selector.yaml`: app.kubernetes.io/name → `checkout-api-mismatch` | Pod stays ready; Service selects no ready EndpointSlice backends; Route fails |
| Quota | workshop-team-c | `runtime.yaml`: requests.cpu → `700m` | ReplicaSet FailedCreate; 700m exceeds 500m quota while within 800m LimitRange; no new Pod to log |

Paths are under `deploy/overlays/ss76v/team-a`, `team-b`, or `team-c`. Keep limits,
probes, Pod labels, image, namespaces, gateway and observer roles unchanged.
The tests render a copy with each fault and confirm exact reset independently.
They do not enforce the actual PR diff against its base; the human reviewer must
check that the entire PR changes only its intended field.

## Baseline bootstrap

1. Review the implementation and publish the healthy commit as `main`, immutable
   `baseline/v1`, and initial `lab/ss76v` (record full commit and image digest).
2. Protect `main` and `lab/ss76v`: require pull requests, one human approval and
   the `validate` CI job. Disable force pushes and deletion. Repository settings
   require a GitHub administrator; a deploy key cannot configure them.
3. Confirm existing workshop namespaces, effective observer/controller RBAC,
   empty fixture inventory and policy compatibility. Confirm unauthenticated HTTPS fetch of the public repository. No repository
   credential is needed.
4. Render all three overlays with `oc kustomize` (CI uses the equivalent
   `kubectl kustomize`). With the demo context explicitly selected, validate
   each render and every bootstrap YAML with `oc --context="$TARGET_CONTEXT"
   apply --dry-run=server -f FILE`. Resolve failures before applying. Then apply `gitops/ss76v/project.yaml`,
   then the three Application YAML files. They track `lab/ss76v`, use local API
   destination, automatic sync/prune/self-heal, and refuse shared resources.
5. Require Synced/Healthy at the expected revision, one ready Deployment/Pod per
   namespace, ready EndpointSlice backends, populated quota status and trusted
   HTTPS `/api/checkout` returning the synthetic JSON before starting a fault.

## Fault pull request

Use a unique RUN_ID and one fault at a time. From a clean checkout:

```bash
git fetch origin
git switch -c scenario/startup-RUN_ID origin/lab/ss76v
# Edit only team-a/runtime.yaml CHECKOUT_MODE to invalid-demo-mode.
.venv/bin/python -B -m unittest discover -s tests -v
git diff --check
git diff
# Commit the reviewed single-field change and push this scenario branch.
```

Open a PR into `lab/ss76v`; request human review and squash merge only after CI
passes. The gateway does not create or merge PRs and cannot mutate workloads.
Record the full squash commit ID as FAULT_COMMIT. Do not switch Application paths
or target revisions, patch live Deployments, or use rollout undo against GitOps.

## Read-only investigation

Use a fresh gateway operation/idempotency key, the dedicated caller bearer and
an explicit workshop namespace on every tool call. Collect Deployment desired
state, ReplicaSets, Pod status/logs and namespace events. For routing, collect
Route, Service selector and EndpointSlices using
`kubernetes.io/service-name=checkout-api`. For quota, collect ResourceQuota
`checkout-budget` and LimitRange `checkout-limits`, not logs from nonexistent
Pods. Pod logs use container `checkout-api`, `tail=100`, and `previous=true`
when an earlier instance exists. `pods_top` is optional.

Expected skills are `pod-failure-diagnosis`, `route-ingress-troubleshooting`, and
`namespace-troubleshooting`; record the actual returned skill rather than
assuming selection. No Secret, ConfigMap, Node, RBAC, shell/exec, HTTP or Git tool
is needed. Report missing evidence. A human performs the trusted external HTTPS
check; the MCP's lack of HTTP tooling is not evidence of successful recovery.

## Recovery pull request

```bash
git fetch origin
git switch -c fix/startup-RUN_ID origin/lab/ss76v
git revert --no-edit FAULT_COMMIT
.venv/bin/python -B -m unittest discover -s tests -v
git diff --check
# Push the fix branch, open a PR, obtain human review, then squash merge.
```

Repeat with route/quota names. Revert only the chosen fault; do not reset or
force-push the environment branch. Verify the Argo revision matches the fix,
Synced/Healthy, ready Deployment and EndpointSlice, and HTTPS success. For
startup, compare the current Pod UID/start time/restart count over five minutes;
old historical restarts are not a fresh failure. For quota, correlate fresh
admission events and hard/used arithmetic before/after recovery.

Record timestamp, namespace, Git revisions, Pod UID, fresh observations, actual
skill/tool evidence and any gaps in private facilitator notes (never credentials
or sensitive tenant evidence). Complete two fault/recovery cycles per scenario
before declaring rehearsal ready. Leave all three namespaces at healthy baseline.

Application deletion has no cascading finalizer. Retire deliberately: disable
sync, remove the Applications, then remove only these explicitly owned fixtures.
Never delete workshop namespaces or shared gateway/MCP infrastructure.
