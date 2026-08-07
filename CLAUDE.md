# CLAUDE.md

`AGENTS.md` is the canonical source of truth for how work is coordinated in
this repository. Read it first, every time.

Before making any change:

1. Read `/AGENTS.md`.
2. Read `/AI_WORKSPACE/ACTIVE_TASKS.yaml` and find your task entry.
3. Verify actual repository state yourself (`git status`, current branch,
   HEAD SHA) — do not infer authority, task scope, or repository state from
   chat history alone.
4. Do not start, modify, or take over another agent's `active` task.
5. Stay within your task's `allowed_paths`; never touch its
   `forbidden_paths`.

Before ending a significant unit of work, record a handoff entry in
`AI_WORKSPACE/HANDOFF.md` using the format defined there.

See `AGENTS.md` for the full rule set — it is not duplicated here.
