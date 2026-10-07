# RCA Copilot — 5-Minute Demo Script

## 0:00–0:30 — What the project is

“RCA Copilot is an evidence-grounded root-cause-analysis system that correlates logs, metrics, distributed traces, and deployment or configuration changes.

I built two architectures: a single-agent baseline and a LangGraph multi-agent version. Interestingly, the simpler baseline performed better in evaluation.”

Show briefly:

```text
README.md
```

Highlight:

```text
Baseline: 79%
Multi-agent: 48%
```

---

## 0:30–1:00 — Architecture

Show the README or `ARCHITECTURE.md` diagram.

Say:

“The baseline agent can query all evidence sources directly.

The multi-agent version runs a log-and-trace analyst and a metrics analyst in parallel, then sends their reports to an adjudicator. The adjudicator uniquely owns the changelog so it can use human changes as resolving evidence.”

Do not explain every class or file.

---

## 1:00–1:30 — Start the environment

Show ECS currently scaled to zero.

```powershell
aws ecs describe-services `
    --cluster rca-copilot `
    --services rca-copilot-service `
    --query "services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}"
```

Then scale it:

```powershell
aws ecs update-service `
    --cluster rca-copilot `
    --service rca-copilot-service `
    --desired-count 1
```

Show:

```text
desired = 1
running = 1
pending = 0
```

Explain:

“The service normally runs at zero tasks to reduce demo infrastructure cost.”

---

## 1:30–2:25 — Run one diagnosis

Use a known scenario, preferably **C2 cart misconfiguration**, because the changelog clearly demonstrates causal reasoning.

Send:

```text
POST /incidents
```

with:

```json
{
  "scenario": "C2-cart-bad-config",
  "alert": {
    "message": "elevated error rate detected"
  },
  "window_start": "2026-09-03T05:46:32Z",
  "window_end": "2026-09-03T06:01:32Z",
  "config": "baseline"
}
```

Show the response.

Highlight:

```text
root cause: cart
confidence
evidence IDs
escalation status
```

Say:

“The visible errors occur downstream, but the actual injected fault is a cart configuration error. RCA Copilot combines telemetry with the changelog instead of simply blaming the loudest failing service.”

---

## 2:25–3:10 — Show tracing

Open AWS X-Ray.

Show one RCA trace.

Point out:

```text
incident.diagnose
agent
llm.attempt
tool calls
```

Then show the multi-agent trace screenshot if useful.

Say:

“OpenTelemetry traces the RCA process itself, not just the application being diagnosed.

This trace also exposed a performance problem in the multi-agent architecture. The investigators execute concurrently, but the adjudicator alone took about 45.9 seconds in this example.”

For the C2 demo trace:

- `incident.diagnose` duration ≈ 18.52s
- trace status = `OK`
- open the trace detail and show the LLM and tool child spans

---

## 3:10–3:45 — Demonstrate the kill switch

Explain:

“Operational controls are outside the prompt.”

Show:

```text
RCA_DISABLED=true
```

Mention expected behavior:

```text
POST /incidents
→ HTTP 503
```

Say:

“This allows new model-backed diagnoses to be stopped without rebuilding the image. The ECS task configuration must be redeployed with the changed environment variable.”

You do not need to actually redeploy during the recording if it consumes too much time.

---

## 3:45–4:20 — Resilience and regression

Show `OPERATIONS.md`.

Briefly show the chaos summary:

```text
Invalid provider key       → monitoring gap found
Metrics unavailable        → detected
Bad prompt                 → regression gate detected
Container OOM              → monitoring gap found
Oversized input            → rejected before LLM
```

Say:

“I deliberately tested failures rather than only the happy path.

Some controls passed, and two tests exposed real monitoring gaps which are documented instead of hidden.”

---

## 4:20–4:40 — CI/CD

Show `.github/workflows/deploy.yml`.

Explain:

“A push to main runs linting and tests, authenticates to AWS through GitHub OIDC, builds the image, tags it with the Git commit SHA, pushes it to ECR, creates a new ECS task definition, deploys it, smoke-tests `/healthz`, and finally scales the service back to zero.”

---

## 4:40–5:00 — Close and teardown

Scale back down:

```powershell
aws ecs update-service `
    --cluster rca-copilot `
    --service rca-copilot-service `
    --desired-count 0
```

Finish with:

“The main result of this project was not that multi-agent is automatically better. Across 49 valid runs, the single-agent baseline achieved 79% accuracy versus 48% for the multi-agent architecture.

The important engineering lesson was to measure agent architecture instead of assuming additional complexity improves the system.”