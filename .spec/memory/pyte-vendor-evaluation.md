# pyte Vendor-Copy Evaluation

**Decision: Keep as pip dependency. Do not vendor.**

## Project Health

| Metric               | Status                                  |
| -------------------- | --------------------------------------- |
| Latest PyPI release  | 0.8.2 (November 2023)                   |
| Last commit          | April 2025 (typing fix)                 |
| GitHub stars / forks | 108 / 681                               |
| Open issues / PRs    | 41 / 12                                 |
| Python 3.14 compat   | No issues; pure Python, no C extensions |
| Unreleased 0.8.3     | In-repo, bumps min Python to 3.10       |

## ccbot Usage (screen_buffer.py, 48 LOC)

7 API surface items across 2 classes:

```python
pyte.Screen(columns, rows)   # constructor
pyte.Stream(screen)          # constructor
screen.columns               # int
screen.lines                 # int
screen.display               # list[str]
screen.cursor.y              # int
screen.reset()               # method
stream.feed(text)            # method
```

## Vendor-Copy Assessment

**Estimated vendor footprint: ~2,000 LOC (entire package).**

Cannot meaningfully subset — `Screen` (1,068 LOC) depends on `streams`, `control`, `modes`, `graphics`, `charsets`. Stripping unused methods saves ~200-300 LOC but requires ongoing diff maintenance.

## Recommendation: Keep as Dependency

1. **Stable interface** — 7 API items unchanged since 0.8.0
2. **Zero security history** — pure-text emulator, no I/O
3. **No size benefit** — would vendor all ~2,000 LOC anyway
4. **Still alive** — April 2025 commits, 0.8.3 in progress
5. **681 forks** — community provides rapid 3.14 compat if needed
6. **PyPI risk mitigation** — lockfile + private mirror, not vendoring

If Python 3.14 breaks pyte before 0.8.3: file upstream PR or apply 1-5 line local patch via `uv` overrides.
