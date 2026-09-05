# Decisions

Engineering decisions made during this project, with alternatives
considered and what would reverse them.

---

## 1. Pin Python to 3.12, excluding 3.13+

**Date:** 2026-08-30
**Chose:** `requires-python = ">=3.12,<3.13"`
**Considered:** 3.13, which was already installed locally.
**Why:** OpenTelemetry instrumentation packages typically lag new Python
releases. Observability is central to this project, so a missing wheel
partway through would cost a session for no benefit. 3.12 is mature and
everything I need supports it.
**Would reverse if:** the OTel packages I depend on publish 3.13 wheels
and I have a reason to move.

---

## 2. uv instead of pip and venv

**Date:** 2026-08-30
**Chose:** uv for dependency management and virtual environments.
**Considered:** pip with venv; conda (which I had installed).
**Why:** uv produces a lockfile, so the exact versions installed on my
laptop are the versions installed in the container and in CI. Without
that, "works on my machine" is a real risk in a project whose whole point
is reproducible deployment. It also replaces four tools with one.
**Would reverse if:** a dependency turned out to be unresolvable by uv,
or the team I join standardises on something else.

---

## 3. src-layout instead of a flat layout

**Date:** 2026-08-30
**Chose:** package at `src/rca_copilot/`.
**Considered:** package at the repository root.
**Why:** with src-layout there is nothing importable at the root, so
`import rca_copilot` only succeeds if the package was genuinely
installed. Tests therefore exercise the same import path the deployed
container uses. I hit this immediately: a wrong import failed in two
seconds rather than surviving until deployment.
**Would reverse if:** nothing I can foresee for this project.

---

## 4. Model split: cheap investigators, stronger adjudicator

**Date:** 2026-08-30
**Chose:** GPT-5.6 Luna ($0.20/$1.20 per million tokens) for both
investigator agents; Claude Sonnet 5 ($2/$10) for the adjudicator;
Claude Haiku 4.5 as fallback adjudicator.
**Considered:** Haiku as the primary adjudicator, saving roughly $1.50
per full evaluation sweep.
**Why:** the work is asymmetric. Investigators do extraction — read
logs, find the error cluster, report it with citations — and they carry
most of the input tokens, so cost savings land there. The adjudicator
does the hard part: weighing contradictory evidence, resisting plausible
but unsupported stories, and deciding when to escalate rather than
guess. My adversarial scenarios are entirely adjudicator tests. Putting
the cheapest model on the hardest task inverts the design for about the
price of a coffee.
**Would reverse if:** measurement shows Haiku scores equivalently on the
adversarial scenarios. I plan to test this rather than assume it.

---

## 5. AWS region ap-south-1

**Date:** 2026-08-30
**Chose:** ap-south-1 (Mumbai) for all resources.
**Considered:** other regions, chosen for service availability rather
than latency.
**Why:** lowest latency from where I am, and keeping everything in one
region avoids cross-region data transfer charges and IAM complexity.
**Would reverse if:** App Runner turns out not to be available in
ap-south-1. I will verify before the deployment phase; if it is not
available, I will use ECS Fargate, which is available everywhere and is
arguably the better thing to be able to discuss anyway.

---

## 6. Terraform for infrastructure as code

**Date:** 2026-08-30
**Chose:** Terraform.
**Considered:** AWS CDK, which would keep everything in Python and mean
no new syntax to learn.
**Why:** Terraform appears in job descriptions far more often than CDK
and transfers to any cloud rather than locking to AWS. Since this
project exists partly to close an interview gap, I chose the option that
closes more of it. The learning cost is small — HCL is configuration,
not programming, and this project needs roughly 150 lines of it.
**Would reverse if:** I found myself spending more than a session
fighting Terraform state rather than learning deployment.

---

## 7. LangGraph rather than hand-written orchestration

**Date:** 2026-08-31
**Chose:** LangGraph for agent orchestration.
**Considered:** plain `asyncio.gather` with three functions, which for
three nodes is roughly forty lines.
**Why:** I have used LangGraph before. My learning goals for this
project are deployment, evaluation and observability — not concurrency
patterns. Spending a session hand-rolling fan-out and fan-in would take
time from the things I actually set out to learn. For three nodes this
is a time decision, not a technical necessity, and I want to be able to
say that plainly.
**Watch for:** frameworks often produce traces that are a single opaque
span, or spans named after framework internals. I will instrument inside
the node functions rather than around the graph, and verify the parallel
fan-out is visible in Jaeger during the instrumentation session rather
than at the end.
**Would reverse if:** the framework's tracing proved unfixable, or the
graph grew complex enough that the abstraction cost more than it saved.

---

## 8. Sources return a status, not just data

**Date:** 2026-08-31
**Chose:** every source query returns one of SUCCESS, NO_DATA, or ERROR.
**Considered:** returning an empty list for both "found nothing" and
"could not query".
**Why:** these mean opposite things to the agent. NO_DATA is evidence —
the source was queried and there was genuinely nothing there. ERROR is
the absence of evidence — the agent is blind on that source and its
confidence should drop accordingly. Collapsing them means an agent can
produce a confident verdict on data it never actually saw. This matters
directly for the "no trigger" scenario, where an empty changelog is the
correct answer and must not be confused with a broken changelog.
**Would reverse if:** nothing. This is a correctness property.

---

## 9. Log queries take a time window, not a line count

**Date:** 2026-08-31
**Chose:** `query_logs(start_time, end_time, ...)`. No tail-style
line-count parameter.
**Considered:** a line count, mirroring `docker logs --tail`.
**Why:** I made this mistake by hand during the exploration sessions.
Tailing two services and comparing the output is comparing two different
moments and calling it correlation — it produced a confident wrong
diagnosis. Every source in this system is anchored to the same window so
that evidence from different sources is actually comparable.
**Would reverse if:** nothing. Confirmed by direct experience.

---

## 10. Results carry a truncation flag and a total count

**Date:** 2026-08-31
**Chose:** `LogQueryResult` includes `truncated: bool`, `count`, and an
explicit ordering (timestamp ascending).
**Considered:** returning a capped list with no indication it was
capped.
**Why:** if a query matches five thousand lines and returns one hundred,
an agent that doesn't know it was truncated will reason confidently over
a partial view. That is the same failure mode the evidence rule exists
to prevent, arriving through a different door. Explicit ordering matters
for the same reason — "the first hundred" and "the last hundred" are
different answers.
**Would reverse if:** nothing. This is a correctness property.

---

## 11. Add a trace source alongside logs and metrics

**Date:** 2026-08-31
**Chose:** a fourth source, `query_traces(start_time, end_time, service,
error_only)`, returning spans with parent-child links, duration and
status.
**Considered:** logs and metrics only, accepting that cascading-failure
scenarios would fail and reporting that honestly.
**Why:** logs describe, traces record. A log line saying "failed POST to
email service" is a sentence a developer wrote, and it can be wrong — I
hit exactly that twice. In one case a service claimed to call another
that had no record of the request; in another, an error named "redis"
while the container was called valkey-cart. A trace records that span A's
parent is span B, which is the call itself rather than a description of
it. My agents need to walk down a dependency chain, and without traces
the only way to find the next hop is to guess from error text that
demonstrably lies. When I diagnosed a three-service cascade by hand,
logs gave me three contradictory accounts and no answer; the trace gave
me the exact cause in about ninety seconds. The cost is one more source
with the same query shape over data that is already being collected.
**Would reverse if:** trace volume made snapshots impractically large,
in which case I would sample rather than drop the source entirely.

---

## 12. Metrics restricted to named queries

**Date:** 2026-08-31
**Chose:** `query_metrics(query_name, start_time, end_time)` where
`query_name` selects from a fixed set, rather than accepting arbitrary
PromQL.
**Considered:** letting the agent write its own PromQL.
**Why:** the backend exposes over two hundred metric names. An agent
cannot reliably guess the right one, and an agent writing its own query
language will invent metrics that do not exist and then reason about the
empty result. A fixed set makes the failure mode obvious — the query
either exists or it does not — and makes snapshots straightforward,
since I know in advance which series to capture.
**Would reverse if:** the fixed set proved too restrictive for a
scenario I care about, in which case I would add named queries rather
than open it up.

## 13. Defensive parsing for heterogeneous telemetry

**Date:** 2026-09-02

**Chose:** using defensive field access such as `.get()` and safe defaults when parsing telemetry documents where fields may be missing or inconsistently shaped.

**Considered:** assuming all telemetry documents have the same schema and directly accessing every field with `[]`.

**Why:** the system collects telemetry from thirteen services implemented across eight languages, and the emitted telemetry is not uniformly shaped. A single malformed document previously caused a `KeyError` and terminated the entire query. In an RCA system, one bad telemetry record should not cause the loss of all other evidence. Defensive parsing allows the source to continue processing valid records while handling missing fields safely.

**Would reverse if:** a field is proven to be mandatory by the source contract and missing it would make the record unsafe or misleading to use. In that case, the parser should explicitly reject or flag the record rather than silently defaulting it.

---

## 14. Distinguish ERROR from NO_DATA

**Date:** 2026-09-02

**Chose:** every observability source explicitly distinguishes `NO_DATA` from `ERROR` through the result `status` field.

**Considered:** returning an empty result for both cases.

**Why:** a wrong port or unavailable backend can produce zero results that look identical to a successful query where no matching evidence exists. During testing, a wrong port produced an apparent "no warnings" result until the status field exposed the connection failure. `NO_DATA` means the source was queried successfully but found no matching evidence. `ERROR` means the source could not be queried successfully or its response could not be trusted. This distinction prevents the RCA agent from treating unavailable evidence as negative evidence.

**Would reverse if:** the underlying source provided a reliable mechanism that made backend failure and genuine empty results unambiguously distinguishable without an explicit status field. Otherwise, the distinction remains part of the source contract.

## 15. Traces and Changelog

**Date:** 2026-09-04

**Chose:**
Traces → log analyst. Changelog → adjudicator.

**Considered:**

* Traces → log analyst
* Changelog → adjudicator
* Alternative: separate traces investigator, with logs, metrics, and traces each owned by a dedicated investigator

**Why:**

### Why traces go to the log analyst

Both logs and traces answer the same qualitative question: **what happened to this specific request, and what did it say?**

A trace span's `otel.status_description` is an error message, making it qualitative evidence similar to a log line.

More practically, in C1 and C4, the log analyst finds an error naming a component, while the trace confirms the call chain to that component. Keeping both with the same agent allows one investigator to correlate the evidence without an unnecessary handoff.

Metrics remain purely quantitative — numbers over time such as error rate, latency, CPU, and memory. This preserves a clean separation between qualitative and quantitative evidence.

### Why the changelog goes to the adjudicator

The changelog is not telemetry. It records what humans deliberately changed and therefore serves as **resolving evidence rather than an independent source of hypotheses**.

C2 illustrates this clearly. The log analyst may identify recommendation as problematic, while the metrics analyst identifies a cart process failure. The adjudicator then has conflicting hypotheses to resolve. A CONFIG change against cart at the exact incident time provides the evidence needed to determine which explanation is causal.

Giving the changelog to the adjudicator therefore prevents it from becoming a fourth opinion. Instead, it acts as a tiebreaker between investigator hypotheses.

### Consequence

The agents are not balanced by tool count. The log analyst has three tools, while the metrics analyst has one.

This is intentional. Balance is not the goal: the metrics tool exposes five named queries covering error rates, latency, and resource pressure, which provides sufficient quantitative evidence without requiring another agent.

### Alternative considered

A stricter architecture would use three investigators:

* Logs → log analyst
* Metrics → metrics analyst
* Traces → trace analyst

This better follows the single-owner rule from Session 3 and would provide an additional source of disagreement.

The cost is another agent, another prompt, another parallel branch, and roughly another share of the token budget. For four scenarios, the additional disagreement signal does not justify that complexity.

**Decision:** Keep traces with the log analyst and give the changelog exclusively to the adjudicator.

## 16. Tool Allocation

**Date:** 2026-09-04

**Chose:**

| Agent           | Tools                                            |
| --------------- | ------------------------------------------------ |
| Log analyst     | `search_logs`, `find_traces`, `get_trace_detail` |
| Metrics analyst | `get_metrics`                                    |
| Adjudicator     | `get_recent_changes`                             |

**Why:**

Traces are assigned to the log analyst because traces and logs provide complementary qualitative evidence about what happened to a specific request. Logs may identify the failing component through an error message, while traces can confirm the cross-service call chain and pinpoint where the failure occurred. Keeping both with the same investigator avoids an unnecessary handoff.

Metrics remain with a dedicated metrics analyst because they provide quantitative evidence: error rates, latency, CPU, memory, and other measurements over time.

The changelog is assigned exclusively to the adjudicator because it represents deliberate human changes rather than telemetry. It is therefore more useful as **resolving evidence** than as another independent source of hypotheses.

For example, in C2, investigators can produce conflicting explanations for the failure. The adjudicator can use a configuration change recorded at the incident time to determine which hypothesis is causally supported. If the changelog were given to an investigator, that investigator could incorporate the change into its own hypothesis, reducing its value as an independent resolving signal.

**Trade-off:**

This creates an intentionally unbalanced tool allocation. The log analyst has three tools, while the metrics analyst has one. This is acceptable because the metrics tool exposes multiple predefined queries covering error rate, latency, CPU, and memory.

**Alternative considered:**

A three-investigator architecture would assign logs, metrics, and traces to separate agents. This would provide cleaner single-source ownership and an additional disagreement signal.

However, it would also require another agent, another prompt, another execution branch, and additional token consumption. For the current four-scenario evaluation set, that additional complexity is not justified.

**Decision:** Use the two-investigator architecture with the adjudicator owning the changelog as resolving evidence.

## 17. Log and Metrics Investigators

**Date:** 2026-09-04

**Metric series are summarised**, not sent raw. First, last, min, max instead of 41 points per series. Cut a metrics run from 241k tokens to 17k. The model reasoning about whether something rose needs the shape, not the samples.

**The CPU threshold is stated as an absolute.** "Below 100 percent is normal" rather than "rising toward 100." The model twice read 80% as pressure and built a wrong hypothesis on it. Vague thresholds get interpreted generously.

**Negative findings are required, not permitted**. Changing "report them" to "you must report them, and do not propose a resource cause" was what produced the honest ruling-out.
