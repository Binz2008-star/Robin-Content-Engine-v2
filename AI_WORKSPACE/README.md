# AI_WORKSPACE

This directory holds the live coordination state for multiple AI agents (and
humans) working in this repository in parallel. `AGENTS.md` at the repo root
is the canonical rule set; this directory is where that rule set gets its
data.

## Files

- **`ACTIVE_TASKS.yaml`** — the task registry. Every task an agent is
  executing must have an entry here: task ID, owner, branch, base SHA,
  allowed/forbidden paths, status, and merge/deploy authority. This answers
  the "ten questions" from `AGENTS.md` Section 1. Read it before editing
  anything.

- **`HANDOFF.md`** — an append-only log of handoff entries. Agents append a
  short, structured entry here before ending a significant unit of work, so
  the next agent (or human) can pick up context without re-deriving it.

## Updating `ACTIVE_TASKS.yaml`

- Only add or edit your own task entry unless a human directs otherwise.
- Never delete another agent's task entry to "clean up" — change its
  `status` instead (e.g. to `complete` or `cancelled`).
- Any SHA you write into this file must come from an actual `git
  rev-parse` / `git merge-base` you ran — never guessed or remembered.
- If a branch exists in the repository but has no task entry, it is not
  yet registered. Do not assume it is safe to ignore or safe to touch.

## Handling conflicts

If two tasks need the same file (i.e. their `allowed_paths` overlap), one
task must be set to `blocked` before the other agent edits that file. See
`AGENTS.md` Section 5 — there is no "last writer wins" in this repository.
