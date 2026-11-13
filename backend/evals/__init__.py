"""Eval harness package: golden cases and deterministic metrics.

There is deliberately no LLM judge here. One was built and measured on 2026-11-13:
19 cases scored by a separate model, compared with human labels, gave
Spearman ρ = 0.394 - against a 0.6 bar - with 17 of 19 scores landing on 3 or 4.
A judge that cannot tell a good trip from a mediocre one is worse than no judge,
because it produces a number that looks like evidence. The measurements that
remain are deterministic: they cost nothing and they answer a narrower question
honestly.
"""

from evals.metrics import CaseMetrics, composite_score, measure
from evals.runner import EvalCase, EvalResult, build_pipeline, load_cases, run_all, run_case

__all__ = [
    "CaseMetrics",
    "EvalCase",
    "EvalResult",
    "build_pipeline",
    "composite_score",
    "load_cases",
    "measure",
    "run_all",
    "run_case",
]
