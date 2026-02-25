---
id: REQ-011
title: Glob Fallback Does Not Update state.cwd
type: bug
status: open
priority: low
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-011: Glob Fallback Does Not Update state.cwd

## Problem

In `session.py` → `_get_session_direct()`, when the direct path
(`claude_projects_path / encoded_cwd / session_id.jsonl`) does not exist,
the method falls back to a glob search:

```python
pattern = f"*/{session_id}.jsonl"
matches = list(config.claude_projects_path.glob(pattern))
if matches:
    file_path = matches[0]
```

The actual file path is found, but `state.cwd` is **not updated** to reflect
the real directory. On the next call to `resolve_session_for_window()`, the
same direct-path miss happens → glob search runs again → repeat forever.

This means every access to such a session incurs an unnecessary filesystem glob
over the entire `~/.claude/projects/` tree.

## Root Cause

`_get_session_direct` is a pure method; it does not mutate `WindowState`.
The caller (`resolve_session_for_window`) only clears state on `None` return,
not on successful-but-different-path resolution.

Key file: `src/ccbot/session.py`

## Success Criteria

1. When glob fallback finds a match, the real `cwd` is extracted from the path
   and `state.cwd` is updated + persisted
2. Subsequent calls use the direct path (no glob)
3. Existing session tests pass
4. Add test: glob fallback updates cwd for next call

## Implementation Notes

Extract the real cwd from `file_path.parent.name` (reverse the encoding:
`-data-code-ccbot` → `/data/code/ccbot`). Update `state.cwd` and call
`self._save_state()` in `resolve_session_for_window()` when `session is not None`
but the path differed from the expected direct path.

## Constraints

- Must handle the cwd decoding correctly (`-` → `/`, with leading slash)
- Should not break existing state persistence tests
