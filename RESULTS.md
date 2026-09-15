# Results

## Configuration

| | |
|---|---|
| Model | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) for all agents |
| Runs per scenario | 5 per configuration |
| Total runs | 40 |
| Data | Captured snapshots, replayed offline |
| Alert | Generic: "elevated error rate detected", no service named |
| Date | 2026-09-07 |

Both configurations use the same model, the same tools, the same source
data and the same scoring rule. The only difference is the architecture.

## Configurations

**Baseline** — one agent with all five tools in a plain loop. Sequential
by design, so that parallelism remains a variable rather than a constant.

**Multi-agent** — a log analyst (logs, trace summaries, trace detail) and
a metrics analyst (metrics) investigating concurrently, each with its own
context window and prompt, followed by an adjudicator holding the
changelog which reconciles their reports into a ranked verdict. Wired
with LangGraph: fan-out from START to both investigators, fan-in to the
adjudicator.

## Scoring

Each scenario declares an `expected_component` in its `scenario.yaml`,
written at capture time before any model output was seen. A run is
correct if that component appears in the **top-ranked cause**. Where it
appears lower in the ranking, the position is recorded.

Component names are compared case-insensitively with hyphens and
underscores normalised to spaces, so `valkey-cart` matches "Valkey cart".

Exact component matching was chosen over an LLM judge because it is
deterministic and any reader can audit a score by reading the stored
verdict text. Using a non-deterministic scorer to measure a
non-deterministic system compounds the problem being measured.

## Headline

| Scenario | Config | Valid runs | Correct | Accuracy | Mean conf | Mean latency | Mean cost |
|---|---|---:|---:|---:|---:|---:|---:|
| C1 valkey-cart stopped | baseline | 13 | 8 | **61.5%** | 0.90 | 27.8s | $0.088 |
| C1 valkey-cart stopped | multi-agent | 6 | 3 | 50.0% | 0.73 | 76.5s | $0.202 |
| C2 cart misconfigured | baseline | 5 | 5 | **100%** | 0.94 | 26.1s | $0.036 |
| C2 cart misconfigured | multi-agent | 5 | 3 | 60.0% | 0.81 | 89.6s | $0.120 |
| C3 product-catalog OOM | baseline | 5 | 4 | **80.0%** | 0.79 | 48.4s | $0.068 |
| C3 product-catalog OOM | multi-agent | 5 | 0 | 0.0% | 0.72 | 76.5s | $0.106 |
| C4 astronomy-db stopped | baseline | 5 | 5 | **100%** | 0.92 | 27.0s | $0.042 |
| C4 astronomy-db stopped | multi-agent | 5 | 4 | 80.0% | 0.65 | 85.9s | $0.117 |

**Overall: baseline 22/28 (79%), multi-agent 10/21 (48%).**

The baseline is more accurate on every scenario, at roughly a third of the
latency and half the cost. The clearest within-scenario comparison is C2,
where identical data produced 100 percent accuracy from the single agent
and 60 percent from the multi-agent pipeline, at 3.3 times the cost and
3.4 times the latency.

Runs that errored before reaching the API - eight on C1 baseline, from
harness and instrumentation development - are excluded from these figures
and counted separately. C1 has more valid runs than the other scenarios
because it was used throughout development; all of them are completions of
the same pipeline against the same snapshot. The other three scenarios
were each run once at n = 5 per configuration.


## Failure taxonomy

Every stored run was classified from its record. A run is `correct` if the
expected component was ranked first, `outranked` if it appeared lower in
the ranking, `absent` if it appeared nowhere, `no_verdict` if nothing was
submitted, and `error` if the run crashed before completing.

| Scenario | Config | Correct | Outranked | Absent | No verdict | Error |
|---|---|---:|---:|---:|---:|---:|
| C1 | baseline | 8 | 0 | 5 | 0 | 8 |
| C1 | multi-agent | 3 | 2 | 1 | 0 | 0 |
| C2 | baseline | 5 | 0 | 0 | 0 | 0 |
| C2 | multi-agent | 3 | 0 | 1 | 1 | 0 |
| C3 | baseline | 4 | 0 | 1 | 0 | 0 |
| C3 | multi-agent | 0 | 0 | 4 | 1 | 0 |
| C4 | baseline | 5 | 0 | 0 | 0 | 0 |
| C4 | multi-agent | 4 | 0 | 1 | 0 | 0 |

Two observations.

**The baseline never fails halfway.** It has no `outranked` and no
`no_verdict` results: it either names the right component first or names
something else entirely. The multi-agent pipeline produces both
intermediate states - twice ranking the correct component second, and twice
failing to submit a verdict at all.

**C3 is a total miss for the multi-agent pipeline.** product-catalog does
not appear in any ranking across five runs, while the baseline names it
first in four of five. This is the clearest evidence for the information
bottleneck described above.

### What gets blamed instead

For every failure where a component was named, the top-ranked cause was
matched against the known service list.

| Blamed component | baseline | multi-agent | total |
|---|---:|---:|---:|
| checkout | 6 | 5 | **11** |
| astronomy-db | 0 | 2 | 2 |
| cart | 0 | 1 | 1 |
| recommendation | 0 | 1 | 1 |

**Eleven of fourteen attributable failures blame checkout**, and checkout is
never the fault in any scenario. It is a bystander that showed 78-81
percent CPU and memory peaking at 99.5 percent during the incident windows.

The bias appears in both configurations at similar rates - six baseline
failures and five multi-agent. **It is therefore a property of how the model
reads resource metrics, not of the architecture.** Both prompts state that
CPU below 100 percent is normal operating load and that memory above 90
percent is not by itself significant; the instruction is followed
inconsistently.

The two astronomy-db attributions are a different mechanism: both occurred
on C3, where the recommendation service logged DNS errors naming
astronomy-db from an unrelated background fault, and the pipeline built a
diagnosis on them.


## Calibration

Stated confidence does not track correctness in either configuration.

| Scenario | Multi-agent accuracy | Mean confidence |
|---|---|---|
| C3 | 0% | 0.72 |
| C1 | 40% | 0.74 |
| C2 | 60% | 0.81 |
| C4 | 80% | 0.65 |

The multi-agent system was most confident on C2, where it scored 60
percent, and least confident on C4, where it scored 80 percent. The
relationship is inverted.

The baseline is better calibrated but still overconfident: 0.89 mean
confidence against 90 percent accuracy overall, but 0.94 on C2 and 0.79
on C3 where its accuracy was 100 and 80 percent respectively.

In individual runs the same confidence value appears on correct and
incorrect answers. One C1 multi-agent run ranked checkout first at 0.80;
another ranked valkey-cart first at 0.80. Confidence cannot be used to
decide whether to trust an answer.

## Observations

**The broken service is usually silent.** In three of four scenarios the
failing component produced no error logs, while a healthy downstream
service produced all the visible errors. A "find the service with the
most errors" heuristic lands on a healthy service every time.

**Failures divide by shape.** `rank_position: 2` means the right
component was found and outranked - a reasoning failure. `rank_position:
null` means it was never named - a search or reporting failure. C1
produced the first kind, C2 and C3 the second. They need different fixes.

**Prompt instructions are not reliably followed.** The metrics analyst
prompt states an absolute CPU threshold and the model applies it
inconsistently, in both directions. It has correctly ruled out resource
exhaustion in some runs and promoted an 80 percent CPU reading as
evidence of it in others, on identical data.

**Parallelism helps wall clock less than expected.** The trace confirms
the two investigators do run concurrently, both starting at trace time
zero. But because the branches are unbalanced, fan-out saves only about
22 percent of elapsed time, and the run is still more than twice as slow
as the baseline.

**Prompt caching engaged inconsistently.** Cache reads were zero on the
early multi-agent runs and on the C1 baseline sweep, then substantial on
later sweeps, using identical code. Where it engaged, cost per
multi-agent run fell from about $0.22 to $0.12.

**Instrumentation found a bug on its first run.** Tool result summaries
were built from the result count without checking status, so a source
that failed reported "no changes recorded" - text that contradicts the
ERROR status beside it and that the prompts explicitly treat as
meaningful evidence of absence. The span attribute was correct while the
text the model reads was not.

**The dominant failure is a misread resource metric, not the architecture.**
checkout accounts for eleven of fourteen attributable failures across both
configurations. Choosing a different agent topology does not address it;
the model reads a busy-but-healthy container as a failing one regardless of
how the evidence reaches it.


## Limitations

- **n = 5.** Enough to establish that variance is large and that the gap
  between configurations is consistent in direction, not enough for
  narrow confidence intervals. The intended sweep was n = 20; the reduced
  figure was forced by API cost.
- **Four scenarios**, all captured from one demo application by the
  author, who knew the answers in advance.
- **One model.** Haiku 4.5 was used throughout for cost reasons. A
  stronger model may close or reverse the gap, and the multi-agent
  design's failure mode - a specialist not following its prompt - is
  plausibly model-dependent.
- **The multi-agent prompts were iterated against C2 after seeing it
  fail.** The baseline prompts were not tuned against any scenario. This
  should favour the multi-agent configuration, and does not.
- **Scoring is exact component matching.** A verdict that describes the
  right failure without naming the component scores as wrong.

## What this would take to fix

The bottleneck is that the adjudicator sees prose summaries rather than
data. Two changes would test that directly: give the adjudicator the
metric values themselves rather than a one-line count, and require
investigators to report the top three values for each metric they query
rather than a narrative conclusion.

Neither is implemented here. The result as it stands is that the simpler
architecture is better on this task, at this model size, with these
prompts.

## Operational overhead, from traces

Both configurations are instrumented with OpenTelemetry: one trace per
incident, a span per agent, a span per tool call. This gives a second,
independent view of the multi-agent overhead alongside the accuracy
numbers.

A representative multi-agent run on C1:

| Span | Duration | Turns | Evidence | Input tokens |
|---|---|---|---|---|
| log analyst | 27.4s | 12 | 24 | 9,130 |
| metrics analyst | 20.6s | 3 | 5 | 2,098 |
| adjudicator | 45.9s | 4 | - | - |
| **Total** | **~73s** | | | |

Three things are visible in the trace that the accuracy numbers alone do
not show.

**The branches are unbalanced.** The log analyst runs four times as many
turns as the metrics analyst and gathers roughly five times the evidence.
Fan-out therefore saves only the shorter branch: about 21 seconds of a 73
second run, or 22 percent, rather than the 50 percent that two balanced
branches would give.

**The adjudicator is the dominant cost.** At 45.9 seconds it takes longer
than both investigators ran for, and longer than an entire baseline run,
which completes in around 28 seconds. The reconciliation step is where
most of the wall clock goes.

**The imbalance compounds the information bottleneck.** The log analyst
compresses 24 pieces of evidence into a single prose report; the metrics
analyst compresses 5. The adjudicator receives two reports of apparently
equal weight, one of which summarises four times as much investigation.
Anything the log analyst chose not to state in prose is unavailable
downstream, and there was substantially more for it to omit.

The result is that the reconciliation step is simultaneously the largest
cost in the run and the point at which evidence is lost.