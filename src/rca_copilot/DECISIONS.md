# Decisions

Engineering decisions made during this project, with alternatives considered.

---

## 1. Pin Python to 3.12, excluding 3.13+

**Date:** 2026-08-30
**Chose:** `requires-python = ">=3.12,<3.13"`
**Considered:** 3.13, already installed locally.
**Why:** OpenTelemetry instrumentation packages typically lag new Python
releases. Since observability is central to this project, a missing wheel in
session 13 would cost a session for no benefit.
**Would reverse if:** the OTel packages I need publish 3.13 wheels.

---

## 2. uv instead of pip + venv

**Date:** 2026-08-30
**Chose:** uv for dependency management and virtual environments.
**Considered:** pip with venv; conda.
**Why:** uv is much faster than pip and conda
**Would reverse if:** It dependes 

---

## 3. src-layout instead of flat layout

**Date:** 2026-08-30
**Chose:** package at `src/rca_copilot/`.
**Considered:** package at repo root.
**Why:** <yours — you hit the concrete reason today when the import failed>
**Would reverse if:** <yours>

---

## 4. Model split: Luna investigators, Sonnet 5 adjudicator

**Date:** 2026-08-30
**Chose:** GPT-5.6 Luna ($0.20/$1.20) for the two investigators;
Claude Sonnet 5 ($2/$10) for the adjudicator; Haiku 4.5 as fallback adjudicator.
**Considered:** Haiku 4.5 as primary adjudicator, saving ~$1.50 per sweep.
**Why:** <yours>
**Would reverse if:** <yours — note you plan to measure this>

---

## 5. AWS region ap-south-1

**Date:** 2026-08-30
**Chose:** ap-south-1 (Mumbai) for all resources.
**Considered:** other regions; App Runner availability unverified.
**Why:** <yours>
**Would reverse if:** <yours>

---

## 6. Terraform for infrastructure as code

**Date:** 2026-08-30
**Chose:** Terraform.
**Considered:** AWS CDK, which would keep everything in Python.
**Why:** <yours>
**Would reverse if:** <yours>