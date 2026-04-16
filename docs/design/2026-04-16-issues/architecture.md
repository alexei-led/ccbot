# Architecture Overview — Two Significant Issues Design

**Date**: 2026-04-16  
**Scope**: Targeted design for the two Significant issues identified in the initial 2026-04-16 modularity review.

---

## Functional Requirements Summary

The 2026-04-16 review identified two Significant coupling issues in a codebase that
had otherwise improved from 4.8 to a claimed 6.3/10 across four refactoring passes.
This design addresses the gap left by that series:

1. **SessionManager Low Cohesion** — 39-method facade over five sub-objects;
   17+ handler modules import it as a one-stop shop. The v2-v5 series addressed
   this substantially (30→15 importers, 89→57 call sites) via `window_query.py` and
   `session_query.py` extractions. The natural floor has been reached for the
   current architecture.

2. **Provider Abstraction Leaks** — Five shell handler files bypass the
   `AgentProvider` protocol by importing from `providers.shell` / `providers.shell_infra`.
   The Claude-specific leak (`capabilities.name == "claude"` in `transcript_reader`)
   was fixed in the series. The shell leaks were never touched in any of the four
   passes.

---

## Module Map

| Module                                  | Role                                                                             | Change     |
| --------------------------------------- | -------------------------------------------------------------------------------- | ---------- |
| `providers/base.py` (`AgentProvider`)   | Protocol contract — extended with prompt marker methods                          | +2 methods |
| `providers/shell.py` (`ShellProvider`)  | Implements the two new protocol methods                                          | Modified   |
| `handlers/shell/` (new sub-package)     | Formalizes shell handler subsystem with declared dependency on `providers.shell` | New        |
| `handlers/shell_prompt_orchestrator.py` | Drops `providers.shell_infra` imports; routes through protocol                   | Modified   |
| `handlers/directory_callbacks.py`       | Replaces `KNOWN_SHELLS` import with `detect_provider_from_command()`             | Modified   |

---

## How the Modules Work Together

### Flow 1: Shell Window Created — Prompt Marker Setup

```
directory_callbacks
  detect_provider_from_command(cmd)        ← providers/__init__.py (no KNOWN_SHELLS import)
  → "shell" detected
  → window created, provider_name="shell"
  → ensure_setup(window_id)               ← shell_prompt_orchestrator entry point

shell_prompt_orchestrator
  get_provider_for_window(window_id)      ← resolves ShellProvider
  provider.ensure_prompt_marker(window_id)← AgentProvider protocol
  → ShellProvider.ensure_prompt_marker
      capture pane
      prompt_marker_present(capture)?
        No → setup_shell_prompt(window_id) ← implementation detail, stays in shell_infra
```

No handler touches `providers.shell_infra` directly. All prompt-marker
coordination flows through the `AgentProvider` protocol.

### Flow 2: Shell Output Capture — Prompt Marker Detection

```
window_tick (passive poll cycle)
  → is_shell_idle(capture)               ← handlers/shell/__init__.py (public API)
    → match_prompt(line)                  ← providers.shell re-export (within subsystem)
  → extract_output(capture, ...)          ← handlers/shell/__init__.py
    → match_prompt(line)                  ← declared subsystem dependency

Subsystem boundary: match_prompt stays in providers.shell_infra (correct location);
shell handlers access it as a declared package dependency, not a scattered file-level leak.
```

### Flow 3: Non-Shell Provider — Protocol No-Op

```
Any provider switch to Claude/Codex/Gemini:
  ensure_setup(window_id) called by orchestrator
  → get_provider_for_window → ClaudeProvider
  → provider.ensure_prompt_marker(window_id)
    → base.py default: async no-op, returns immediately
  → provider.prompt_marker_present(capture)
    → base.py default: returns True
```

Generic code never branches on provider identity. Protocol polymorphism
handles the shell-vs-non-shell distinction.

---

## Coupling Assessment

| Integration                                                           | Strength   | Distance | Volatility  | Balanced?                                                                 |
| --------------------------------------------------------------------- | ---------- | -------- | ----------- | ------------------------------------------------------------------------- |
| `shell_prompt_orchestrator` → `AgentProvider.ensure_prompt_marker`    | Contract   | Low      | Medium-High | **Yes** — protocol method, no implementation knowledge                    |
| `shell_prompt_orchestrator` → `AgentProvider.prompt_marker_present`   | Contract   | Low      | Medium-High | **Yes** — protocol method                                                 |
| `handlers/shell/` → `providers.shell` (declared subsystem dependency) | Functional | Low      | Medium      | **Yes** — shell handlers ARE the shell subsystem; intentional co-location |
| `directory_callbacks` → `detect_provider_from_command`                | Contract   | Low      | Low         | **Yes** — public function, no shell-specific knowledge in callback        |
| 13 handlers → `SessionManager` (writes/lifecycle)                     | Functional | Low      | High        | **Yes** — natural floor; writes require the coordinator                   |
| `window_query` → `window_state_store`                                 | Contract   | Low      | High        | **Yes** ✓ design exemplar unchanged                                       |
| `transcript_reader` → `provider.capabilities.supports_task_tracking`  | Contract   | Low      | High        | **Yes** ✓ fixed in prior series                                           |

One Minor imbalance remains: `shell_capture`, `shell_commands`, and `shell_context`
still import directly from `providers.shell`. Moving them into `handlers/shell/`
makes the dependency declared and auditable but does not change its coupling
strength, distance, or direction. This is accepted as an intentional subsystem
dependency — the balance rule tolerates functional coupling at low distance in a
medium-volatility area.

---

## Design Decisions and Trade-offs

### Decision 1: Protocol extension over co-location for orchestrator

`shell_prompt_orchestrator` serves as the single coordination point for all
five trigger sites. Adding `ensure_prompt_marker` and `prompt_marker_present` to
the protocol lets the orchestrator stay generic — it works for any future
provider that uses a prompt marker, not just shell.

**Alternative considered**: Move `has_prompt_marker` and `setup_shell_prompt`
from `providers.shell_infra` into the orchestrator directly, making it shell-specific.
**Rejected**: The orchestrator is called from generic code (`window_tick`,
`text_handler`). Making it shell-specific would require adding a provider-name
guard at each call site, re-introducing the name-check pattern the earlier series
removed.

**Trade-off accepted**: Two additional methods on the protocol, with no-op
defaults for non-shell providers. Protocol surface grows from 15 to 17 methods.
This is a small cost for a stable abstraction.

**Stateless-provider contract caveat**: The `AgentProvider` protocol docstring
states providers are "stateless — they receive input and return results without
side effects." `ensure_prompt_marker` is intentionally side-effectful: it sends
tmux keys to inject the prompt marker. The protocol docstring must be updated to
distinguish _query methods_ (stateless) from _setup methods_ (`ensure_prompt_marker`
is the only one). For testability, `ShellProvider.ensure_prompt_marker` must accept
injectable `inject_fn` / `capture_fn` parameters, consistent with the existing
pattern in `shell_infra.setup_shell_prompt`.

### Decision 2: Sub-package formalization over moving utilities

The shell handler files (`shell_capture`, `shell_commands`, `shell_context`)
are inherently shell-specific and need `match_prompt`, `KNOWN_SHELLS`, and
`detect_pane_shell`. Two options were considered:

**Option A** (chosen): Create `handlers/shell/` sub-package. The subsystem
dependency on `providers.shell` is declared at the package level, visible in
the directory listing, and auditable in one place.

**Option B**: Move shell utilities out of `providers/` into the handler layer.
**Rejected**: `KNOWN_SHELLS` and `detect_pane_shell` are also used by
`providers/__init__.py` and `providers/process_detection.py` for provider
detection. Moving them to handlers would invert the dependency direction for
those callers. The utility functions belong in the provider layer; the handlers
that consume them declare the dependency explicitly via the sub-package.

### Decision 3: SessionManager — accept natural floor

The v2-v5 series reduced SM importers from 30 to 13 (handler files) via
`window_query` and `session_query` extractions. The remaining 13 are all
legitimate write/lifecycle/query consumers. No further extraction is warranted
without:

- Dissolving SM into independent stores with per-object persistence (large
  structural change, no immediate coupling benefit)
- Introducing command objects / write request queues (adds indirection for
  no gain at low distance)

The one actionable optimization: migrate `set_window_provider` (11 call sites,
7 files) to `session_lifecycle`. This is a rename-not-redesign that reduces SM's
surface by one more frequently-called method. Recommended for the next targeted
pass, not for this design.

---

## Refactoring Progress — Honest Multi-Dimensional Score

The v2-v5 series made real progress on Issue 1 but left Issue 2 entirely
unaddressed. The v5 review's 6.3/10 overall score was generous because the
shell abstraction leaks directly degrade four of the eight measured dimensions.

| Dimension            | v1 ¹    | v2      | v3      | v4      | v5 claimed | v5 honest | After design |
| -------------------- | ------- | ------- | ------- | ------- | ---------- | --------- | ------------ |
| Encapsulation        | 4       | 5       | 6       | 6       | 7          | **6**     | **7**        |
| Cohesion             | 5       | 5       | 5       | 5       | 5          | 5         | **6**        |
| Coupling Discipline  | 4       | 5       | 5       | 5       | 6          | **5**     | **6**        |
| Contract Stability   | 6       | 6       | 6       | 6       | 7          | **6**     | 7            |
| Testability          | 5       | 6       | 7       | 7       | 7          | 7         | 7            |
| Volatility Alignment | 4       | 5       | 5       | 5       | 6          | **5**     | **6**        |
| Module Size          | 6       | 6       | 6       | 6       | 6          | 6         | 6            |
| Dependency Direction | 4       | 5       | 5       | 5       | 6          | **5**     | **6**        |
| **Overall**          | **4.8** | **5.4** | **5.6** | **5.6** | **6.3**    | **5.6**   | **6.4**      |

¹ v1 baseline uses the v2-v5 series' own scores; the shell leaks existed then too
and were already priced into the original 4.8.

**Where the v5 claimed score was inflated (Δ = −0.7):**

- _Encapsulation_ (claimed 7, honest 6): `shell_capture.py` has a module-level
  import of `match_prompt` from the provider layer. A handler reaching into a
  provider implementation at module level is a concrete encapsulation breach.

- _Coupling Discipline_ (claimed 6, honest 5): Five handler files bypass the
  `AgentProvider` protocol — including one with a module-level import. Declaring
  this "Minor at low distance" conflates tolerability with correctness. It is a
  discipline violation against a Core subdomain abstraction.

- _Volatility Alignment_ (claimed 6, honest 5): Shell volatility (prompt format,
  detection logic) cascades directly to handler files because they import shell
  internals. This is the opposite of volatility alignment.

- _Dependency Direction_ (claimed 6, honest 5): Handler layer importing from
  provider implementation layer (not the protocol) runs against the intended
  abstraction direction.

**What the design delivers (honest):**
Changes A and B (protocol extension + `directory_callbacks` cleanup) are
structural fixes: they change the coupling path, not just the file location.
Changes A+B move Encapsulation, Coupling Discipline, Volatility Alignment, and
Dependency Direction each up by 1, and add a structural grouping signal for
Cohesion. Testability gains from the orchestrator being mockable through the
protocol; shell_capture still requires `providers.shell` mocking, so Testability
stays at 7 rather than reaching 8.

Change C (sub-package) is a cognitive-load improvement. It does not change
coupling strength, distance, or direction for `shell_capture`, `shell_commands`,
or `shell_context` — their imports remain. Sub-package scores only benefit
dimensions that measure discoverability (Cohesion), not coupling properties.
Awarding more than +1 to coupling dimensions for Change C alone would reproduce
the same grade-inflation pattern diagnosed in the v5 review.

**Net result**: 5.6 (honest v5) → **6.4** (after this design). Real progress of
+0.8 — all of it earned by structural changes to the import graph, not directory
reorganization.

**What remains below ceiling:**

- Coupling Discipline at 6 (not 7+): `shell_capture`, `shell_commands`,
  `shell_context` still import from `providers.shell` directly. The sub-package
  makes this a declared dependency rather than a scattered leak, but the
  coupling properties are unchanged. Reaching 7 requires either moving
  `match_prompt` / `detect_pane_shell` onto the `AgentProvider` protocol or
  accepting that the shell subsystem is genuinely provider-internal code that
  belongs in `providers/shell/` not `handlers/shell/`.
- Cohesion at 6 (not 7+): The flat top-level handler namespace still has 40+
  files. Extracting `handlers/messaging/` and `handlers/directory/` sub-packages
  would push this to 7 — deferred.
- Module Size at 6: `tmux_manager.py` remains large infrastructure. No benefit
  from splitting.
- Contract Stability at 7 (not 8+): Reaching 8 requires protocol-level versioning
  or interface segregation — not warranted at solo-developer scale.
- Testability at 7 (not 8): `shell_capture`'s module-level import of `match_prompt`
  means its tests still patch `providers.shell` rather than mocking a protocol
  boundary. Moves to 8 only if `match_prompt` is accessed via the protocol or
  injectable parameter.

---

## Unresolved Risks

1. **Three deferred import cycles** — `session.py` ↔ `session_resolver.py`,
   `session_map.py` ↔ `window_state_store.py` / `thread_router.py`. Low priority.
   Fix pattern is proven (extract shared types to dependency-free module). Address
   opportunistically.

2. **`set_window_provider` still on SessionManager** — 11 call sites, 7 files.
   Semantically a lifecycle operation; moving it to `session_lifecycle` is the
   next highest-leverage targeted fix. Not blocking.

3. **Cohesion ceiling** — Flat handler namespace and SessionManager's remaining
   7 concerns limit Cohesion to 6/10. Reaching 7 requires either extracting
   additional sub-packages or further dissolving SessionManager into independent
   stores with their own persistence. Neither is urgent; both are non-trivial.

4. **Protocol surface growth** — At 17 methods after this design, the
   `AgentProvider` protocol is approaching the upper bound of comfortable size.
   Any future extension should audit whether a method belongs on the protocol or
   in a capability flag.
