# Working Agreement (Solo Project)

This is a single-developer portfolio project. The agreements below replace
heavyweight Agile process while keeping the discipline of a closed feedback
loop. See [dev-test-loop spec § 13](docs/superpowers/specs/2026-04-29-dev-test-loop-design.md)
for the full rationale.

## 1. Feedback triggers

| Trigger | Outcome |
|---|---|
| PR job fails | PR is blocked from merging (no manual issue needed) |
| Nightly job fails | GitHub Actions auto-creates an issue with label `nightly-failure` |
| Cassette drift detected | Auto-issue with label `cassette-drift` |
| Eval regression > 5pp | Auto-issue with label `eval-regression` |

## 2. Response SLA (soft)

- Nightly issue: respond within 24h (acknowledge / fix / mark-deferred)
- Eval regression > 5pp: must be fixed (or thresholds adjusted with rationale)
  before any v0/v1 release

## 3. Fix commits must declare their layer

Every commit whose subject starts with `fix` (or `fix(scope):`) must include
this line in the body:

```
原因 layer: <impl|plan|spec>
```

| Layer | Meaning | What to do |
|---|---|---|
| `impl` | Implementation bug | Fix code; add a regression test |
| `plan` | Plan missed something | Change the plan doc first, then fix code |
| `spec` | Spec design is wrong | Run the full spec revision flow (brainstorming again), then update plan, then fix code |

This is enforced via [`scripts/check_commit_msg.py`](scripts/check_commit_msg.py)
called from a `commit-msg` pre-commit hook.

Non-fix commits (`feat`, `chore`, `docs`, `test`, `refactor`, …) are exempt.

## 4. Spec retrospective is required for "done"

When all tasks of a plan are merged to `main` and the plan's spec is fully
realized, append this section to the spec document:

```markdown
## Retrospective

**Implementation completion date**: YYYY-MM-DD

**Right designs (1-3 items)**:
- ...

**Wrong designs / what the plan missed (1-3 items)**:
- ...

**Things to avoid in the next spec (1-3 items)**:
- ...

**Lessons distilled into memory**:
- [memory file](path) — one-line hook
```

A spec without a retrospective is **not done**, and the project should not
move on to writing the next spec's plan until this is filled in.

Important lessons should be distilled into the project memory system at
`.claude/projects/-.../memory/` so that future Claude conversations
automatically inherit the learning.

## 5. Cost guardrails

- Nightly eval hard cost limit: ¥20 / run (LLMService aborts above this)
- Monthly nightly cost cap: ¥150 (manual tracking)
- PR jobs do **not** call real LLMs (mock + cassette only); fork PR safe.

## 6. Branch strategy

- Each plan implementation gets its own `feat/dev-test-loop-<X>` branch
- Plans land via PR (even self-merge) for portfolio history visibility
- Spec / plan documents may be committed directly to `main` ahead of branch
  cuts so they are reviewable independent of any in-progress branch
