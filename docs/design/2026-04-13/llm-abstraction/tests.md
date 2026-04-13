# LLM Abstraction — Test Specification

## Unit Tests

| Name                                           | Scenario                                      | Expected                                       |
| ---------------------------------------------- | --------------------------------------------- | ---------------------------------------------- |
| `test_get_completer_factory_openai`            | Config openai                                 | Returns httpx_completer targeting OpenAI       |
| `test_get_completer_factory_ollama`            | Config ollama                                 | Returns httpx_completer targeting local Ollama |
| `test_api_key_resolution_explicit`             | `CCGRAM_LLM_API_KEY` set                      | Used                                           |
| `test_api_key_resolution_provider_fallback`    | `CCGRAM_LLM_API_KEY` unset, `XAI_API_KEY` set | Used                                           |
| `test_api_key_resolution_universal_fallback`   | Only `OPENAI_API_KEY` set                     | Used                                           |
| `test_http_completer_parses_openai_response`   | Mocked httpx response                         | Returns text                                   |
| `test_http_completer_handles_timeout`          | Mocked timeout                                | Returns error or raises                        |
| `test_command_result_dataclass`                | Build instance                                | Fields accessible                              |
| `test_command_generator_generate_success`      | Mocked LLM                                    | Returns CommandResult                          |
| `test_command_generator_generate_dangerous`    | LLM flags dangerous                           | `is_dangerous=True`                            |
| `test_summarizer_parse_entry_assistant`        | Claude JSONL assistant line                   | Returns blocks list                            |
| `test_summarizer_parse_entry_user_tool_result` | User line with tool_result                    | Captures result snippet                        |
| `test_summarizer_build_context_trims`          | 200 lines                                     | Returns compact context under token budget     |
| `test_summarize_completion_timeout`            | Mocked LLM hangs                              | Returns None after timeout                     |
| `test_summarize_completion_success`            | Mocked LLM returns text                       | Returns single line                            |
| `test_read_tail_lines_small_file`              | 10-line file, request 5                       | Returns last 5                                 |

## Integration Contract Tests

| Name                                                                | Scenario                      | Expected                                        |
| ------------------------------------------------------------------- | ----------------------------- | ----------------------------------------------- |
| `test_command_generator_real_openai` (optional, skipped by default) | Real OpenAI key               | End-to-end NL→command                           |
| `test_summarizer_with_mock_completer`                               | Fake completer returns "Done" | Summary = "Done"                                |
| `test_summarizer_hardcodes_claude_jsonl_format`                     | Non-Claude transcript         | Returns None or garbage — documented limitation |

## Boundary Tests

| Name                           | Scenario      | Expected                      |
| ------------------------------ | ------------- | ----------------------------- |
| `test_empty_transcript_tail`   | Empty file    | Context empty, LLM not called |
| `test_malformed_jsonl_in_tail` | Garbage lines | Skipped, logged               |
| `test_llm_rate_limit_response` | 429           | Retries or returns None       |

## Behavior Tests

| Name                                          | Scenario                             | Expected                                            |
| --------------------------------------------- | ------------------------------------ | --------------------------------------------------- |
| `test_scenario_nl_to_command_success`         | "list files sorted by size"          | LLM returns `ls -lS`, CommandResult.command set     |
| `test_scenario_completion_summary_round_trip` | Stop hook fires with real transcript | Single-line summary delivered to Telegram within 3s |
