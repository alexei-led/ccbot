# Whisper Transcription — Test Specification

## Unit Tests

| Name                                            | Scenario             | Expected                                                  |
| ----------------------------------------------- | -------------------- | --------------------------------------------------------- |
| `test_httpx_transcriber_parses_openai_response` | Mocked response      | Returns TranscriptionResult                               |
| `test_httpx_transcriber_multipart_upload`       | Mocked httpx         | Verifies multipart body shape                             |
| `test_get_transcriber_factory_openai`           | Config openai        | Correct base URL + model                                  |
| `test_get_transcriber_factory_groq`             | Config groq          | Correct base URL + model                                  |
| `test_voice_handler_builds_confirm_keyboard`    | Transcription result | Send/Drop keyboard                                        |
| `test_voice_callback_send_plain_topic`          | Non-shell topic      | Text sent as user message to agent                        |
| `test_voice_callback_send_shell_topic`          | Shell topic          | Text routed through `shell_commands.handle_shell_message` |
| `test_voice_callback_drop_cleans_state`         | Tap drop             | `context.user_data` cleared                               |

## Integration Contract Tests

| Name                                         | Scenario                                | Expected                                             |
| -------------------------------------------- | --------------------------------------- | ---------------------------------------------------- |
| `test_voice_handler_download_and_transcribe` | Mocked bot.get_file, mocked transcriber | File downloaded, transcribed, confirm keyboard shown |
| `test_voice_shell_routing`                   | Shell topic, voice note                 | NL→command path engaged                              |

## Boundary Tests

| Name                           | Scenario           | Expected                    |
| ------------------------------ | ------------------ | --------------------------- |
| `test_empty_transcription`     | Silence input      | Result empty, user notified |
| `test_transcription_api_error` | 500 response       | User notified, no crash     |
| `test_missing_api_key`         | Config without key | Graceful error              |

## Behavior Tests

| Name                                  | Scenario                                                                   | Expected                        |
| ------------------------------------- | -------------------------------------------------------------------------- | ------------------------------- |
| `test_scenario_voice_in_claude_topic` | Send voice "list my files" → transcript → user confirms → sent to Claude   | Claude receives "list my files" |
| `test_scenario_voice_in_shell_topic`  | Send voice "list files" → transcript → LLM generates `ls` → approval → run | Shell receives `ls`             |
