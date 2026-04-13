# Whisper Transcription

## Functional Responsibilities

Voice message transcription via OpenAI-compatible Whisper APIs. The user sends a voice note in a Telegram topic; the bot downloads the OGA, sends it to the transcription endpoint, and shows the user a "Send / Drop" keyboard with the transcribed text.

Files:

- **`whisper/base.py`** — `WhisperTranscriber` Protocol, `TranscriptionResult` dataclass (text, language, duration, confidence optional).
- **`whisper/httpx_transcriber.py`** — httpx implementation supporting OpenAI, Groq, and any OpenAI-compatible `/audio/transcriptions` endpoint.
- **`whisper/__init__.py`** — `get_transcriber()` factory from config.
- **`handlers/voice_handler.py`** — voice message download, transcription call, confirm keyboard rendering.
- **`handlers/voice_callbacks.py`** — `vc:send` / `vc:drop` callback dispatch. Shell provider transcriptions route through the LLM (NL→command) before being sent.

## Encapsulated Knowledge

- **Transcription endpoint quirks** — only `httpx_transcriber.py` knows the multipart upload format, the API key headers, and the response schema differences between OpenAI and Groq.
- **OGA → PCM conversion** (if any) — currently not done; the API accepts OGA directly.
- **Voice → shell command routing** — `voice_callbacks.py` knows that shell topics get the transcript run through the LLM rather than sent as raw text.

## Subdomain Classification

**Generic.** Transcription is a solved problem — OpenAI-compatible APIs exist and the Protocol abstracts them. Low volatility.

## Integration Contracts

### Inbound

| From                                                                     | Kind     |
| ------------------------------------------------------------------------ | -------- |
| PTB voice message filter → `voice_handler.handle_voice(update, context)` | Contract |
| PTB callback dispatcher → `voice_callbacks._dispatch`                    | Contract |

### Outbound

| To                                                                      | Kind         |
| ----------------------------------------------------------------------- | ------------ |
| HTTPX to transcription endpoint                                         | External API |
| `message_sender.safe_send`                                              | Contract     |
| `shell_commands.generate_from_nl(...)` when the source is a shell topic | Contract     |

## Change Vectors

- **New transcription provider** — branch in `whisper/__init__.py` factory.
- **Language override** — add to config.
- **Auto-send policy** (no confirm keyboard) — `voice_handler` flag.

## Testability Goals

- **Unit-test `httpx_transcriber.transcribe`** with mocked httpx — verify multipart upload and response parsing.
- **Unit-test `voice_handler.handle_voice`** with a mocked bot, mocked transcriber, mocked file download — verify the confirm keyboard appears with the transcribed text.
- **Unit-test shell-provider voice routing** — verify that when source topic is shell, the transcript goes through `shell_commands` instead of being sent raw.
