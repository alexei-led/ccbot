---
id: REQ-020
title: Subagent Context Binding — Link Messages to Subagents
type: feature
status: open
priority: medium
inspired_by: slopus/happy sessionProtocol.ts (subagent field in envelope)
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-020: Subagent Context Binding

## Problem

CCBot already tracks subagents via `SubagentStart` / `SubagentStop` hook
events (see `hook_events.py → _active_subagents`). It knows:
- How many subagents are running (`get_subagent_count()`)
- Their `subagent_id`, `name`, `description`

But this data goes nowhere useful. In Telegram, all messages look identical
regardless of whether they're from the parent agent or a subagent. When
Claude spawns 3 parallel subagents, you see a flood of tool calls with no
indication of context: "who is doing what?"

Happy Coder solved this by tagging every message envelope with an optional
`subagent` field (cuid2 ID). CCBot can achieve the same effect without
changing the wire protocol — just at the rendering layer.

## What "Subagent Context" Means in CCBot

In Claude Code's JSONL, a subagent is launched via the `Task` tool:

```
tool_use  { tool_name: "Task", tool_use_id: "X", input: {description: "..."} }
...
tool_result { tool_use_id: "X", content: "..." }  ← subagent output
```

Between `SubagentStart` and `SubagentStop` hook events, all `Task` tool_use
and tool_result entries in the JSONL belong to that subagent.

## Success Criteria

### 1. Status message shows active subagent name

While a subagent is running, the Telegram status message includes the
subagent's name/description:

```
⚙️ subagent [api-refactor]: running tests…
```

vs current:
```
⚙️ running tests…
```

Multiple subagents:
```
⚙️ 3 subagents running: [api-refactor], [db-migration], [ui-tests]
```

### 2. Task tool_use rendered with subagent label

When a `tool_use` with `tool_name == "Task"` is rendered in Telegram,
prefix it with the active subagent context:

```
📎 Subagent [api-refactor]
  › Task: Refactor auth endpoints to use JWT
```

vs current (generic):
```
🔧 Task
  › Refactor auth endpoints to use JWT
```

### 3. Task tool_result rendered with subagent label

```
✅ Subagent [api-refactor] completed
  › Modified 4 files: auth.py, tokens.py…
```

vs current:
```
✅ Task result
  › Modified 4 files…
```

### 4. Failed subagent clearly marked

If SubagentStop fires before a matching tool_result (crash/timeout):
```
❌ Subagent [api-refactor] failed — no output returned
```

## Implementation Design

### Phase 1: Status context (easy, standalone)

`status_polling.py` already calls `get_subagent_count(window_id)`. Extend
to also call `get_subagent_info(window_id)` which returns a list of
`{name, description}` dicts. Interpolate into the status display label.

Changes: `hook_events.py` (expose info), `status_polling.py` (use it).

### Phase 2: Message binding (core)

**The binding problem**: link `SubagentStart` hook (has `subagent_id`,
`name`) to the JSONL `Task` tool_use (has `tool_use_id`).

**Approach — timestamp correlation**:
1. On `SubagentStart`, record `{subagent_id, name, description, started_at: monotonic()}`
   in `_active_subagents[window_id]` (already stored, just add `started_at`)
2. In `TranscriptParser` / `ClaudeProvider.parse_transcript_entries()`, when
   a `tool_use` with `tool_name == "Task"` is parsed, check `_active_subagents`
   for a subagent that started within ±3s of the entry's `timestamp` field
3. If match found: attach `subagent_name` to the resulting `AgentMessage`
   (new optional field: `AgentMessage.subagent_name: str | None = None`)
4. `response_builder.py` uses `subagent_name` to render the prefixed label

**Fallback**: if correlation fails (no timestamp match), render as generic
`Task` tool_use (no regression from current behavior).

### Phase 3: tool_result binding (follow-on)

Track `tool_use_id → subagent_name` mapping after Phase 2. When
`tool_result` with matching `tool_use_id` arrives, render with same label.

## Data Flow

```
SubagentStart hook event
    ↓
_active_subagents[window_id].append({subagent_id, name, started_at})
    ↓
TranscriptParser sees tool_use(tool_name="Task", timestamp=T)
    ↓
Correlate: find subagent where |started_at - T| < 3s
    ↓
AgentMessage(tool_name="Task", subagent_name="api-refactor")
    ↓
response_builder: render with "📎 Subagent [api-refactor]" prefix
```

## New Fields

```python
# providers/base.py — AgentMessage
@dataclass(frozen=True, slots=True)
class AgentMessage:
    ...
    subagent_name: str | None = None  # NEW
```

```python
# hook_events.py — richer subagent tracking
_active_subagents: dict[str, list[dict[str, Any]]] = {}
# each entry: {subagent_id, name, description, started_at: float}
```

## Constraints

- Phase 1 (status) is independent and can ship alone
- Phase 2 requires `timestamp` field in JSONL entries (Claude Code adds
  ISO timestamps to all entries — verify in real transcripts)
- Timestamp correlation is best-effort (±3s window) — no guarantee
- Must not change behavior for Codex/Gemini (no subagent hooks)
- `AgentMessage` is `frozen=True, slots=True` — adding `subagent_name`
  must be backward-compatible (default `None`)
- All existing tests must pass
