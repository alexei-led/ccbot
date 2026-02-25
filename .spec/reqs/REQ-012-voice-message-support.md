---
id: REQ-012
title: Voice Message Support (Whisper Transcription)
type: feature
status: open
priority: high
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-012: Voice Message Support

## Motivation

CCBot is designed for mobile-first usage: controlling agents while away from
desk. Typing long prompts on a phone is friction. Telegram natively supports
voice notes — the user records a voice note, and CCBot transcribes it and
forwards the text to the agent.

This directly reduces the main UX pain point of mobile agent control.

## Success Criteria

1. When a voice note is sent to any bound topic, CCBot downloads the `.ogg` audio
2. Transcribes it via OpenAI Whisper API (`whisper-1` model)
3. Shows the transcribed text as a confirmation message with inline buttons:
   `[✅ Send]` `[✏️ Edit]` `[❌ Cancel]`
4. On `[✅ Send]`: forwards transcribed text to the tmux window
5. On `[✏️ Edit]`: asks user to type correction, then forwards
6. On `[❌ Cancel]`: deletes confirmation message, does nothing
7. Language auto-detection (no hardcoded language)
8. Works for all providers (Claude, Codex, Gemini)
9. Graceful fallback if Whisper API key not configured (clear error message)

## Configuration

New env var: `OPENAI_API_KEY` (already common) or `WHISPER_API_KEY` for
dedicated key. Endpoint: `https://api.openai.com/v1/audio/transcriptions`.

## Implementation Notes

- `python-telegram-bot` provides `Update.message.voice` with `file_id`
- Download via `bot.get_file(file_id)` → stream OGG bytes
- POST multipart to Whisper API with `model=whisper-1`
- Add new handler in `bot.py` for `filters.VOICE`
- Confirmation flow uses callback data (under 64 bytes): `va:confirm:<msg_id>`,
  `va:cancel:<msg_id>`
- Transcribed text stored in `context.user_data` keyed by msg_id for Edit flow
- Cost: ~$0.006/min (negligible for typical voice notes < 30s)

## Similar Art

- `n3d1117/chatgpt-telegram-bot` — voice via Whisper, nearly identical flow
- OpenClaw (this machine) already has Whisper configured and working

## Constraints

- Whisper API is external — requires internet + key
- Must not block the bot event loop (download + API call in async handler)
- Keep under Telegram's 20 MB file download limit (voice notes are tiny)
