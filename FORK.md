# Origin

CCBot was originally created by [six-ddc](https://github.com/six-ddc) as a Telegram bridge for Claude Code ([six-ddc/ccbot](https://github.com/six-ddc/ccbot), released February 7, 2026).

This project started as a fork on February 8, 2026 and has since been developed independently as a standalone project. The codebase has been largely rewritten — the original provided the initial idea and foundation, but the current implementation shares very little code with the upstream.

## Why a Separate Project

The original ccbot was a clean proof-of-concept. I needed more features for my own workflow and wanted to move faster than upstream, so I took it in a different direction:

- **Multi-provider support** — Claude Code, Codex CLI, and Gemini CLI as interchangeable backends
- **Topic-only architecture** — 1 topic = 1 tmux window = 1 agent session, no legacy routing
- **Interactive UI** — inline keyboards for permission prompts, plan approval, and question answering
- **Recovery flows** — Fresh/Continue/Resume for dead sessions, provider-aware
- **Per-user message queue** — FIFO ordering, message merging, rate limiting
- **MarkdownV2 output** — with automatic plain text fallback
- **1000+ test suite** — with CI enforcement, type checking, and lint rules
- **Python 3.14** — using modern language features

## Thanks

Thanks to [six-ddc](https://github.com/six-ddc) for the original idea and the initial implementation that got this started.
