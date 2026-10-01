# Snapshot additions (budgie-2vh)

Spec: perch `docs/superpowers/specs/2026-10-01-{quarterly-report,budget-cut}-design.md`, "The Budgie addition".

1. `Snapshot.budget_revisions` / `Snapshot.plan` (defaulted fields), filled by `load_snapshot` from the budget source and plan.csv it already resolves. Tests: present/absent for both (`budgie/tests/test_project.py`).
2. `Snapshot.what_if(budget, plan_entries)` in `budgie/core/project.py`: budget -> `Budget.flat`, `budget_revisions` None; entries appended to the plan, allocations (or `planned`) recomputed through `AllocationPlan`. Tests: budget only, leave entry (126 working days x 7.968 h = 1,003.968 h off a 1,992 h year), append to existing plan + new person, plan-only snapshot, original untouched.
3. Document in `budgie/core/CLAUDE.md`; run perch's `test_contract.py` against this worktree.
