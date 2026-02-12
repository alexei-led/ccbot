---
name: releasing
description: Tag version and trigger PyPI + Homebrew release. Use when user says "release", "tag and release", "publish version".
disable-model-invocation: true
user-invocable: true
allowed-tools: Bash(git *), Bash(gh *), Bash(make check), Read
argument-hint: <version> (e.g., 0.3.0)
model: haiku
---

# Release v$ARGUMENTS

Tag and publish a new version to PyPI and Homebrew.

## Pre-flight

1. Verify on `main` branch: `git branch --show-current`
2. Verify working tree is clean: `git status`
3. Run `make check` — all must pass
4. Confirm no unpushed commits: `git log origin/main..HEAD --oneline`

## Tag and Push

5. Tag: `git tag v$ARGUMENTS`
6. Push tag: `git push origin v$ARGUMENTS`

## Monitor

7. Wait 30s, then check: `gh api repos/alexei-led/ccbot/actions/runs --jq '.workflow_runs[0] | "\(.name): \(.status) \(.conclusion // "running")"'`
8. If publish job failed, show logs and stop
9. If update-homebrew failed, show logs and stop
10. Report final status

## Notes

- hatch-vcs generates version from tag: `v0.3.0` → PyPI `0.3.0`
- Release workflow: `.github/workflows/release.yml`
- Re-tag if needed: `git tag -d v$ARGUMENTS && git push origin :refs/tags/v$ARGUMENTS && git tag v$ARGUMENTS && git push origin v$ARGUMENTS`
