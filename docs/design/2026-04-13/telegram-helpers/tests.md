# Telegram Helpers — Test Specification

## Unit Tests

| Name                                                 | Scenario                        | Expected                                      |
| ---------------------------------------------------- | ------------------------------- | --------------------------------------------- |
| `test_split_message_short`                           | Under 4096                      | Single page                                   |
| `test_split_message_exact_4096`                      | Exactly 4096                    | Single page                                   |
| `test_split_message_over_4096`                       | 8000 chars                      | Two pages                                     |
| `test_split_message_preserves_expandable_quote`      | Quote spans split point         | Quote kept atomic                             |
| `test_format_expandable_quote_under_limit`           | 1000 chars                      | Returns wrapped text                          |
| `test_format_expandable_quote_at_limit`              | 3500 chars                      | Not truncated                                 |
| `test_format_expandable_quote_over_limit`            | 5000 chars                      | Truncated with "… (truncated, N chars total)" |
| `test_convert_to_entities_plain_text`                | Plain text                      | Plain text + no entities                      |
| `test_convert_to_entities_markdown`                  | `**bold**`                      | Plain text + bold entity at correct offset    |
| `test_convert_to_entities_expandable_quote_sentinel` | Wrapped text                    | Blockquote expandable entity                  |
| `test_rate_limit_minimum_interval`                   | Send twice rapidly              | Second delayed by 0.5s                        |
| `test_rate_limit_independent_per_user`               | Two users send simultaneously   | No cross-blocking                             |
| `test_safe_reply_markdown_fallback`                  | First attempt raises BadRequest | Second attempt as plain text succeeds         |
| `test_response_builder_pagination_nav`               | 10 pages                        | Prev/Next buttons                             |

## Integration Contract Tests

| Name                                          | Scenario                 | Expected                                                     |
| --------------------------------------------- | ------------------------ | ------------------------------------------------------------ |
| `test_safe_send_uses_entity_formatting`       | Any send call            | Goes through `convert_to_entities`                           |
| `test_every_outbound_goes_through_rate_limit` | grep source              | All `bot.send_message` calls inside `message_sender` helpers |
| `test_base_py_has_no_expandable_quote`        | grep `providers/base.py` | No references to expandable quote sentinels                  |

## Boundary Tests

| Name                                   | Scenario                     | Expected                      |
| -------------------------------------- | ---------------------------- | ----------------------------- |
| `test_split_at_middle_of_entity`       | Entity crosses 4096 boundary | Split respects entity bounds  |
| `test_rate_limit_with_lock_contention` | Two tasks race               | Serialized via asyncio.Lock   |
| `test_empty_message_send`              | Text = ""                    | Handled (log warning or skip) |

## Behavior Tests

| Name                                             | Scenario                | Expected                                       |
| ------------------------------------------------ | ----------------------- | ---------------------------------------------- |
| `test_scenario_long_message_paginated`           | 10000-char history page | Two Telegram messages with continuation marker |
| `test_scenario_markdown_fallback_on_parse_error` | Malformed markdown      | Second attempt as plain text wins              |
