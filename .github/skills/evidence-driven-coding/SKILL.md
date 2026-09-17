---
name: evidence-driven-coding
description: "Use when implementing, debugging, or reviewing code changes that need a grounded workflow: locate the controlling code path, form a falsifiable hypothesis, make the smallest focused edit, and validate behavior with a narrow check."
argument-hint: "Describe the bug, feature, failing check, or target file."
user-invocable: true
disable-model-invocation: false
---

# Evidence-Driven Python/Flask Coding

## Purpose

Produce focused, reviewable Python/Flask changes from concrete repository evidence. Keep the investigation local, expose assumptions, and leave the touched behavior executable and validated.

## When to Use

- Implementing a feature or bug fix in Python, Flask, pandas, or data-processing code
- Investigating a failing test, diagnostic, or runtime behavior
- Reviewing a change for regressions, missing tests, or risky assumptions
- Working in a codebase where the owning abstraction is not immediately obvious

## Procedure

1. Identify the strongest concrete anchor: target file, symbol, failing command, test, error, or call site.
2. Read only the nearby implementation and one relevant test or caller. If the anchor only forwards or registers behavior, follow one hop to the code that computes, mutates, or controls it.
3. State one falsifiable local hypothesis about the behavior or failure, plus the cheapest check that could disconfirm it.
4. Choose the smallest edit that tests the hypothesis. Preserve existing APIs, patterns, formatting, and unrelated worktree changes.
5. Before editing, tell the user which files or behavior will change and why.
6. Validate immediately after the first substantive edit. Prefer, in order:
   - the failing or behavior-scoped check;
   - a narrow test for the touched slice, using the repository's `unittest` or `pytest` convention;
   - `python -m py_compile <module.py>` for syntax-only changes or `python -c "import <module>"` for import-sensitive changes;
   - a narrow typecheck or lint check when configured;
   - a diff inspection only when no executable check is available.
7. If validation fails but supports the hypothesis, repair the same slice and rerun the same check. If it falsifies the hypothesis, follow one nearby hop to the more direct controller before editing again.
8. Add or update focused tests when the behavior is observable and the repository has a test convention. Do not repair unrelated failures.
9. Finish with an executable post-edit validation whenever the environment provides one. Report what changed, what was checked, and any remaining gap.

### Python/Flask Checks

- For analyzer or service logic, prefer one focused test file or test method before the full suite.
- For Flask routes or template rendering, use the existing application test context/client and assert observable status, content, or redirect behavior.
- For pandas transformations, test column names, empty input, representative values, and types at the boundary where the transformation is consumed.
- For imports, run the narrow import check before broader tests so optional dependencies and initialization side effects are exposed early.

## Decision Rules

- Prefer an existing helper, service, parser, or test pattern over a new abstraction.
- Keep data normalization at the existing schema or adapter boundary; do not spread column aliases through downstream analyzers.
- Do not broaden the search after a sufficient local hypothesis and discriminating check exist.
- If evidence is incomplete, make a small reversible probe or ask one precise question; do not guess across multiple architectural boundaries.
- Treat unrelated dirty files as user work. Never reset, checkout, or overwrite them.
- Keep comments rare and explanatory; do not narrate obvious code.
- Scale test coverage with risk: narrow tests for local changes, broader checks for shared contracts or user-facing workflows.

## Completion Criteria

- The controlling code path is identified.
- The change is minimal and consistent with local conventions.
- The relevant focused check passes, or its blocker is explicitly reported.
- New behavior has a regression test when practical.
- The final report names changed files, validation performed, and residual risks or unrelated failures.
