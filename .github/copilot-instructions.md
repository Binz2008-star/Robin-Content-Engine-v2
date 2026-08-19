# Copilot Instructions

This repository is coordinated by a multi-agent control plane. `AGENTS.md`
at the repository root is canonical — read it before doing anything else.

## Before editing

1. Read `/AGENTS.md`.
2. Read `/AI_WORKSPACE/ACTIVE_TASKS.yaml`.
3. Identify your assigned task entry (by task ID or branch name).
4. Verify the current branch and base SHA match what the task declares.
5. Respect the task's `allowed_paths`; never touch its `forbidden_paths`.
6. If anything doesn't match — wrong branch, unexpected base SHA, a needed
   file outside `allowed_paths`, or the task isn't in the registry — stop
   instead of silently switching or widening scope.

## Reporting

Do not claim a task is complete, tests passed, or CI is green until you have
verified it directly (actual test/CI output), not assumed it. Report exact
results.

See `/AGENTS.md` for the full rule set, task states, and merge/deploy
authority model.
