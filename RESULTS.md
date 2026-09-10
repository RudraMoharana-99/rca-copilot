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


| Scenario | Fault | Baseline | Multi-agent |
|---|---|---|---|
| C1 | valkey-cart stopped | **80%** | 40% |
| C2 | cart VALKEY_ADDR misconfigured | **100%** | 60% |
| C3 | product-catalog memory limit reduced | **80%** | 0% |
| C4 | astronomy-db stopped | **100%** | 80% |
| | **Overall** | **90%** (18/20) | **45%** (9/20) |

| | Baseline | Multi-agent |
|---|---|---|
| Top-1 accuracy | 90% | 45% |
| Mean wall clock | ~32s | ~82s |
| Mean cost per run | ~$0.06 | ~$0.15 |
| Mean stated confidence | 0.89 | 0.73 |

**The multi-agent architecture was worse on every scenario.** It is half
as accurate, two and a half times slower, twice as expensive, and less
well calibrated than the single agent it was built to improve on.

## Why the multi-agent system is worse

Splitting evidence gathering across specialists creates an information
bottleneck. The adjudicator never sees raw telemetry - only the
investigators' prose reports and one-line evidence summaries. Anything an
investigator fails to report is therefore invisible downstream, and a
component that no investigator nominates cannot be ranked at all.

C3 demonstrates this cleanly. The fault was a memory limit reduction on
product-catalog, which showed 107 percent CPU and 209 GB of block I/O
during the incident. That data is present in `container_cpu` and
`container_memory_ratio`, and the baseline reads it and names
product-catalog in 4 of 5 runs. The metrics analyst reads the same
metrics and reports checkout at 78-81 percent CPU instead, never
mentioning product-catalog. Across all five multi-agent runs,
product-catalog appears nowhere in any ranking - `rank_position` is null
every time.

The metrics analyst's prompt explicitly instructs it that CPU below 100
percent is normal load and that only sustained CPU at or above 100
percent indicates resource pressure. It does not follow this. The single
agent, given the same metrics without a specialist framing, does.

C1 shows the same bottleneck producing a different symptom. Three of the
four multi-agent failures ranked checkout first, citing memory at 99.5
percent and CPU at 78-81 percent - the same misreading. In two of those
runs valkey-cart was ranked second, so the correct answer was present but
outranked by the metrics analyst's story. The baseline, which has no
metrics analyst, reads cart's logs and answers correctly in 4 of 5 runs.

## Per scenario

### C1 - valkey-cart stopped

Baseline 4/5. Multi-agent 2/5.

Cart logs "Wasn't able to connect to redis" four times, which is
unambiguous. The multi-agent failures were mostly near misses: two ranked
valkey-cart second behind a checkout resource-exhaustion story, and one
did not mention it at all. Top-3 accuracy for multi-agent on this
scenario is 80 percent against a top-1 of 40 percent, so the right
component is usually found and wrongly ranked.

### C2 - cart configuration change

Baseline 5/5. Multi-agent 3/5.

Cart crash-looped and produced no logs, so the changelog entry recording
the VALKEY_ADDR change is the only evidence naming the cause. Both
multi-agent failures were `rank_position: null` - cart was not ranked at
all. This is a binary failure rather than a near miss: either the
adjudicator queries the changelog and finds the entry, or cart never
enters the ranking.

Reaching 3/5 required three fixes made after observing failures:
permitting an unfiltered changelog query, telling the adjudicator that
the window includes a lead-in period before the incident, and rejecting
malformed `submit_verdict` calls with an explicit instruction to
resubmit. Those changes are in the prompts used for all runs reported
here, but they were developed against this scenario.

### C3 - product-catalog memory exhaustion

Baseline 4/5. Multi-agent 0/5.

The widest gap in the table, and the clearest evidence of the
architectural problem. See "Why the multi-agent system is worse" above.

### C4 - astronomy-db stopped

Baseline 5/5. Multi-agent 4/5.

The narrowest gap. The correct component is named directly in
recommendation's error text - "lookup astronomy-db on 127.0.0.11:53: no
such host" - which both configurations can find by reading logs. There is
no competing resource-exhaustion story in the data for the metrics
analyst to promote, which is consistent with the pattern that multi-agent
fails when a plausible-but-wrong alternative is present rather than when
the correct answer is hard to find.

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