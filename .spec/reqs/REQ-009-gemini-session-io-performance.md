---
id: REQ-009
title: Gemini Session File Growing I/O Performance
type: bug
status: open
priority: medium
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-009: Gemini Session File Growing I/O Performance

## Problem

`GeminiProvider.read_transcript_file()` reads the **entire JSON file** on every
poll cycle (1–2 seconds). Unlike Claude and Codex providers which use incremental
byte-offset reads, Gemini parses the whole file as a JSON object each time.

As a Gemini session grows (long conversations with many tool calls), this
becomes a progressively worsening I/O and parse bottleneck:

- A 1 MB session file → ~500 µs parse per poll → ~250 MB read/s sustained I/O
- No caching, no mtime check before re-reading

## Root Cause

`ProviderCapabilities.supports_incremental_read = False` for Gemini — this is
intentional because Gemini uses whole-file JSON (not JSONL). However, the
current implementation skips even a simple mtime/size guard.

Key file: `src/ccbot/providers/gemini.py` → `read_transcript_file()`

## Success Criteria

1. Add `mtime` + `file_size` guard before re-parsing: skip if file unchanged
2. Cache last parsed messages list with a TTL or invalidation on size change
3. Benchmark: poll overhead on a 1 MB Gemini session file < 1 ms when unchanged
4. Existing Gemini tests continue to pass

## Implementation Notes

Simple approach: track `(mtime, size) → parsed_result` in a module-level dict
per file path. Invalidate on mtime or size change. This is a pure optimization,
zero behavior change.

## Constraints

- No behavior changes for Claude or Codex providers
- Guard should be thread-safe (asyncio context — single-threaded, so fine)
- Must not break `test_jsonl_providers.py` or `test_provider_contracts.py`
