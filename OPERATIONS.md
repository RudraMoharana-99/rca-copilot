# RCA Copilot — Operations and Chaos Drills

## Operational Runbook

RCA Copilot runs as an AWS ECS Fargate service in `ap-south-1`.

The production configuration is the **baseline** RCA pipeline. The `multi_agent` configuration remains experimental and is evaluated separately.

The service is normally scaled to:

```text
desiredCount = 0
```

to minimize demo infrastructure cost. CI/CD and manual operational testing temporarily scale it to one running task.

### Core AWS resources

| Resource | Name |
|---|---|
| ECS cluster | `rca-copilot` |
| ECS service | `rca-copilot-service` |
| ECS task family | `rca-copilot` |
| ECR repository | `rca-copilot` |
| DynamoDB table | `rca-copilot-incidents` |
| Application log group | `/ecs/rca-copilot` |
| Metrics log group | `/ecs/rca-copilot-metrics` |
| CloudWatch namespace | `RCACopilot` |
| Region | `ap-south-1` |

The production Fargate task uses:

```text
CPU:    512 units
Memory: 1024 MiB
```

and contains:

```text
rca-copilot
aws-otel-collector
```

The application container is essential. The ADOT collector sidecar is non-essential so loss of telemetry export does not terminate the RCA API itself.

---

## Health Check

The application exposes:

```text
GET /healthz
```

Expected response:

```json
{
  "status": "ok"
}
```

`/healthz` is intentionally a **liveness** endpoint.

It does not call:

- Anthropic
- DynamoDB
- telemetry evidence sources
- X-Ray
- CloudWatch

This prevents a downstream dependency problem from making the application itself appear dead.

A successful `/healthz` therefore means:

> the API process is running and capable of serving HTTP requests.

It does **not** prove that a diagnosis can complete successfully.

---

## Starting the Service

Scale the ECS service to one task:

```powershell
aws ecs update-service `
    --cluster rca-copilot `
    --service rca-copilot-service `
    --desired-count 1
```

Check deployment state:

```powershell
aws ecs describe-services `
    --cluster rca-copilot `
    --services rca-copilot-service `
    --query "services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}"
```

Healthy steady state for an active demo:

```json
{
  "desired": 1,
  "running": 1,
  "pending": 0
}
```

---

## Stopping the Service

Return the demo service to scale-to-zero:

```powershell
aws ecs update-service `
    --cluster rca-copilot `
    --service rca-copilot-service `
    --desired-count 0
```

Verify:

```powershell
aws ecs describe-services `
    --cluster rca-copilot `
    --services rca-copilot-service `
    --query "services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}"
```

Expected final state:

```json
{
  "desired": 0,
  "running": 0,
  "pending": 0
}
```

---

## Operational Kill Switch

New RCA diagnoses can be disabled using:

```text
RCA_DISABLED=true
```

When enabled, `POST /incidents` returns:

```text
HTTP 503
Diagnosis is temporarily disabled
```

The kill switch prevents new LLM-backed diagnoses without rebuilding the application image. Changing the ECS environment variable requires a new task-definition revision and task deployment.

Use it when:

- the model provider is returning unsafe or unstable results
- unexpected model spend is occurring
- a prompt or agent regression is suspected
- evidence integrations are producing misleading results
- incident diagnosis must be suspended during investigation

The liveness endpoint remains available while RCA is disabled.

---

## Input Protection

`POST /incidents` validates the serialized alert payload before the RCA pipeline runs.

Maximum alert size:

```text
16 KiB
```

Requests above that limit are rejected by Pydantic with:

```text
HTTP 422
```

This validation happens before:

- agent execution
- evidence collection
- Anthropic API calls
- token consumption

The limit exists because the per-run token ceiling only observes tokens **after** an LLM response. It is therefore not sufficient protection against an oversized initial prompt.

Drill 5 validated this control with a 1 MiB request.

---

## Model Provider Resilience

The Anthropic SDK's own automatic retries are disabled.

RCA Copilot owns the retry policy explicitly.

Retryable failures include:

- rate limiting
- connection failures
- timeouts
- provider HTTP 5xx responses

The retry policy uses:

```text
maximum attempts: 3
backoff: exponential
jitter: enabled
```

Authentication and permission failures are **not retried** because repeating the same invalid credential cannot recover the request.

If retryable provider failures remain after all attempts, the pipeline records:

```text
provider_unavailable = true
```

and can produce an escalated degraded response rather than continuing to guess.

---

## Cost Controls

Two separate controls exist.

### Per-run token ceiling

Default:

```text
MAX_TOKENS_PER_RUN = 400000
```

Each agent tracks cumulative input and output tokens.

If the limit is reached, the current run stops further model execution and records:

```text
cost_ceiling_hit = true
```

The API exposes this operationally through the `cost_ceiling` outcome.

### Rolling hourly USD ceiling

Default:

```text
MAX_COST_PER_HOUR_USD = 2.0
```

Completed diagnosis costs are tracked in a rolling one-hour in-process window.

When the threshold is already exceeded, new incident requests are rejected with:

```text
HTTP 429
Hourly cost limit reached
```

This is a process-local safeguard rather than a durable billing system.

---

## Monitoring and Alarms

OpenTelemetry application metrics are exported through the ADOT sidecar into CloudWatch EMF under:

```text
RCACopilot
```

Operational alarms notify through SNS.

Four application-level alarms currently exist.

---

### 1. Provider Unavailable Alarm

Alarm:

```text
rca-copilot-provider-unavailable
```

Metric:

```text
api_requests_total
```

Dimension:

```text
outcome = provider_unavailable
```

Trigger:

```text
>= 1 event within a 5-minute period
```

### Why it exists

Transient provider failures are already retried.

Therefore a `provider_unavailable` event means all configured retry attempts were exhausted.

At this point continuing silently would hide a dependency outage that directly prevents RCA execution.

One event is sufficient to page because successful diagnosis depends on the model provider.

---

### 2. Cost Ceiling Alarm

Alarm:

```text
rca-copilot-cost-ceiling
```

Metric:

```text
api_requests_total
```

Dimension:

```text
outcome = cost_ceiling
```

Trigger:

```text
>= 1 event within a 5-minute period
```

### Why it exists

The per-run token ceiling is a runaway-agent safeguard.

Reaching it is not normal usage. It may indicate:

- an agent stuck in repeated tool/model turns
- unusually large context
- prompt regression
- repeated failed reasoning
- unexpected model behavior

The alarm therefore treats a single ceiling hit as operationally significant.

---

### 3. Tool Failure Alarm

Alarm:

```text
rca-copilot-tool-failures
```

Metric:

```text
tool_failures_total
```

Trigger:

```text
>= 1 tool failure within a 5-minute period
```

### Why it exists

RCA quality depends on observability evidence.

A broken telemetry source may not crash the application because sources explicitly return:

```text
ERROR
```

instead.

That behavior is desirable for graceful degradation, but without an alarm it could make the service appear healthy while the model is diagnosing with incomplete evidence.

Drill 2 confirmed that the alarm detects evidence-source failures even when RCA still returns a verdict.

---

### 4. Regression Failure Alarm

Alarm:

```text
rca-copilot-regression-failed
```

Metric:

```text
regression_runs_total
```

Dimension:

```text
outcome = fail
```

Trigger:

```text
>= 1 failed regression execution within a 5-minute period
```

### Why it exists

The RCA system is probabilistic.

HTTP health and infrastructure health cannot detect a reasoning regression.

A prompt edit can leave:

```text
/healthz = 200
```

while diagnostic accuracy collapses.

The regression alarm therefore monitors model behavior rather than application availability.

Drill 3 demonstrated this directly: a deliberately degraded prompt caused C3 baseline accuracy to fall to 0%, and the scheduled-regression telemetry detected the failure.

---

## Scheduled Regression Gate

EventBridge Scheduler runs:

```text
python -m eval.regression
```

on ECS Fargate every:

```text
7 days
```

The baseline configuration is the production regression gate.

Current thresholds are:

| Scenario | Minimum baseline accuracy |
|---|---:|
| C1 — valkey-cart-down | 50% |
| C2 — cart-bad-config | 80% |
| C3 — product-catalog-oom | 60% |
| C4 — astronomy-db-down | 80% |

Each scenario normally runs five times.

Regression execution is fail-fast:

```text
baseline scenario
      ↓
below threshold?
      ├── yes → emit failure metric → exit
      └── no  → next baseline scenario
```

Only after every baseline scenario passes does the job run the experimental multi-agent configuration.

This prevents a known-bad production baseline from consuming additional model budget on experimental evaluations.

---

## Deployment Runbook

Production deployment is performed through GitHub Actions after a push to `main`.

The workflow performs:

```text
checkout
   ↓
uv dependency install
   ↓
ruff check
   ↓
ruff format --check
   ↓
pytest
   ↓
GitHub OIDC authentication to AWS
   ↓
Docker build
   ↓
push image to ECR
   ↓
render new ECS task definition
   ↓
deploy service with desiredCount = 1
   ↓
wait for ECS stability
   ↓
GET /healthz smoke test
   ↓
scale service back to 0
```

The Docker image is tagged with:

```text
github.sha
```

rather than `latest`.

This creates a direct mapping:

```text
Git commit
    ↕
Docker image
    ↕
ECS task revision
```

ECR image tags are immutable.

---

## Configuration and Secrets

Normal configuration is passed as ECS environment variables.

Examples:

```text
AWS_REGION
INCIDENTS_TABLE
RCA_DISABLED
MAX_TOKENS_PER_RUN
MAX_COST_PER_HOUR_USD
OTEL_EXPORTER_OTLP_ENDPOINT
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT
```

Sensitive configuration is not committed into the image.

The Anthropic key is stored in AWS Systems Manager Parameter Store:

```text
/rca-copilot/anthropic-api-key
```

ECS injects it into the application container as:

```text
ANTHROPIC_API_KEY
```

The ADOT collector configuration is also stored in SSM and injected into the collector container.

---

## Rollback Runbook

Because deployments are identified by immutable Git-SHA images and ECS task-definition revisions, rollback does not require rebuilding an older image.

At 2am, the rollback process is:

```text
1. Identify the last known-good ECS task definition.
2. Update rca-copilot-service to that task definition.
3. Set desiredCount = 1.
4. Wait for ECS service stability.
5. Call /healthz.
6. Run a known diagnosis if model behavior is in question.
7. Inspect CloudWatch logs and X-Ray.
8. Keep the known-good revision if healthy.
```

ECS also has the deployment circuit breaker enabled with automatic rollback for deployments that fail to stabilize.

Application rollback and model-behavior rollback are not the same thing.

A deployment can be technically healthy while producing poor RCA results. In that case the evaluation/regression evidence must determine the known-good revision.

---

## How to Know the System Is Working

No single signal is sufficient.

Use several layers.

### Layer 1 — process

```text
GET /healthz → 200
```

Confirms the API process is alive.

### Layer 2 — ECS

Confirm:

```text
desiredCount
runningCount
pendingCount
```

match the expected operational state.

### Layer 3 — logs

Check `/ecs/rca-copilot` for:

- application startup
- request failures
- Python exceptions
- provider errors

### Layer 4 — tracing

Use AWS X-Ray to inspect:

```text
incident.diagnose
agent.*
llm.attempt
tool.*
```

This exposes agent latency, retries, and failed evidence queries.

### Layer 5 — metrics and alarms

Inspect:

- `api_requests_total`
- `tool_failures_total`
- `regression_runs_total`
- token usage
- agent duration

### Layer 6 — RCA quality

Run a known scenario and compare the returned root component with the expected component.

This final layer matters because infrastructure health does not guarantee reasoning quality.

---

## Known Monitoring Gaps

Chaos testing identified monitoring gaps that are intentionally documented rather than hidden.

### Provider authentication failures

Invalid Anthropic credentials produce a `ProviderAuthError`.

Current behavior:

```text
POST /incidents → HTTP 500
```

The existing provider alarm watches:

```text
outcome = provider_unavailable
```

Authentication failure exits before `record_api_request()` records that outcome.

Therefore:

```text
automatic detection: FAILED
```

during Drill 1.

Required future improvement:

```text
explicit provider_auth_error metric/outcome + CloudWatch alarm
```

---

### ECS OOM / abnormal task termination

Drill 4 forced the RCA application container to:

```text
128 MiB memory
```

and produced:

```text
exit code 137
OutOfMemoryError
```

ECS correctly recorded the failure.

However, all existing application-level alarms remained healthy because the process died before application telemetry could report the fault.

Current gaps:

- no ECS abnormal-stop alarm
- no OOM-specific alert
- no ECS container health check
- no automatic task-state-change notification

Required future improvement:

```text
EventBridge ECS Task State Change
      ↓
detect abnormal stopped reason / exit code
      ↓
SNS / operational alarm
```

---

### Confidence calibration

Drill 2 deliberately removed the metrics source.

Despite losing evidence, model confidence increased:

```text
healthy:   0.85
degraded:  0.92
```

This demonstrates that model-reported confidence must not be interpreted as a calibrated reliability score.

Future improvement should calculate an external confidence adjustment from deterministic signals such as:

- evidence source availability
- number of `ERROR` evidence results
- cross-source agreement
- missing expected evidence domains

---

## Chaos Test Summary

| Drill | Failure injected | Expected protection | Result |
|---|---|---|---|
| 1 | Invalid Anthropic credential | Detect provider failure | **Detection gap found** |
| 2 | Metrics source unavailable | Tool-failure detection + graceful degradation | **PASS; confidence issue found** |
| 3 | Deliberately degraded prompt | Regression gate | **PASS** |
| 4 | Container memory starvation | Infrastructure failure detection | **Detection gap found** |
| 5 | 1 MiB alert payload | Reject before LLM execution | **PASS** |

The detailed evidence for each experiment follows below.

---

## Session 25–26 Chaos Testing

### Drill 1 — Invalid Anthropic API Credential

**Purpose**

Validate provider authentication failure handling, service liveness, alerting, and operational recovery.

**Prediction**

- `/healthz` remains healthy because it does not depend on Anthropic.
- `/incidents` fails immediately with `ProviderAuthError`.
- Authentication failures are not retried.
- Existing `provider_unavailable` alarm may not detect this failure because it watches the `provider_unavailable` outcome.

**Failure injection**

- Invalid credential written to SSM at 11:08:59.
- ECS task restarted so the new task loaded the invalid credential.

**Observed behaviour**

- `/healthz`: HTTP 200 — PASS.
- `/incidents`: HTTP 500 with `Diagnosis failed: ProviderAuthError`.
- No degraded verdict was returned.
- Authentication failure correctly bypassed retry logic.
- `rca-copilot-provider-unavailable` remained `OK`.

**Detection**

- Automatic CloudWatch detection: FAILED.
- Failure was detected manually through the failed `/incidents` request.
- Time-to-detect by configured alarm: Not detected.

**Mitigation**

- Original API key restored to SSM at 13:00:38.
- ECS task restarted to reload the restored credential.
- Recovery verified at 13:11:29.
- Time-to-mitigate: 10.8 minutes.
- Recovery RCA request completed successfully in 16.6 seconds with confidence 0.85.

**Finding**

The application handles provider authentication failure correctly, but observability has a gap: `ProviderAuthError` exits before an `api_requests_total` provider-failure outcome is recorded, so the existing provider-unavailable alarm does not fire.

**Follow-up**

Add explicit telemetry/alarming for provider authentication failures after completing the chaos drills, rather than modifying the system before documenting the observed failure.

### Drill 2 — Metrics Source Unreachable

**Purpose**

Validate graceful degradation when one evidence source becomes unreachable, verify tool-failure telemetry, and confirm CloudWatch alerting.

**Healthy baseline**

- Scenario: C3-product-catalog-oom.
- Correct root cause identified.
- Overall confidence: 0.85.
- Escalation: False.
- Elapsed time: approximately 19.0 seconds.

**Failure injection**

- A one-off ECS Fargate task was launched with `PrometheusMetricsSource` pointed at `http://127.0.0.1:1`.
- Production API service was not modified.
- Faulty task started at 22:40:03.

**Observed behaviour**

- Forced metrics query returned `Status.ERROR`.
- Agent continued operating with changelog, logs, and traces.
- Four additional metrics queries also returned `ERROR`.
- The agent still identified the correct product-catalog memory-limit reduction as the root cause.
- Confidence increased from 0.85 to 0.92 instead of decreasing.
- Chaos task exited normally with exit code 0.

**Detection**

- `tool_failures_total` emitted value 5:
  - 1 forced metrics failure.
  - 4 agent-generated metrics failures.
- `rca-copilot-tool-failures` transitioned to `ALARM`.
- Alarm transition: 22:41:18.936.
- Time-to-detect from actual faulty-task start: approximately 75.6 seconds.

**Mitigation / containment**

- The fault was isolated to a temporary ECS task.
- Task stopped automatically at 22:41:18.036.
- Fault containment duration from task start: approximately 74.7 seconds.
- Production service required no remediation.
- Production time-to-mitigate: Not applicable.

**Finding**

The RCA system tolerates loss of the metrics source and continues diagnosis using other evidence. Tool-failure telemetry and CloudWatch alerting worked correctly.

However, confidence calibration is not enforced. Despite losing a diagnostically important evidence source, confidence increased from 0.85 to 0.92. Prompt guidance alone is insufficient to guarantee confidence reduction under partial evidence.

**Follow-up**

Introduce deterministic confidence adjustment or evidence-availability scoring when required sources return `Status.ERROR`, rather than relying exclusively on the LLM to lower confidence.

### Drill 3 — Deliberately Degraded RCA Prompt

**Purpose**

Validate that automated regression testing detects a prompt change that significantly reduces RCA quality before the change can be trusted in production.

**Failure injection**

- The production baseline prompt was deliberately degraded.
- Important safeguards were removed, including:
  - silent-service reasoning,
  - cross-source verification,
  - trace causality guidance,
  - changelog usage,
  - confidence reduction under weak evidence.
- The degraded prompt was deployed through the normal CI/CD pipeline.

**Local validation**

C3-product-catalog-oom was tested five times using the degraded prompt.

- Correct: 0/5 (0%).
- Required regression threshold: 60%.
- Execution errors: 0.
- Mean confidence: 0.89.
- Regression gate correctly failed.

This demonstrated a genuine AI-quality regression rather than an application failure.

**Infrastructure finding**

The first AWS regression attempt failed before evaluation because the non-root container user could not create `/app/runs`.

Observed error:

`PermissionError: [Errno 13] Permission denied: 'runs'`

The Docker image was corrected to create `/app/runs` and give ownership to `appuser`.

**Cost-control finding**

The regression runner originally continued running all baseline scenarios and the experimental multi-agent configuration even after the production baseline had already failed.

This caused unnecessary LLM token consumption.

The runner was changed to fail fast:

- Run baseline scenarios in order.
- On the first failed baseline threshold:
  - emit `regression_runs_total{outcome="fail"}`,
  - force-flush telemetry,
  - exit immediately.
- Multi-agent evaluation runs only when the complete production baseline gate passes.

**Targeted AWS verification**

To limit token usage, a single C3 baseline evaluation was run against the deployed degraded prompt.

- Test started: 00:52:59.
- Correct: 0/1 (0%).
- Required threshold: 60%.
- Execution errors: 0.
- Confidence: 0.95.
- Elapsed model evaluation: 12.9 seconds.
- Estimated LLM cost: $0.0216.
- Regression result: FAILED.

**Detection**

- `regression_runs_total{outcome="fail"}` emitted successfully.
- CloudWatch datapoint recorded at approximately 00:53.
- `rca-copilot-regression-failed` transitioned to `ALARM` at 00:54:07.
- Observed time-to-detect from targeted test start: approximately 68 seconds.

**Mitigation**

- The known-good baseline prompt was restored.
- CI/CD deployed the restored prompt successfully.
- Restored image commit: `7490eb9`.
- ECS task definition: revision 21.
- Restored revision registered at 01:04:43.
- Time-to-mitigate from alarm: approximately 10 minutes 36 seconds.

**Result**

PASS.

The regression system successfully detected a deliberately harmful prompt change and raised the production regression alarm.

The drill also exposed and corrected two operational weaknesses:

1. Regression output directory permissions inside the production container.
2. Excessive token usage caused by continuing evaluation after the production gate had already failed.

### Drill 4 — Container Memory Starvation

**Purpose**

Validate application behaviour under severe container memory pressure and determine whether ECS health checks or CloudWatch alarms detect the failure.

**Failure injection**

- Created an isolated task-definition family: `rca-copilot-chaos-memory`.
- Production task definition `rca-copilot:21` was not modified.
- Task-level resources remained:
  - CPU: 512
  - Memory: 1024 MiB
- Added a 128 MiB hard memory limit to the `rca-copilot` container.
- Executed a synthetic workload that allocated memory in 16 MiB increments.

**Observed behaviour**

- Task started at 17:04:37.095.
- Application container exceeded its 128 MiB limit.
- ECS terminated the container with exit code 137.
- ECS explicitly reported:
  `OutOfMemoryError: container killed due to memory usage`
- Task stopped at 17:05:16.470.
- Time from task start to OOM termination: approximately 39.4 seconds.
- OTel collector exited normally with exit code 0.

**Health and restart behaviour**

- No ECS container health check is currently configured for `rca-copilot`.
- Because this was an isolated one-off task rather than an ECS Service task, ECS did not restart the failed container.
- Therefore restart behaviour of the production ECS Service was not exercised in this drill.

**Detection**

All existing RCA CloudWatch alarms remained `OK`:

- provider unavailable
- cost ceiling
- regression failed
- tool failures

Automatic OOM/infrastructure failure detection: FAILED.

Time-to-detect by configured monitoring: Not detected.

**Mitigation / containment**

The failure was fully isolated to the temporary chaos task.

Production was never modified and therefore required no recovery.

Production time-to-mitigate: Not applicable.

**Finding**

Fargate correctly enforced the container memory limit and terminated the application when it exceeded that limit.

However, RCA Copilot currently has no monitoring path for ECS task termination or container OOM events. It also has no ECS container health check configured.

**Follow-up**

Add infrastructure-level monitoring for abnormal ECS task exits/OOM events and consider an ECS container health check for the RCA service.

### Drill 5 — Oversized Input

**Purpose**

Validate that oversized incident alerts are rejected before entering the RCA pipeline or reaching the Anthropic provider.

**Prediction**

- Oversized input should be rejected at the API validation boundary.
- `create_incident()` should not execute.
- No Anthropic request should be made.
- Normal-sized alerts should continue to work.

**Failure injection**

A 1 MiB alert payload was submitted.

Before the protection was added, the same payload was accepted:

```text
REQUEST_ACCEPTED
Alert bytes: 1048576
```

This exposed an input-protection gap. The existing `CostTracker` checks token usage after an LLM response and therefore cannot prevent an oversized initial prompt from reaching the provider.

**Mitigation**

Added a serialized alert-size limit to `DiagnoseRequest`:

```text
MAX_ALERT_BYTES = 16384
```

The alert is serialized as UTF-8 JSON and rejected when its serialized size exceeds 16 KiB.

Automated validation:

```text
ruff check  -> PASS
pytest      -> 25 passed
ruff format -> clean
```

Normal-sized alerts remained accepted.

**Live AWS verification**

The updated application was deployed as:

```text
Task definition: rca-copilot:22
Commit: 0c3c911
```

The ECS service was temporarily scaled to one task and `/healthz` returned healthy.

The same 1 MiB alert was submitted to:

```text
POST /incidents
```

Observed result:

```text
HTTP 422
Value error, alert must not exceed 16384 bytes
```

The request was rejected by FastAPI/Pydantic validation before entering the RCA execution path.

**Detection**

- Oversized request rejected synchronously with HTTP 422.
- Time-to-detect: Immediate at request validation.
- No CloudWatch alarm was required because this is a preventive API-boundary control.

**Mitigation / containment**

- The oversized request never entered the RCA pipeline.
- No runtime recovery was required.
- Time-to-mitigate: Immediate.
- ECS service was returned to `desiredCount = 0` after verification.

**Result**

PASS.

Before the fix, a 1 MiB alert was accepted.

After the fix, alerts larger than 16 KiB of serialized UTF-8 JSON are rejected with HTTP 422 before RCA processing.

**Finding**

Input-size validation must happen before LLM invocation. Token and cost controls that execute after a provider response are not sufficient protection against oversized initial prompts.
