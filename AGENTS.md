# Agent context use

Start with the acceptance condition and the smallest relevant document. Search paths and headings before reading bounded excerpts; exclude worktrees and generated output from broad searches unless targeted. Preserve full command logs and exit status when output is verbose, then show only the decisive lines and log path. Reuse source-bound evidence and expand verification only for an unanswered condition.

For a documentation-only change, verify the affected links, syntax and rendering. Do not run Rust workspace tests unless the change also affects product behavior or an explicit gate requires them.

For multi-phase work, keep one compact task-state note with acceptance checks, decisions and evidence pointers, verified results, and next action. Update it at milestones; after compaction, reload only the current phase's evidence.

Delegate substantial separable writing or editing in disjoint files, review, assessment, evaluation, task triage, progress checks, and investigation. Give each agent acceptance checks, file ownership, allowed side effects, minimal history, and a compact source-backed result. The parent coordinates shared edits and final synthesis; avoid duplicate or short dependent work.

At phase boundaries, check usage across project sessions with `python3 ../alopex-docs-internal/scripts/agent-usage-audit.py --workspace .. --hours 24` when local Codex records are available. Stop repeated calls or polls that produce no new decision or verified fact and reassess the acceptance condition.

The workspace procedure is in `../alopex-docs-internal/development/agent-context-efficiency.md`; read it for a large task or a context-use investigation.
