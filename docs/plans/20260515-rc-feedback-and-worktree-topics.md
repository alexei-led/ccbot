# RC Feedback + Worktree Topics (v3.1.0)

## Overview

Two user-visible features that share a release. Both shipped together as v3.1.0.

1. **Claude `/remote-control` feedback.** Today triggering RC (via status-bubble button or forwarded slash command) produces zero indication of outcome — silent on success, silent on "feature unavailable", silent on failure. This adds a probe that captures the pane after RC is fired, classifies the result, and posts a single status reply in the topic.
2. **Git-worktree integration for new topics.** Inserts an opt-in step between directory-confirm and provider-pick. If the selected directory is an eligible git repo, the user is asked whether to use the current branch or spin up a new worktree on a new branch. Non-git directories are untouched.

**Out of scope (deferred):** codex remote-control support, forking a worktree from a running session, worktree cleanup UX, PR creation, any non-git regression.

**Release after merge:** v3.1.0 (minor — two new features, no breaking changes).

## Context (from discovery)

**Files / components involved:**

Feature 1 — RC feedback:
- `src/ccgram/handlers/status/status_bar_actions.py` — `_handle_remote_control` (line ~208) — status-bubble button entry
- `src/ccgram/handlers/commands/forward.py` — `forward_command_handler` `cc_name in ("remote-control", "rc")` branch (line ~133) — forwarded-slash entry
- `src/ccgram/handlers/polling/polling_state.py` — `TerminalScreenBuffer.is_rc_active(window_id)` already exists as a fallback signal
- `src/ccgram/handlers/polling/polling_types.py` — `WindowPollState` dataclass holds existing `rc_active: bool` field
- `src/ccgram/tmux_manager.py` — `capture_pane` for pane snapshots
- `src/ccgram/handlers/messaging_pipeline/message_sender.py` — `safe_send` for final reply

Feature 2 — worktree:
- `src/ccgram/handlers/topics/directory_browser.py` — `build_provider_picker`, `build_mode_picker` (current 5-step flow stops at provider/mode)
- `src/ccgram/handlers/topics/directory_callbacks.py` — `handle_directory_callback` dispatcher (line ~68), `_handle_confirm` (line ~91)
- `src/ccgram/handlers/callback_data.py` — `CB_DIR_*`, `CB_PROV_SELECT`, `CB_MODE_SELECT` constants live here
- `src/ccgram/handlers/user_state.py` — pending-flow state keys
- `src/ccgram/window_state_store.py` — `WindowState` dataclass + atomic serialization

**Related patterns:**
- Inline-keyboard flow with callback prefixes (e.g. `CB_DIR_SELECT`, `CB_PROV_SELECT`) dispatched via `callback_registry` — same pattern for new worktree callbacks.
- `TelegramClient` Protocol throughout handlers — no `telegram.Bot` import. New handler code must follow.
- Read path: `window_query` / `session_query` for reads; `session_manager.<attr>` only for documented writes (codified by `tests/ccgram/test_query_layer_only_for_handlers.py`).
- All new in-function imports must have `# Lazy: <reason>` (codified by `scripts/lint_lazy_imports.py`).
- Tests mirror source layout under `tests/ccgram/`; integration tests under `tests/integration/`. `asyncio_mode = "auto"`. No comments/docstrings in tests.

**Dependencies identified:**
- No new third-party packages. Worktree feature uses `subprocess.run` against `git` (already a runtime requirement of the host).
- Existing dependencies sufficient: structlog, telegram (PTB), pathlib, asyncio.

## Development Approach

- **Testing approach: Regular** (code-first, then tests in same task — tests are still mandatory).
- Complete each task fully before moving to the next.
- Make small, focused changes; one logical unit per task.
- **Every task MUST include new/updated tests** for code changes in that task. Tests are a required deliverable.
  - Unit tests for new functions and any modified functions.
  - Success and error scenarios both covered.
- **All tests must pass (`make check`) before starting the next task.** No exceptions.
- Update this plan file in-place when scope changes during implementation.
- Maintain backward compatibility — non-git directories see no flow change; non-Claude providers see no RC feedback.

## Testing Strategy

- **Unit tests** (required, per task): `tests/ccgram/handlers/status/test_rc_probe.py`, `tests/ccgram/handlers/topics/test_worktree.py`, plus targeted assertions in existing handler tests for the new wiring points.
- **Integration tests** (required where flow crosses module boundaries): extend `tests/integration/test_topic_creation.py` (or sibling) with a real git fixture repo so the worktree picker → confirm → window creation chain is exercised end-to-end. RC integration spike uses `FakeTelegramClient` + a stubbed `capture_pane`.
- **E2E tests**: no UI-based e2e — `tests/e2e/` exercises real agent CLIs and is out of scope for both features.
- Run `make check` after every task: `make fmt && make lint && make typecheck && make test && make test-integration`.

## Progress Tracking

- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix.
- Document issues/blockers with ⚠️ prefix.
- Update plan if implementation deviates from original scope.
- Keep plan in sync with actual work done.

## Solution Overview

### Feature 1 — RC feedback

A single small probe coroutine, armed by both trigger paths (status button and forwarded slash), classifies pane output after ~1.5s and again at intervals up to ~10s. Posts a single Telegram reply per arming. De-duped by a per-window `rc_probe_state` field. Capability-gated to Claude provider.

### Feature 2 — Worktree picker

A new step in the new-topic flow. Inserted between directory-confirm and provider-pick. Shown only when the selected directory is an eligible git repo. If shown, the user picks either current branch (continue as today) or a new worktree (auto-suggested branch name, one-tap confirm or text-reply edit). Worktrees live at `<repo>.worktrees/<slug>`. Branch name and worktree path persisted in `WindowState` for future cleanup UX.

### Key design decisions

- **Single probe module, two entry points.** RC probe lives in `handlers/status/rc_probe.py`; both `status_bar_actions.py` and `commands/forward.py` call `arm_rc_probe(window_id)`. Keeps the contract one-place-only.
- **Worktree state on `WindowState`, not a side-channel store.** Two new fields (`worktree_path`, `worktree_branch`) on the existing `WindowState` dataclass — atomic with the rest of the topic's metadata.
- **Preconditions hide the step, never fail loudly.** If a directory is not git, is bare, has detached HEAD, or is mid-rebase, the worktree step is silently skipped (current flow). No warning UI unless the user explicitly tried to start a worktree.
- **Existing `is_rc_active` is a fallback, not a replacement.** The probe primarily classifies via regex on captured pane output; `is_rc_active` (already wired into `TerminalScreenBuffer`) is consulted as a tiebreaker before declaring timeout.
- **One-shot text reply only as the minority path.** Auto-generated branch name is the happy path. Edit-name is the only place we accept free text in the new flow.

## Technical Details

### Feature 1 — RC probe

**`arm_rc_probe(window_id: str, client: TelegramClient) -> None`** in `handlers/status/rc_probe.py`:
- ⚠️ Signature deviation from original plan: takes an explicit `client: TelegramClient`. There is no global bot accessor in the codebase, and F5 mandates explicit `TelegramClient` threading. Both Task 2 entry points already have a bot (`query.get_bot()` / `context.bot`) to wrap in `PTBTelegramClient`. The probe still "owns" its send path via `safe_send`.
- Reads existing `rc_probe_state` from `WindowState`. If `armed`, returns early (double-tap guard).
- Sets `rc_probe_state = "armed"`, `rc_armed_at = monotonic()`.
- Schedules `_classify_loop(window_id)` via `asyncio.create_task`.

**`_classify_loop(window_id: str)`** coroutine:
- Sleeps 1.5s before first capture (gives Claude time to render the RC banner).
- Captures pane via `tmux_manager.capture_pane`, scans the last ~30 lines.
- Classifier (pure function `classify_rc_output(text: str) -> RCOutcome`):
  - `RCOutcome.SUCCESS(url)` — URL regex `https://claude\.ai/[^\s]+` OR `https?://[^\s]+remote[^\s]*` matches.
  - `RCOutcome.UNAVAILABLE(reason)` — phrases: `not available`, `requires`, `upgrade`, `permission denied`, `unknown command`.
  - `RCOutcome.FAILED(reason)` — `error` or `failed` near the RC slash line.
  - `RCOutcome.PENDING` — none of the above, retry.
- Retries every 1.5s up to 10s total. Between retries, also checks `terminal_screen_buffer.is_rc_active(window_id)`; if true → treat as success even without URL match (degraded message: "📡 Remote Control active.").
- On any non-PENDING outcome OR on timeout: send the reply, set `rc_probe_state = "classified"`.

**Reply formatting** (via `safe_send`, owns its own `TelegramClient`):
- success with URL: `📡 Remote Control active — <code>URL</code>` (monospace formatting via existing entity helpers)
- success without URL: `📡 Remote Control active.`
- unavailable: `📡 Remote Control unavailable — <one-line reason>.`
- failed: `📡 Remote Control failed — <one-line reason>.`
- timeout: `📡 No response from /remote-control — check the pane.`

**State on WindowState** (`window_state_store.py`):
- `rc_probe_state: Literal["armed", "classified"] | None = None`
- `rc_armed_at: float | None = None`

(Both serialize as part of the existing state.json round-trip; rc-related fields are transient and OK to drop on restart.)

**Capability gate.** Both entry points read `get_provider_for_window(window_id).capabilities.name`. Only `"claude"` arms the probe. Other providers continue to use the existing "not supported by <provider>" reply that already exists in `forward.py` via `_command_known_in_other_provider`.

### Feature 2 — Worktree picker

**Helpers in `handlers/topics/worktree.py`:**

```python
@dataclass(frozen=True)
class WorktreeEligibility:
    eligible: bool
    repo_path: Path | None
    current_branch: str | None
    dirty: bool
    reason: str | None   # populated when eligible=False, for debug logging only

def check_worktree_eligibility(path: Path) -> WorktreeEligibility: ...
def suggest_branch_name(topic_title: str | None, repo_path: Path) -> str: ...
def slug_for_path(branch: str) -> str: ...
def worktree_path_for(repo_path: Path, slug: str) -> Path: ...
def validate_branch_name(name: str) -> bool: ...  # wraps `git check-ref-format --branch`
def create_worktree(repo_path: Path, branch: str, worktree_path: Path) -> None: ...
```

- `check_worktree_eligibility` runs four `git -C <path>` subprocess calls and one filesystem check (`MERGE_HEAD` / `rebase-apply` / `rebase-merge`). Returns a frozen dataclass.
- `suggest_branch_name` returns `ccg/<kebab(topic-title)>` or `ccg/agent-<n>` (n = smallest integer such that no branch/worktree already uses it).
- `slug_for_path(branch)` replaces `/` with `-` for the worktree directory name.
- `worktree_path_for(repo_path, slug)` → `repo_path.parent / f"{repo_path.name}.worktrees" / slug`.
- `validate_branch_name(name)` runs `git check-ref-format --branch <name>`; returns bool.
- `create_worktree` runs `git -C <repo> worktree add <worktree_path> -b <branch> HEAD`. Raises `WorktreeError` on failure.

**Picker keyboard builders in `directory_browser.py`:**

```python
def build_worktree_picker(repo_path: str, current_branch: str) -> tuple[str, InlineKeyboardMarkup]: ...
def build_worktree_confirm(
    repo_path: str, branch: str, worktree_path: str, dirty: bool
) -> tuple[str, InlineKeyboardMarkup]: ...
```

**Callbacks added in `callback_data.py`:**
- `CB_WT_USE_CURRENT = "wt:cur"` — keep current branch, fall through to provider picker (no worktree created)
- `CB_WT_NEW = "wt:new"` — show confirm/edit screen with suggested branch
- `CB_WT_CONFIRM = "wt:ok"` — create the worktree, fall through to provider picker with worktree path as cwd
- `CB_WT_EDIT_NAME = "wt:ed"` — prompt for branch name via text reply, validate, then create

**User-state keys added in `handlers/user_state.py`:**
- `PENDING_WORKTREE_REPO` — selected repo path while in worktree flow
- `PENDING_WORKTREE_BRANCH` — suggested or user-edited branch name
- `PENDING_WORKTREE_PATH` — computed worktree path
- `AWAITING_WORKTREE_BRANCH_NAME` — set when waiting for text reply on edit-name

**`directory_callbacks._handle_confirm` change:** after directory is confirmed, call `check_worktree_eligibility(path)`. If eligible, edit-message to the worktree picker. If not, behave exactly as today (jump straight to provider picker).

**`WindowState` extension** (`window_state_store.py`):
- `worktree_path: str | None = None`
- `worktree_branch: str | None = None`

Set on window creation in `topic_orchestration.py` when the flow took the worktree path. Persisted to state.json. No behavior reads them yet — they're a forward investment for the eventual cleanup UX.

**Edit-name flow.** When user taps Edit name: store `AWAITING_WORKTREE_BRANCH_NAME = True` in user_data, prompt "Send branch name, or /cancel." The existing text-message router (`handlers/text/text_handler.py`) needs a small guard at the top: if `AWAITING_WORKTREE_BRANCH_NAME`, route to a new `_handle_worktree_name_reply` instead of forwarding to the window. Validate via `validate_branch_name`; on success → show confirm again with the new name; on failure → reply "Invalid branch name; try again or /cancel."

## What Goes Where

- **Implementation Steps** (checkboxes): code, tests, doc updates in this repo.
- **Post-Completion** (no checkboxes): release tagging, CHANGELOG, manual smoke testing.

## Implementation Steps

### Task 1: RC probe — module + state fields

**Files:**
- Create: `src/ccgram/handlers/status/rc_probe.py`
- Modify: `src/ccgram/window_state_store.py`
- Create: `tests/ccgram/handlers/status/test_rc_probe.py`

- [x] add `rc_probe_state: Literal["armed", "classified"] | None = None` and `rc_armed_at: float | None = None` to `WindowState` dataclass
- [x] update `WindowState` serialization to drop these on round-trip (or persist — pick one consistently); ensure existing state.json files load without error (backward-compat for missing fields) — chose transient: NOT added to to_dict/from_dict; dataclass defaults give backward-compat on load
- [x] create `rc_probe.py` with: `RCOutcome` enum/union, `classify_rc_output(text: str) -> RCOutcome` pure function, `arm_rc_probe(window_id, client) -> None`, `_classify_loop(window_id, client)` coroutine, `_send_outcome_reply` helper (`_format_reply` split out for testability)
- [x] capability gate: `arm_rc_probe` returns immediately if `get_provider_for_window(window_id).capabilities.name != "claude"`
- [x] write unit tests for `classify_rc_output` with fixture pane captures: success with URL, success URL near prompt, unavailable phrases, error phrases, pending (nothing matches)
- [x] write unit tests for `arm_rc_probe` double-tap guard (second call while `armed` is no-op) + capability gate (codex → no-op)
- [x] write integration-style test for `_classify_loop`: stubbed `capture_pane` returns success on second poll → asserts one `safe_send` call with URL; plus timeout-resets-state test and a source-scan test asserting no `telegram.Bot` import
- [x] run `make check` — fmt/lint/typecheck/deptry clean; 4787 unit pass (incl. new layering allowlist entry for `status/rc_probe.py`); 267 integration pass. ⚠️ `test_doctor_cmd.py::test_reports_missing_hooks_for_codex_provider` fails on clean branch HEAD too (pre-existing, environmental, unrelated to Task 1) — tracked separately

### Task 2: Wire RC probe into both trigger paths

**Files:**
- Modify: `src/ccgram/handlers/status/status_bar_actions.py`
- Modify: `src/ccgram/handlers/commands/forward.py`
- Modify: `tests/ccgram/handlers/status/test_rc_probe.py` (extend)
- Modify or create: `tests/ccgram/handlers/status/test_status_bar_actions.py`
- Modify or create: `tests/ccgram/handlers/commands/test_forward.py`

- [x] in `_handle_remote_control`: after `send_to_window(...)`, call `arm_rc_probe(window_id, PTBTelegramClient(query.get_bot()))` with a lazy-import marker (rc_probe pulls providers/__init__ — same deferral reason as `_handle_status_recall`). Signature deviation from Task 1 carried through: explicit `client` arg, no global bot accessor
- [x] in `forward.py`: extracted to helper `_arm_rc_probe_if_remote_control(update, window_id, cc_name)` (kept `forward_command_handler` under the C901 complexity-10 cap — mirrors the existing `_handle_clear_command` helper pattern); helper gates on `cc_name in ("remote-control", "rc")`, calls `arm_rc_probe(window_id, PTBTelegramClient(update.get_bot()))`, docstring states the Claude-only capability gate is internal
- [x] unit tests in `test_status_bar_actions.py`: `test_arms_rc_probe_after_activation` (fake terminal_screen_buffer inactive → arm invoked with `@0` + `PTBTelegramClient`) and `test_does_not_arm_probe_when_already_active` (rc-active → not armed)
- [x] unit tests in `test_forward.py`: `test_arms_rc_probe_for_claude_remote_control`, `test_arms_rc_probe_for_rc_alias`, `test_no_rc_probe_for_non_rc_command`, `test_no_rc_probe_for_codex_rejected_remote_control` (codex `/remote-control` rejected by `_command_known_in_other_provider` → arm not invoked, send not called)
- [x] run `make check` — fmt/lint-lazy/lint/typecheck clean; 4793 unit pass; 267 integration pass; import-cycle + query-layer guards green. ⚠️ `test_doctor_cmd.py::test_reports_missing_hooks_for_codex_provider` still fails (same pre-existing environmental failure documented in Task 1 — codex hooks are installed on this machine; unrelated to Task 2 which touches only RC wiring)

### Task 3: Worktree helpers module

**Files:**
- Create: `src/ccgram/handlers/topics/worktree.py`
- Create: `tests/ccgram/handlers/topics/test_worktree.py`

- [x] implement `WorktreeEligibility` frozen dataclass and `check_worktree_eligibility(path: Path)` running the four git checks (in-work-tree, not-bare, named-branch, no merge/rebase). Use `subprocess.run` with `check=False` and inspect returncode/stdout — git-dir resolution + merge/rebase check extracted to `_resolve_git_dir`/`_has_merge_or_rebase` helpers to stay under C901 complexity-10
- [x] implement `suggest_branch_name(topic_title, repo_path)` with kebab-case + `ccg/agent-<n>` fallback; collision avoidance by listing `git -C <repo> branch --list` and `git -C <repo> worktree list --porcelain`
- [x] implement `slug_for_path(branch)` and `worktree_path_for(repo_path, slug)`
- [x] implement `validate_branch_name(name)` via `git check-ref-format --branch <name>` (returncode check); also rejects empty/over-long/leading-dash up front (leading-dash would be misread as a git option)
- [x] implement `create_worktree(repo_path, branch, worktree_path)` with `WorktreeError` exception on failure (include git stderr in message)
- [x] write unit tests using a `tmp_path` git repo fixture: eligibility for clean repo, bare repo, detached HEAD, mid-rebase, non-git dir (all combinations) — real git, not mocked
- [x] write unit tests for `suggest_branch_name`: kebab-case, collision with existing branch, collision with existing worktree, no topic title
- [x] write unit tests for `validate_branch_name`: valid name, name with spaces (invalid), name with `..` (invalid)
- [x] write unit tests for `create_worktree`: success creates the dir + branch; on conflict raises `WorktreeError`
- [x] run `make check` — fmt/lint/typecheck clean; 26 new tests pass; 4822 total pass. ⚠️ only `test_doctor_cmd.py::test_reports_missing_hooks_for_codex_provider` fails — same pre-existing environmental failure documented in Tasks 1 & 2 (codex hooks installed on this machine; new module is isolated, cannot affect doctor)

### Task 4: Worktree picker keyboards and callback constants

**Files:**
- Modify: `src/ccgram/handlers/callback_data.py`
- Modify: `src/ccgram/handlers/topics/directory_browser.py`
- Modify: `src/ccgram/handlers/user_state.py`
- Modify: `tests/ccgram/handlers/topics/test_directory_browser.py` (or create)

- [x] add `CB_WT_USE_CURRENT`, `CB_WT_NEW`, `CB_WT_CONFIRM`, `CB_WT_EDIT_NAME` constants (static `wt:*` callbacks, no per-instance suffix — well under the 64-byte budget; the ≤24-char note in the design refers to action-name length and is N/A here)
- [x] add `PENDING_WORKTREE_REPO`, `PENDING_WORKTREE_BRANCH`, `PENDING_WORKTREE_PATH`, `AWAITING_WORKTREE_BRANCH_NAME` user-state keys
- [x] implement `build_worktree_picker(repo_path, current_branch) -> (text, InlineKeyboardMarkup)` matching the design preview (use-current / new-worktree / cancel) — cancel reuses `CB_DIR_CANCEL`, consistent with `build_provider_picker`/`build_mode_picker`
- [x] implement `build_worktree_confirm(repo_path, branch, worktree_path, dirty) -> (text, InlineKeyboardMarkup)` with dirty warning line if applicable
- [x] write unit tests asserting both keyboards have the expected button rows, labels include the branch name, and callback_data length is within budget (9 new tests in `test_directory_browser.py`)
- [x] run `make check` — fmt/lint-lazy/lint/typecheck clean; 4830 unit pass; import-cycle (171) + query-layer (89) guards green. ⚠️ only `test_doctor_cmd.py::test_reports_missing_hooks_for_codex_provider` fails — same pre-existing environmental failure documented in Tasks 1–3 (codex hooks installed on this machine; Task 4 touches no doctor code)

### Task 5: Wire worktree picker into directory flow

**Files:**
- Modify: `src/ccgram/handlers/topics/directory_callbacks.py`
- Modify: `src/ccgram/handlers/topics/topic_orchestration.py`
- Modify: `src/ccgram/window_state_store.py`
- Modify: `src/ccgram/handlers/text/text_handler.py`
- Modify: `tests/ccgram/handlers/topics/test_directory_callbacks.py` (or create)

- [ ] add `worktree_path: str | None = None`, `worktree_branch: str | None = None` to `WindowState`; serialize and load (backward-compat for old state.json)
- [ ] in `handle_directory_callback`, add prefix dispatches for the four new CB_WT_* constants
- [ ] in `_handle_confirm`: after directory is confirmed, call `check_worktree_eligibility`. If eligible → store repo path in user_data and edit-message to worktree picker. If not → fall through to provider picker as today
- [ ] implement `_handle_wt_use_current`: clear worktree user_data, fall through to provider picker with the original directory as cwd
- [ ] implement `_handle_wt_new`: suggest branch name, store in user_data, edit-message to worktree confirm
- [ ] implement `_handle_wt_confirm`: call `create_worktree`, on success store path/branch in user_data, fall through to provider picker with worktree path as cwd. On failure: edit-message with one-line error and a Cancel button
- [ ] implement `_handle_wt_edit_name`: set `AWAITING_WORKTREE_BRANCH_NAME = True` in user_data, send "Send branch name, or /cancel."
- [ ] in `text_handler.py`, add a guard at the top: if `AWAITING_WORKTREE_BRANCH_NAME` in user_data → route to `_handle_worktree_name_reply` (validate via `validate_branch_name`; on success update suggested branch, re-show confirm; on failure → reply "Invalid branch name; try again or /cancel."). Clear flag on /cancel or success
- [ ] in `topic_orchestration.py`: when window is created, if `PENDING_WORKTREE_PATH` is set in user_data, persist `worktree_path` and `worktree_branch` to the new `WindowState`. Clear all worktree user_data keys after window creation
- [ ] write integration test using a real git fixture repo: confirm directory → assert worktree picker shown → tap "Use current branch" → assert provider picker shown next; tap "New worktree" → assert confirm shown → tap "Use this" → assert worktree created at expected path AND `WindowState.worktree_path` is set
- [ ] write integration test for the edit-name text-reply path
- [ ] write integration test for non-git directory: assert worktree picker is skipped (provider picker shown directly)
- [ ] run `make check` — must pass before Task 6

### Task 6: Verify acceptance criteria

- [ ] verify all Overview requirements implemented: RC feedback fires on both button and forwarded slash; worktree picker appears only for eligible git repos; non-git flow unchanged
- [ ] verify all edge cases handled: double-tap on RC button (no second probe); cancel at every worktree step; invalid branch name; dirty source repo (allowed with warning); mid-rebase repo (worktree picker skipped)
- [ ] run full unit test suite: `make test`
- [ ] run integration test suite: `make test-integration`
- [ ] run lint + typecheck + lazy-import lint: `make lint && make typecheck`
- [ ] confirm `tests/ccgram/test_query_layer_only_for_handlers.py` still passes (no new violations)
- [ ] confirm `tests/integration/test_import_no_cycles.py` still passes (no new cycles)
- [ ] manual smoke (in a real Telegram session in the worktree's running bot instance): trigger `/remote-control` via button → see status reply; create a new topic in a git repo → exercise both worktree branches; create one in a non-git dir → confirm no flow change

### Task 7: Update documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/rules/architecture.md`
- Modify: `.claude/rules/topic-architecture.md`
- Move: this plan to `docs/plans/completed/`

- [ ] update `CLAUDE.md`: brief note under "Provider Configuration" (Claude RC feedback) and a new "Git Worktree Integration" subsection under topic flow
- [ ] update `.claude/rules/architecture.md`: add `handlers/status/rc_probe.py` and `handlers/topics/worktree.py` to module inventory
- [ ] update `.claude/rules/topic-architecture.md`: insert "Worktree picker (optional, inserted when directory is an eligible git repo)" between directory-confirm and provider-pick in the new-topic flow narrative
- [ ] move this plan to `docs/plans/completed/`
- [ ] final `make check`

## Post-Completion

*Items requiring manual intervention or external systems — no checkboxes, informational only.*

**Manual verification:**
- Launch a dev bot instance, trigger `/remote-control` in a real Claude session, confirm the status reply renders with the URL as monospace and is tap-to-copy on mobile.
- Confirm RC button → reply path and forwarded slash → reply path produce identical messages.
- Trigger `/remote-control` on a Claude account without RC entitlement; confirm "📡 Remote Control unavailable — …" message appears.
- Create a new topic in a git repo; exercise current-branch, new-worktree-use-this, new-worktree-edit-name flows. Confirm worktree appears at `<repo>.worktrees/<slug>` and the new topic is rooted there.
- Create a new topic in a non-git directory; confirm zero change in UX (no worktree picker shown).
- Verify `state.json` round-trip with the new `worktree_path`/`worktree_branch` fields (kill bot, restart, confirm topic still resolves).

**Release after merge:**
- Bump to v3.1.0 via the existing release workflow (`git cliff --tag v3.1.0 --output CHANGELOG.md`, commit, tag, push). PyPI + Homebrew + GitHub Release auto-publish via `release.yml`.
- Add v3.1.0 release notes highlighting both features with screenshots of the Telegram UI.

**External system updates:** none. No consuming projects depend on the internal API of these handlers.
