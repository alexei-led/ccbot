# Telegram Helpers

## Functional Responsibilities

Thin layer of helpers that wrap python-telegram-bot primitives with entity-based formatting, safe fallback, rate limiting, and pagination. Every outbound message in ccgram (except the queue worker and some UI code) goes through here.

Files:

- **`entity_formatting.py`** — converts markdown to plain text + `MessageEntity` offsets via `telegramify-markdown`. Handles the `EXPANDABLE_QUOTE_START` / `EXPANDABLE_QUOTE_END` sentinel contract from `expandable_quote.py`.
- **`expandable_quote.py`** — sentinel constants (`\x02EXPQUOTE_START\x02`, `\x02EXPQUOTE_END\x02`) and `format_expandable_quote(text)` wrapper with truncation at 3500 chars.
- **`handlers/message_sender.py`** — `safe_reply`, `safe_edit`, `safe_send`, `rate_limit_send_message`, `edit_with_fallback`. Rate-limit primitives: `_last_send_time`, `_rate_limit_locks` per user.
- **`handlers/response_builder.py`** — response pagination (split long messages into pages), inline keyboard for page navigation.
- **`telegram_sender.py`** — `split_message(text, max_len)` — Telegram 4096-char limit splitter respecting expandable quote atomicity.
- **`telegram_request.py`** — custom HTTPX transport for resilient long polling.

## Encapsulated Knowledge

- **4096 char limit** — only `telegram_sender.split_message` knows how to split while keeping expandable quotes atomic.
- **Expandable quote sentinel contract** — `expandable_quote.py` owns the opaque `\x02`-bracketed tokens. Producers wrap text; `entity_formatting.convert_to_entities` reads the sentinels during markdown conversion.
- **Rate-limit timing** — `message_sender._last_send_time` dict; minimum 0.5s between sends per user via `rate_limit_send_message`.
- **Fallback-to-plain-text** — every `safe_*` function tries markdown first, then retries as plain text on any parse error.

## Subdomain Classification

**Generic + wrapper.** python-telegram-bot handles the protocol; ccgram wraps it with conventions. Low volatility after the Apr 12 refactor that moved the sentinel constants out of `providers/base.py`.

## Integration Contracts

### Inbound

| From                                                                                           | Kind     |
| ---------------------------------------------------------------------------------------------- | -------- |
| Every module that sends Telegram messages → `safe_send` / `safe_edit` / `safe_reply`           | Contract |
| `message_queue._process_content_task` → `rate_limit_send_message`                              | Contract |
| `status_bubble.send_status_text` → `rate_limit_send_message` / `edit_with_fallback`            | Contract |
| Producers (`transcript_parser`, `codex provider`, `history`) → `format_expandable_quote(text)` | Contract |

### Outbound

| To                                                                                                               | Kind    |
| ---------------------------------------------------------------------------------------------------------------- | ------- |
| python-telegram-bot `Bot.send_message`, `edit_message_text`, `edit_message_media`, `send_photo`, `send_document` | Library |
| `telegramify-markdown` for markdown → entities                                                                   | Library |
| `httpx.AsyncClient` for custom transport                                                                         | Library |

## Change Vectors

- **Telegram 4096 limit changes** — constant in `telegram_sender.py`.
- **New markdown extension** — `telegramify-markdown` upgrade; test the fallback still works.
- **Adjust rate limit** — constant in `message_sender.py`.
- **Add a new response format** (e.g., "send as file if >4096 chars") — touches `response_builder.py`.

## Testability Goals

- **Unit-test `split_message`** with fixture strings — boundary cases, expandable-quote atomicity, exact 4096-char content.
- **Unit-test `format_expandable_quote`** — under, at, over the truncation threshold.
- **Unit-test `entity_formatting.convert_to_entities`** with fixture markdown — verify plain text + entity offsets.
- **Unit-test `rate_limit_send_message`** with a fake clock — verify the 0.5s gap is enforced.
- **Unit-test `safe_reply`** fallback — first attempt raises `BadRequest` on markdown, second attempt succeeds on plain text.
