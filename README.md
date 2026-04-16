# Codex Skill Evolution

中文说明见 [README.zh-CN.md](README.zh-CN.md)

Proposal-gated skill evolution for Codex: detect skill use, require a retrospective, generate reviewable proposals, and only write changes back after explicit approval.

## Why This Exists

Codex skills tend to drift in two ways:

- a skill gets used in a real task and the instructions turn out to be incomplete
- the missing learning is obvious in retrospect, but there is no safe path to capture it

This project adds that safe path. It turns "we should remember this next time" into an explicit workflow:

- detect skill usage
- require a retrospective before finishing
- convert reusable learnings into proposals
- review proposals before they touch any durable rules

## What It Does

- Detects likely skill use from hook events.
- Marks the current session as requiring a retrospective before completion.
- Stores learnings and proposals in a review queue.
- Applies changes only after explicit approval.
- Supports rollback for both appended proposal blocks and newly created artifacts.

## What a Real Session Looks Like

Example:

1. A Codex session uses a skill such as `find-skills`.
2. During the task, the operator discovers a reusable missing rule, for example:
   "when a repo keeps `SKILL.md` at the repository root, installation needs `--path . --name <skill-name>`."
3. The hook marks the session as needing a retrospective.
4. At the end of the task, the operator either:
   - records `no_reusable_learning`, or
   - runs `record` and creates a proposal
5. The proposal stays in `proposed` until a human explicitly approves it.
6. Only then can it be applied back to a skill file or `AGENTS.md`.
7. If the change turns out to be wrong, it can be rolled back.

This is intentionally narrower and safer than auto-editing prompts from conversation history.

## What It Does Not Do

- It does not auto-edit `SKILL.md`.
- It does not auto-edit `AGENTS.md`.
- It does not auto-approve proposals.
- It is not a general-purpose memory or reflection platform.

## Core Workflow

```text
skill used
-> retrospective required
-> learning recorded
-> proposal created
-> human review
-> approve or reject
-> apply
-> rollback if needed
```

## Current Source Layout

This workspace snapshot keeps the implementation under `.codex/`:

- Workflow CLI: `.codex/scripts/skill_evolution.py`
- Hook detector: `.codex/plugins/skill-evolution-hooks/scripts/posttooluse_skill_tracker.py`
- Hook wiring: `.codex/plugins/skill-evolution-hooks/hooks.json`
- Plugin metadata: `.codex/plugins/skill-evolution-hooks/.codex-plugin/plugin.json`
- Public smoke check: `scripts/check_skill_evolution_smoke.py`

Runtime artifacts are intentionally separate from source and should not be committed:

- `.codex/skill-learnings/`
- `.codex/skill-proposals/`
- `.codex/skill-backups/`
- `.codex/skill-evolution-state/`
- `.codex/skill-change-log.jsonl`

## Installation Notes

This project currently assumes a Codex-compatible environment that can:

- run Python 3.12+
- execute hook scripts
- provide an active `CODEX_HOME`

In this workspace layout, the minimal pieces are:

1. Place `skill_evolution.py` under the active runtime's `scripts/` directory.
2. Place `posttooluse_skill_tracker.py` under the active runtime's plugin `scripts/` directory.
3. Install `hooks.json` and the plugin manifest in the same plugin tree.
4. Verify the setup with:

```bash
python3 scripts/check_skill_evolution_smoke.py --json
```

## Everyday Commands

Record "no reusable learning":

```bash
python3 .codex/scripts/skill_evolution.py mark-retrospective --outcome no_reusable_learning
```

Record a learning and create a proposal:

```bash
python3 .codex/scripts/skill_evolution.py record \
  --skill-name <skill-name> \
  --skill-path <path-to-skill-md> \
  --trigger-scenario "<what happened>" \
  --problem "<what went wrong>" \
  --problem-kind workflow-improvement \
  --reusable-rationale "<why this is reusable>" \
  --proposed-text "<suggested update text>" \
  --risk "<risk summary>"
```

Review pending proposals:

```bash
python3 .codex/scripts/skill_evolution.py review --status proposed
```

Approve a proposal:

```bash
python3 .codex/scripts/skill_evolution.py approve --proposal-id <proposal-id>
```

Apply an approved proposal:

```bash
python3 .codex/scripts/skill_evolution.py apply --proposal-id <proposal-id>
```

Rollback an applied proposal:

```bash
python3 .codex/scripts/skill_evolution.py rollback --proposal-id <proposal-id>
```

## Safety Model

- Proposals are review-first. They start as `proposed`.
- Unapproved proposals cannot be applied.
- Workflow improvements for system skills are routed away from `.system`.
- Appended proposal rollbacks are marker-aware and remove only the inserted block when possible.
- If a marker-aware rollback cannot be completed, backup-based restoration remains available.

## Current Capabilities

The current implementation already supports:

- local skills under `.codex/skills/`
- user-installed skills under `.agents/skills/`
- symlinked skills, for example `.codex/skills/foo -> .agents/skills/foo`
- hook-driven skill-use detection
- proposal creation from explicit retrospectives
- approval-gated apply
- rollback for appended proposal blocks and created artifacts
- a public smoke check for verifying core workflow liveness

## Current Limitations

This is not yet a full Codex equivalent of `claude-reflect`.

Missing or intentionally out of scope for the current version:

- general correction capture outside skill use
- history-wide reflection scans
- automatic new-skill discovery
- richer confidence / dedupe / semantic clustering layers
- fully standalone packaging outside the current `.codex/`-shaped workspace snapshot

## Verification

Run the public smoke check:

```bash
python3 scripts/check_skill_evolution_smoke.py
python3 scripts/check_skill_evolution_smoke.py --json
```

Current automated tests:

```bash
python3 -m unittest tests.test_skill_evolution_paths -v
python3 -m unittest tests.test_skill_evolution_cli -v
python3 -m unittest tests.test_skill_evolution_runtime -v
python3 -m unittest tests.test_skill_evolution_smoke -v
python3 - <<'PY'
import unittest
import tests.test_posttooluse_skill_tracker as t
suite = unittest.defaultTestLoader.loadTestsFromModule(t)
unittest.TextTestRunner(verbosity=2).run(suite)
PY
```

## Scope and Roadmap

Current scope:

- skill-use detection
- retrospective gating
- proposal queue
- approval-gated apply
- rollback
- public smoke verification

Future scope:

- richer reflection capture beyond skill use
- session-history backfill
- candidate new-skill suggestions
- cleaner standalone repository packaging
