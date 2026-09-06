# Results

## Configuration

| | |
|---|---|
| Model | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) |
| Runs per scenario | 1 |
| Data | Captured snapshots, replayed offline |
| Alert | Generic: "elevated error rate detected", no service named |
| Date | 2026-09-03 |

**These are single runs and should be read as indicative only.** See
Limitations below.

## Configurations compared

**Baseline** — one agent with all five tools, a plain loop, no
orchestration. Sequential by design so that parallelism remains a
variable rather than a constant.

**Multi-agent** — a log analyst (logs, trace summaries, trace detail)
and a metrics analyst (metrics) investigating independently, each with
its own context window, followed by an adjudicator holding the
changelog which reconciles their reports into a ranked verdict.

## Scoring

An answer is correct if it names the component identified in the
scenario's `correct_answer` field as the top-ranked cause. Criteria are
written into each `scenario.yaml` at capture time, before any model
output was seen.

## Comparison

| Scenario | Fault | Baseline | Multi-agent |
|---|---|---|---|
| C1 | valkey-cart stopped | correct | correct |
| C2 | cart VALKEY_ADDR misconfigured | correct | correct |
| C3 | product-catalog memory limit reduced | wrong | wrong |
| C4 | astronomy-db stopped | wrong | wrong |
| | | **2/4** | **2/4** |

Cost per run: roughly 40k tokens for the baseline, 150k–285k for
multi-agent. The multi-agent configuration costs four to seven times
more for the same accuracy on this sample.

## Per scenario

### C1 — valkey-cart stopped

Both configurations correct. Cart logs four "Wasn't able to connect to
redis" entries, which is unambiguous. The multi-agent adjudicator
additionally overruled its metrics analyst, which had proposed checkout
degradation at 0.85 confidence, on the grounds that multiple unrelated
services showed identical error counts and therefore pointed to a shared
dependency rather than an isolated failure.

### C2 — cart configuration change

The baseline was correct on the first attempt. The multi-agent
configuration failed twice before three targeted changes fixed it:

1. The adjudicator queried the changelog only for services its analysts
   had nominated. Neither nominated cart, because cart crash-looped and
   produced no logs, so the decisive CONFIG entry was never fetched.
   Fixed by allowing an unfiltered changelog query.
2. Once found, the adjudicator dismissed the change because it fell five
   minutes into the incident window, treating that as "after the alert".
   The window deliberately includes a lead-in period. Fixed by stating
   the window's shape in the prompt.
3. A malformed `submit_verdict` call lost an entire run. The model then
   summarised its verdict in prose and stopped, believing it had
   succeeded. Fixed by rejecting malformed submissions with a specific
   error and appending an explicit instruction to resubmit.

**These fixes were made after seeing the failure**, which is fitting to
the test set. The C2 result should be read accordingly.

### C3 — product-catalog memory exhaustion

Both configurations wrong. Neither named product-catalog.

The metrics analyst had the evidence — product-catalog was at 107 percent
CPU with 209 GB of block I/O — and did not report it, proposing checkout
and frontend instead. The log analyst read recommendation's 57 error
entries, which name astronomy-db, and built a DNS-failure hypothesis on
an unrelated background fault.

This is the scenario where the failing service is silent and the loudest
service is healthy, and both configurations fell for it.

### C4 — astronomy-db stopped

Both configurations wrong on the recorded run.

The multi-agent configuration answered C4 **correctly on an earlier
run**, ranking astronomy-db first and escalating with an actionable
reason. On the recorded run with the same code and the same data it
ranked checkout first at 0.70 confidence instead.

Its dissent argued that checkout's error rate of 10.83 percent exceeding
frontend's 2.92 percent meant checkout must be upstream — "a downstream
service's error rate should not exceed the cause". That rule was
invented; error rate magnitude does not order causality. A service that
fails fast can show a higher rate than the dependency that caused it.

**This is the most important observation in this table.** Identical
inputs produced opposite verdicts on consecutive runs.

## Observations

**The broken service is usually silent.** In three of four scenarios the
failing component produced no error logs, while a healthy downstream
service produced all the visible errors. A "find the service with the
most errors" heuristic lands on a healthy service every time.

**Confidence does not track correctness.** The baseline reported 0.95 on
two wrong answers. Investigators regularly report 0.85 to 0.95 on
hypotheses the adjudicator later demotes on evidential grounds.

**The adjudicator's demotions were sound.** Where it overruled a
high-confidence investigator, its stated reasons were correct: evidence
resting on absence rather than presence, dependency direction, and
prose confidence exceeding what the cited evidence supports.

**Context is a hard limit on single-agent search.** The baseline
exceeded the 200k token limit on C4 and could not complete the run until
tool results were truncated. Multi-agent avoids this by giving each
investigator its own context, though at four to seven times the cost.

**Failures divide into two kinds.** C3 is a reasoning failure — the
evidence was gathered and misread. C4 is a search failure — the right
services were reached inconsistently. They need different fixes.

## Limitations

- **n = 1.** C4 produced opposite verdicts on two runs of identical
  code against identical data. Nothing in this table should be treated
  as stable.
- **Four scenarios**, all captured from a single demo application, all
  by the same author who knew the answers in advance.
- **One model.** Haiku 4.5 was used for cost reasons during development.
  A stronger model may behave differently.
- **Prompt changes were made between runs**, so the configurations are
  not identical across the four rows.

Repeated evaluation at n = 20 per scenario, with the prompts frozen, is
the next step. These numbers exist to be replaced.