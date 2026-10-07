# RCA Copilot Architecture

RCA Copilot supports two root-cause-analysis configurations over the same incident evidence:

- **Baseline** — one agent owns all evidence tools and produces one hypothesis.
- **Multi-agent** — specialist investigators analyze separate evidence domains, then an adjudicator reconciles their reports into a ranked verdict.

The project intentionally keeps both configurations because the evaluation showed that the simpler baseline currently performs better, while the multi-agent design remains useful for studying specialization, parallelism, evidence ownership, and information loss between agents.

---

## 1. System boundary

The deployed API accepts an incident request containing:

- scenario
- alert
- incident start time
- incident end time
- configuration: `baseline` or `multi_agent`

The request is validated by FastAPI/Pydantic before diagnosis begins.

```text
Incident request
      ↓
FastAPI
      ↓
Pydantic validation
      ↓
Evidence sources
      ↓
RCA configuration
      ↓
Verdict
      ↓
DynamoDB
```

The API currently diagnoses **captured incident snapshots** stored under `scenarios/`.

The repository also contains live source adapters for:

- OpenSearch logs
- Prometheus metrics
- Jaeger traces

Those adapters are used when capturing scenarios. The API itself currently replays the stored snapshots for deterministic evaluation.

---

## 2. Shared evidence model

All evidence sources implement explicit interfaces under:

```text
src/rca_copilot/sources/
```

The core abstractions are defined in:

```text
sources/base.py
```

Four evidence domains exist:

```text
Logs
Metrics
Traces
Changelog
```

Each query returns one of three statuses:

```text
SUCCESS
NO_DATA
ERROR
```

These statuses are part of the reasoning contract.

### SUCCESS

The query executed successfully and returned evidence.

### NO_DATA

The query executed successfully but found nothing.

This is meaningful negative evidence.

### ERROR

The source could not be queried reliably.

This means the RCA agent is missing evidence and should not interpret the result as proof that nothing happened.

The distinction between `NO_DATA` and `ERROR` is a correctness requirement of the architecture.

---

## 3. Evidence objects

Every tool execution is converted into an `Evidence` object.

Conceptually:

```text
Evidence
├── evidence_id
├── agent
├── source
├── query
├── status
├── summary
├── raw
└── timestamp
```

Agents reason over these evidence objects rather than directly over source-specific response structures.

This provides a consistent evidence contract across logs, metrics, traces, and changelog records.

---

# 4. Baseline architecture

The baseline is intentionally simple.

```text
               ┌───────────────┐
Logs ─────────▶│               │
Metrics ──────▶│               │
Traces ───────▶│ Baseline Agent│──▶ Hypothesis
Changelog ────▶│               │
               │               │
               └───────────────┘
```

The baseline uses Claude Haiku 4.5 and can call all five RCA tools:

```text
search_logs
get_metrics
find_traces
get_trace_detail
get_recent_changes
```

The agent investigates sequentially within a bounded tool-use loop.

When enough evidence has been gathered, it calls:

```text
submit_hypothesis
```

The resulting hypothesis contains:

```text
cause
confidence
evidence_ids
```

The API converts that hypothesis into the common `Verdict` response format used by both configurations.

---

## 5. Why the baseline exists

The baseline serves two purposes.

First, it establishes a control configuration against which more complex orchestration can be measured.

Second, evaluation showed that the baseline is currently the stronger production configuration.

Measured results:

```text
Baseline:     22 / 28 valid runs correct = 79%
Multi-agent:  10 / 21 valid runs correct = 48%
```

Therefore the project does not assume that additional agents automatically improve RCA quality.

Architecture is treated as an experimental variable.

---

# 6. Multi-agent architecture

The multi-agent configuration uses LangGraph.

Its topology is:

```text
                     ┌─────────────────┐
                     │   Log Analyst   │
                     │  logs + traces  │
                     └────────┬────────┘
                              │
START ────────────────────────┤
                              │
                     ┌────────▼────────┐
                     │ Metrics Analyst │
                     │     metrics     │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │   Adjudicator   │
                     │    changelog    │
                     └────────┬────────┘
                              │
                              ▼
                            END
```

The two investigators begin from `START` and can execute concurrently.

Their reports then fan in to the adjudicator.

---

# 7. Agent boundaries

Each agent owns a deliberately constrained evidence domain.

| Agent | Logs | Metrics | Trace summaries | Trace details | Changelog |
|---|---:|---:|---:|---:|---:|
| Baseline | ✓ | ✓ | ✓ | ✓ | ✓ |
| Log analyst | ✓ | — | ✓ | ✓ | — |
| Metrics analyst | — | ✓ | — | — | — |
| Adjudicator | Reports only | Reports only | Reports only | Reports only | ✓ |

The multi-agent boundaries are intentional.

An investigator must not speculate about evidence outside its assigned domain.

---

# 8. Log analyst

The log analyst owns qualitative incident evidence.

Available tools:

```text
search_logs
find_traces
get_trace_detail
```

Logs answer questions such as:

```text
What error occurred?
Which service emitted it?
What dependency does the message mention?
```

Traces answer questions such as:

```text
Which services actually communicated?
Where in the dependency chain did the failure originate?
Which failing span is deepest in the trace?
```

Logs and traces are grouped under the same investigator because they describe **request-level behavior**.

A log may describe a dependency failure while the trace confirms the actual call path.

Keeping them together allows one investigator to correlate those two forms of evidence without another agent-to-agent handoff.

---

# 9. Metrics analyst

The metrics analyst owns quantitative evidence.

Its only tool is:

```text
get_metrics
```

The tool exposes five predefined queries:

```text
call_rate_by_service
error_rate_by_service
latency_p95_by_service
container_memory_ratio
container_cpu
```

The agent cannot invent arbitrary PromQL.

This is intentional.

Allowing an LLM to construct arbitrary metric queries would introduce another failure mode:

```text
invented metric
      ↓
empty result
      ↓
incorrect reasoning
```

A fixed query catalogue makes evidence collection deterministic and reproducible.

---

# 10. Why metrics are separated

Metrics answer a fundamentally different question from logs and traces.

Logs and traces are mostly qualitative:

```text
What happened to this request?
```

Metrics are quantitative:

```text
How did the system behave over time?
```

Examples include:

- request volume
- error rate
- p95 latency
- CPU
- memory

This separation gives the multi-agent experiment two independent reasoning perspectives rather than simply splitting tools arbitrarily.

---

# 11. Adjudicator

The adjudicator does not directly query:

```text
logs
metrics
traces
```

Instead it receives investigator reports containing:

```text
agent name
sources queried
evidence summaries
evidence IDs
hypotheses
confidence
```

Its job is to reconcile those reports.

It evaluates:

```text
agreement
conflict
coverage gaps
timing
dependency direction
negative evidence
source failures
```

It then submits a `Verdict`.

A verdict can contain at most three ranked causes.

```text
Verdict
├── ranked_causes
├── overall_confidence
├── dissent
├── escalate
└── escalation_reason
```

---

# 12. Why the adjudicator owns the changelog

The changelog is deliberately not assigned to either investigator.

This is one of the central architectural decisions in the project.

The reason is that the changelog is not ordinary telemetry.

Logs, metrics, and traces describe:

```text
what the system did
```

The changelog records:

```text
what humans deliberately changed
```

Examples include:

```text
deployment
configuration change
feature flag
scaling change
```

That makes the changelog especially valuable as **resolving evidence**.

---

## Example: C2

C2 intentionally creates conflicting signals.

The cart service is misconfigured:

```text
VALKEY_ADDR
valkey-cart:6379
        ↓
valkey-cart:6380
```

Cart crashes before producing useful error telemetry.

Meanwhile, another service generates visible downstream errors.

The investigators may therefore disagree about the failing component.

The changelog contains:

```text
service: cart
change_type: CONFIG
Changed VALKEY_ADDR port from 6379 to 6380
```

That evidence allows the adjudicator to distinguish:

```text
downstream symptom
```

from:

```text
causal change
```

---

# 13. Why the changelog is not another investigator

An alternative architecture would be:

```text
Log analyst
Metrics analyst
Trace analyst
Change analyst
       ↓
Adjudicator
```

This was rejected.

The changelog does not need to generate another independent hypothesis.

Its strongest role is to resolve competing hypotheses.

Giving it exclusively to the adjudicator also reduces the risk that one investigator sees the causal change early and dominates the entire investigation.

Instead:

```text
investigators form telemetry-based hypotheses
                ↓
adjudicator checks human changes
                ↓
causal hypothesis is strengthened or rejected
```

This preserves the changelog as an independent tiebreaker.

---

# 14. Why traces belong to the log analyst

A separate trace investigator was considered.

That would produce:

```text
log analyst
metrics analyst
trace analyst
      ↓
adjudicator
```

The design was rejected for the current experiment.

Logs and traces are highly complementary.

For example:

```text
log:
"failed to connect to redis"
```

may identify a technology but not the actual service.

A trace can reveal:

```text
cart
  ↓
valkey-cart:6379
```

The log describes the failure.

The trace establishes the dependency relationship.

Keeping these together avoids an unnecessary extra agent and another lossy summary boundary.

---

# 15. Information ownership

The multi-agent configuration follows explicit evidence ownership.

```text
                    INCIDENT
                       │
        ┌──────────────┴──────────────┐
        │                             │
        ▼                             ▼
 LOG + TRACE DOMAIN             METRIC DOMAIN
        │                             │
        ▼                             ▼
  Log Analyst                  Metrics Analyst
        │                             │
        └──────────────┬──────────────┘
                       │
                 prose reports
                       │
                       ▼
                  Adjudicator
                       │
                  CHANGELOG
                       │
                       ▼
                    Verdict
```

The adjudicator does **not** receive the investigators' entire raw telemetry payloads.

It receives their reports plus evidence identifiers and summaries.

That boundary turned out to be architecturally significant.

---

# 16. The information bottleneck

Evaluation showed that the multi-agent handoff can lose useful evidence.

The flow is:

```text
raw telemetry
      ↓
investigator tool use
      ↓
evidence objects
      ↓
investigator reasoning
      ↓
compressed prose report
      ↓
adjudicator reasoning
      ↓
final verdict
```

The baseline does not have this intermediate compression step.

It reasons directly across all evidence inside one context.

This is the most important explanation for why the simpler configuration currently performs better.

---

# 17. Uneven investigator workloads

The two investigators are not balanced by tool count or workload.

A representative trace showed approximately:

```text
Log analyst
12 turns
24 evidence items
27.4 seconds

Metrics analyst
3 turns
5 evidence items
20.6 seconds

Adjudicator
4 turns
45.9 seconds
```

This creates two consequences.

First, parallelism produces less latency improvement than two equally sized branches would.

Second, the log analyst must compress substantially more evidence into its report.

The adjudicator then receives two reports that appear structurally equivalent even though one summarizes far more investigation.

---

# 18. LangGraph state

The multi-agent graph maintains shared state containing:

```text
incident_id
alert
window_start
window_end
evidence
hypotheses
reports
run_metas
verdict
```

The investigator branches append to shared collections.

LangGraph reducers combine:

```text
evidence
hypotheses
reports
run metadata
```

before the adjudicator executes.

The verdict is written after fan-in.

---

# 19. Tool execution boundary

Agents never call observability backends directly.

They request named tools.

Conceptually:

```text
Agent
  ↓
Tool schema
  ↓
execute_tool()
  ↓
Source abstraction
  ↓
Evidence object
```

This provides a single place to:

- normalize source responses
- attach evidence IDs
- generate summaries
- record OpenTelemetry spans
- detect source failures
- emit tool-failure metrics

The architecture therefore separates:

```text
reasoning
```

from:

```text
data acquisition
```

---

# 20. Context reduction

Raw telemetry can be too large to send directly to the model.

The tool layer reduces context before returning evidence.

### Logs

Only a limited number of records are passed to the model.

Individual messages are capped.

### Metrics

Full time series are converted to:

```text
first
last
min
max
point_count
```

### Traces

Only a limited number of summaries or spans are returned.

Span attributes are reduced to diagnostic fields.

This keeps the model context bounded while preserving evidence needed for diagnosis.

---

# 21. Validation boundaries

Pydantic models enforce structural constraints around:

```text
Evidence
Hypothesis
RankedCause
Verdict
IncidentState
DiagnoseRequest
IncidentResponse
```

Examples include:

- confidence must remain between `0` and `1`
- hypotheses require evidence IDs
- non-escalated verdicts require at least one ranked cause
- incident window end must be later than start
- serialized alert payload must not exceed 16 KiB

The multi-agent investigators and adjudicator also validate referenced evidence IDs before accepting hypotheses or verdicts.

---

# 22. Resilience boundary

Model-provider resilience is implemented outside agent prompts.

The Anthropic client itself has automatic retries disabled.

RCA Copilot owns the retry policy.

Retryable conditions include:

```text
rate limits
timeouts
connection failures
provider 5xx errors
```

Retries use bounded exponential backoff with jitter.

Authentication and permission failures are not retried.

Additional safeguards include:

```text
MAX_TOKENS_PER_RUN
MAX_COST_PER_HOUR_USD
RCA_DISABLED
```

These controls prevent reasoning behavior from being the only protection against runaway cost or provider failure.

---

# 23. Observability architecture

RCA Copilot instruments its own reasoning pipeline.

```text
incident.diagnose
├── agent.*
│   └── llm.attempt
└── tool.*
```

OpenTelemetry traces expose:

- agent duration
- LLM attempts
- retries
- token usage
- evidence count
- hypothesis count
- tool failures
- verdict submission

In AWS:

```text
RCA Copilot
      ↓ OTLP
ADOT Collector
      ├── AWS X-Ray
      └── CloudWatch EMF
```

Observability is therefore part of the architecture rather than an external debugging add-on.

---

# 24. Persistence boundary

Completed API diagnoses are persisted in DynamoDB.

The store contains:

```text
incident_id
serialized IncidentResponse
```

The API exposes:

```text
POST /incidents
GET  /incidents/{incident_id}
```

This keeps persistence separate from agent state and orchestration.

---

# 25. Deployment architecture

The application runs on AWS ECS Fargate.

```text
GitHub
   ↓
GitHub Actions
   ↓ OIDC
AWS IAM
   ↓
Docker build
   ↓
ECR
   ↓
ECS Fargate task
   ├── RCA Copilot container
   └── ADOT Collector sidecar
```

Supporting services include:

```text
DynamoDB
SSM Parameter Store
CloudWatch
X-Ray
SNS
EventBridge Scheduler
```

The ECS service normally remains at:

```text
desiredCount = 0
```

to keep the demo environment inexpensive.

---

# 26. Architectural trade-off

The central architectural lesson from the project is:

> Agent specialization is useful only when the information gained from specialization is greater than the information lost at the handoff boundary.

The multi-agent design provides:

- explicit evidence ownership
- parallel investigation
- independent hypotheses
- conflict resolution
- clean agent boundaries

But it also introduces:

- additional model calls
- additional latency
- higher cost
- evidence compression
- another reasoning stage
- another failure boundary

For the current scenarios and model, those costs outweigh the benefits.

Therefore:

```text
baseline = production configuration

multi_agent = experimental comparison
```

The architecture remains intentionally measurable so that this decision can be reversed if future evaluation shows the multi-agent configuration outperforming the baseline.