# LLM Abstraction

## Functional Responsibilities

Provider-agnostic text completion used for two features: (1) shell command generation (NL→command in shell topics), and (2) completion summaries (single-line summary when an agent Stop hook fires).

Files:

- **`llm/base.py`** — `CommandGenerator` Protocol (`async def generate(text, context) -> CommandResult`), `TextCompleter` Protocol (`async def complete(prompt, ...) -> str`), `CommandResult` dataclass.
- **`llm/httpx_completer.py`** — OpenAI-compatible + Anthropic completions via httpx. Implements both protocols. Handles API key resolution (env fallback chain).
- **`llm/summarizer.py`** — completion summary generator. Reads a transcript tail, builds compact context, asks the LLM for a single-line summary. **Currently Claude-hardcoded** — parses `type == "assistant"` / `type == "user"` / `tool_use` / `tool_result` / `content` blocks directly. Deferred per the Apr 12 plan + user confirmation that a second provider is unlikely.
- **`llm/__init__.py`** — `get_completer()` / `get_text_completer()` factories from config.

## Encapsulated Knowledge

- **API key resolution chain** — only `httpx_completer.py` knows the fallback: `CCGRAM_LLM_API_KEY` > provider-specific env var > `OPENAI_API_KEY`.
- **Provider endpoints** — OpenAI, xAI, DeepSeek, Anthropic, Groq, Ollama base URLs and default models.
- **Command prompt template** — only `httpx_completer.py` knows how to wrap shell context + user request into the NL→command prompt.
- **Summary prompt template + Claude JSONL parsing** — only `summarizer.py` knows the "read last N tool events and produce a one-line summary" algorithm. Currently assumes Claude's JSONL.

## Subdomain Classification

**Generic.** Text completion is a solved problem with an abstract Protocol + concrete httpx implementation. Low functional volatility. Moderate implementation volatility (new providers appear) — the `httpx_completer` handles this by parameterising on base URL and model.

**Note on summariser.** The summariser is Claude-hardcoded because no second provider is planned (per maintainer). It is technically provider-specific logic masquerading as generic LLM code. The clean design would move it to `ClaudeProvider.summarise_recent(...)` — deferred until a second provider needs summaries.

## Integration Contracts

### Inbound

| From                                                                                    | Kind     |
| --------------------------------------------------------------------------------------- | -------- |
| `handlers/shell_commands` → `get_completer()` → `CommandGenerator.generate(...)`        | Contract |
| `handlers/hook_events.handle_stop` → `summarizer.summarize_completion(transcript_path)` | Contract |

### Outbound

| To                                                                 | Kind         |
| ------------------------------------------------------------------ | ------------ |
| HTTPX client → OpenAI / xAI / DeepSeek / Anthropic / Groq / Ollama | External API |
| `pathlib.Path.read_text` for transcript reading                    | stdlib       |

## Change Vectors

- **New LLM provider** — add a branch in `__init__.py` factory, set base URL + default model.
- **New completion task** — add a new method or a new file (e.g., `llm/explainer.py` for command explanations).
- **Summary prompt refinement** — touches `summarizer.py` only.
- **Second agent provider's summary format** — **NOT deferred anymore**: would require moving `summarizer.py` inside the provider layer or adding a `parse_for_summary` method to the provider Protocol.

## Testability Goals

- **Unit-test `CommandResult` dataclass** — trivial.
- **Unit-test `httpx_completer.complete`** with a mocked httpx transport — verify prompt construction, verify response parsing.
- **Unit-test `summarizer._build_summary_context`** with fixture JSONL lines — verify the correct tool events are extracted.
- **Unit-test `summarizer.summarize_completion`** with a mocked completer — verify the timeout path and the error path (LLM returns empty string).
- **Integration-test** against a real Ollama local model if available — optional.
