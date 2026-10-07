# RCA Copilot — Operations and Chaos Drills

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
