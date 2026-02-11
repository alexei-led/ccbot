---
id: REQ-003
title: Session Resume / Continue
status: todo
priority: medium
phase: 3
---

# REQ-003: Session Resume / Continue

Dead tmux windows can be recovered with Fresh, Continue, or Resume options.

## Success Criteria

1. When user sends a message in a topic bound to a dead window, recovery UI is shown
2. **Fresh**: new `claude` session in same cwd, rebinds topic
3. **Continue**: `claude --continue` in same cwd (most recent session), rebinds topic
4. **Resume picker**: lists recent sessions from `~/.claude/projects/` matching the cwd, user picks one, `claude --resume <id>`
5. `/resume` command works in any topic (even unbound), lists all recent sessions grouped by cwd
6. If `--continue` fails (no recent session), falls back to Fresh
7. If `--resume` fails (stale session), shows error and offers Fresh/Continue
8. If cwd no longer exists, shows directory browser

## Constraints

- Session metadata read from `~/.claude/projects/` session index files
- Recovery must forward the pending message after rebinding
