# Telegram Bot Advanced Features Research

## 1. Telegram Bot API Feature Overview

### 1.1 Rich Text & Formatting

| Feature | Description |
|---------|-------------|
| **MarkdownV2 parse_mode** | Bold `*`, italic `_`, underline `__`, strikethrough `~`, spoiler `\|\|`, code `` ` ``, code block `` ``` ``, links `[text](url)`. Special chars must be escaped |
| **HTML parse_mode** | `<b>`, `<i>`, `<u>`, `<s>`, `<code>`, `<pre>`, `<pre language="python">` syntax highlighting, `<blockquote>`, `<tg-spoiler>` |
| **Expandable Blockquote** | `<blockquote expandable>` in HTML / `**>` in MarkdownV2 — collapsed by default, tap to expand (Bot API 7.3+) |
| **Spoiler text** | Hidden text revealed on tap: `\|\|spoiler\|\|` in MarkdownV2, `<tg-spoiler>` in HTML |
| **Custom Emoji** | `<tg-emoji emoji-id="...">` in HTML — use premium custom emoji inline |
| **MessageEntity** | Structured entity objects: mention, hashtag, URL, code, pre, text_link, custom_emoji, blockquote, expandable_blockquote, etc. |
| **link_preview_options** | Control link previews: disable, prefer small/large media, position above/below text (Bot API 7.0+) |

### 1.2 Interactive Components

| Feature | Description |
|---------|-------------|
| **InlineKeyboardMarkup** | Inline buttons attached to messages. Button types: callback_data, url, web_app, login_url, switch_inline_query, pay, copy_text |
| **ReplyKeyboardMarkup** | Persistent keyboard at the bottom, supports resize, one_time, input_field_placeholder |
| **ReplyKeyboardRemove** | Remove a previously sent ReplyKeyboardMarkup |
| **callback_query.answer(text, show_alert)** | Toast notification or modal alert after button click. Must be called within 10 seconds |
| **copy_text button** | InlineKeyboardButton with `copy_text` field — one-tap copy to clipboard (Bot API 7.10+) |
| **WebApp (Mini App)** | Embed web pages via `WebAppInfo`. Support for keyboard button, inline button, menu button modes |

### 1.3 Media & Files

| Feature | Description |
|---------|-------------|
| **sendPhoto / sendDocument / sendAnimation** | Send images, files, GIFs with optional caption |
| **sendVideo / sendAudio / sendVoice / sendVideoNote** | Video, audio, voice messages, video notes (circles) |
| **sendMediaGroup** | Album-mode batch send (2-10 items). Supports photos, videos, documents, audio |
| **sendSticker** | Send static/animated/video stickers |
| **sendPaidMedia** | Send media behind Telegram Star paywall (Bot API 7.6+) |
| **InputMediaPhoto / InputMediaDocument** | Edit media of sent messages via `editMessageMedia` |
| **sendDice** | Send animated emoji dice (🎲🎯🏀⚽🎳🎰) |

### 1.4 Conversation Management

| Feature | Description |
|---------|-------------|
| **ConversationHandler** | python-telegram-bot multi-step state machine dialog (library feature, not Bot API) |
| **send_chat_action("typing")** | "Typing..." status indicator. Auto-expires after 5 seconds, must resend for longer operations |
| **reply_parameters** | Reply to messages with optional quote text. Replaces old `reply_to_message_id` parameter (Bot API 7.0+) |
| **pin_chat_message / unpin** | Pin messages to top of chat. `unpin_all_chat_messages` to clear all |
| **forwardMessage / forwardMessages** | Forward single/multiple messages. `copyMessage` / `copyMessages` forwards without source attribution |
| **deleteMessage / deleteMessages** | Delete single or multiple messages at once |
| **message_effect_id** | Add visual effect animation to sent messages (Bot API 7.5+) |

### 1.5 Inline Mode

| Feature | Description |
|---------|-------------|
| **InlineQueryHandler** | @bot triggers search in any chat. Returns up to 50 results |
| **ChosenInlineResultHandler** | Track which result the user selected (requires /setinlinefeedback via BotFather) |
| **switch_inline_query_chosen_chat** | Button that opens inline query in a specific chat type |

### 1.6 Bot Commands & Menu

| Feature | Description |
|---------|-------------|
| **BotCommand + set_my_commands** | Register `/` command menu. Supports per-language and per-scope (all chats, group, private) |
| **MenuButton** | Custom bottom-left menu button: default, commands list, or web_app |
| **BotName / BotDescription / BotShortDescription** | Programmatically set bot name, description, and short description per language |

### 1.7 Message Editing & Lifecycle

| Feature | Description |
|---------|-------------|
| **editMessageText** | Edit text of sent messages. Supports parse_mode, inline_keyboard |
| **editMessageMedia** | Replace attached media |
| **editMessageCaption** | Modify caption |
| **editMessageReplyMarkup** | Update inline keyboard only |
| **deleteMessage / deleteMessages** | Remove messages (bot's own or in groups with admin rights) |

### 1.8 Message Streaming (Bot API 9.3+, Dec 2025)

| Feature | Description |
|---------|-------------|
| **sendMessageDraft** | Stream partial messages while generating — the message is progressively updated. Ideal for AI/LLM bots that produce long responses incrementally |

### 1.9 Forum Topics

| Feature | Description |
|---------|-------------|
| **Forum Topics** | Group superchats can enable topics. Bots can create/edit/close/reopen/delete topics |
| **Topics in Private Chats** | Bots can enable forum mode in private chats (`has_topics_enabled` on User). Messages support `message_thread_id` (Bot API 9.3+) |

### 1.10 Payments & Stars

| Feature | Description |
|---------|-------------|
| **sendInvoice** | Send payment invoices to users |
| **Telegram Stars** | Digital currency for in-app payments. `getMyStarBalance` to check balance (Bot API 9.1+) |
| **sendPaidMedia** | Content behind Star paywall (up to 25,000 Stars, Bot API 9.3+) |

### 1.11 Other Capabilities

| Feature | Description |
|---------|-------------|
| **Message Reactions** | `setMessageReaction` — set emoji/custom emoji reactions on messages (Bot API 7.2+) |
| **sendPoll** | Polls with up to 12 options (expanded from 10 in Bot API 9.1+), quiz mode with explanations |
| **Checklists** | `sendChecklist` / `editMessageChecklist` — structured task lists (Bot API 9.1+) |
| **Job Queue** | python-telegram-bot scheduled/delayed tasks (library feature, not Bot API) |
| **Webhook / getUpdates** | Two modes for receiving updates |

---

## 2. Feature Implementation Status in ccbot

### Already Implemented

| Feature | Status | Notes |
|---------|--------|-------|
| **MarkdownV2 formatting** | ✅ | All messages use MarkdownV2 via `telegramify-markdown` with plaintext fallback |
| **send_chat_action("typing")** | ✅ | Shown while processing user messages and during long operations |
| **InlineKeyboardMarkup** | ✅ | Used extensively: session list, history pagination, directory browser, interactive UI, screenshot refresh |
| **callback_query.answer()** | ✅ | Instant feedback on all callback button clicks |
| **editMessageText** | ✅ | Status-to-content conversion, tool_result editing into tool_use messages |
| **editMessageMedia** | ✅ | Screenshot refresh replaces image in-place |
| **deleteMessage** | ✅ | Status message cleanup, interactive UI cleanup |
| **BotCommand + set_my_commands** | ✅ | 10 commands registered: /start, /list, /history, /screenshot, /esc + 5 Claude Code forwards |
| **sendDocument** | ✅ | Screenshots sent as PNG documents |
| **ReplyKeyboardRemove** | ✅ | Used when switching away from reply keyboard |
| **Claude Code command forwarding** | ✅ | /clear, /compact, /cost, /help, /memory forwarded to tmux |
| **Message rate limiting** | ✅ | 1.1s minimum interval per user to avoid flood control |
| **Per-user message queues** | ✅ | FIFO ordering, content/status task separation, message merging |
| **Status message deduplication** | ✅ | Skip edit if status text unchanged |

### Potential Improvements (Prioritized)

| # | Feature | Impact | Effort | Notes |
|---|---------|--------|--------|-------|
| 1 | **sendMessageDraft (streaming)** | High | Medium | Stream Claude's responses progressively instead of waiting for complete messages. Bot API 9.3+ required. Would significantly improve perceived responsiveness |
| 2 | **Expandable blockquote for thinking** | Medium | Low | Wrap Claude's thinking/reasoning in `<blockquote expandable>` for cleaner layout. Replaces spoiler approach — better UX since content is visible on tap without losing context |
| 3 | **reply_parameters with quote** | Medium | Low | Quote the specific user message when replying, providing clear message association |
| 4 | **copy_text button** | Medium | Low | Add "Copy" button to code block messages for one-tap clipboard copy |
| 5 | **link_preview_options** | Low | Low | Disable or minimize link previews in Claude's responses to reduce visual noise |
| 6 | **message_effect_id** | Low | Low | Add subtle animation effects on completion or error messages |
| 7 | **Forum Topics in Private Chat** | Medium | High | Organize per-session conversations as topics in a single private chat instead of interleaving |
| 8 | **Checklists** | Low | Medium | Display Claude's task lists as native Telegram checklists |
| 9 | **WebApp dashboard** | Medium | High | Real-time terminal view, session management UI via Mini App |
| 10 | **pinChatMessage** | Low | Low | Pin summary or active session info |

---

## 3. Claude Code Slash Commands

### Currently Forwarded by ccbot

These 5 commands are registered in the Telegram bot menu and forwarded to Claude Code via tmux:

| Command | Bot Menu Description | Function |
|---------|---------------------|----------|
| `/clear` | ↗ Clear conversation history | Wipes conversation, starts fresh. ccbot also clears session association |
| `/compact` | ↗ Compact conversation context | Summarize/compress context to free token budget. Supports optional instructions |
| `/cost` | ↗ Show token/cost usage | Display token counts and API cost for current session |
| `/help` | ↗ Show Claude Code help | List available commands and usage help |
| `/memory` | ↗ Edit CLAUDE.md | Open CLAUDE.md for editing project instructions |

### Other Claude Code Commands (Full Reference)

| Command | Parameterless | Interactive | Suitable for Telegram | Notes |
|---------|:---:|:---:|:---:|-------|
| `/context` | ✅ | No | ✅ Recommended | Show context window usage. Useful for monitoring |
| `/status` | ✅ | No | ✅ Possible | Show project/session status |
| `/review` | ✅ | No | ⚠️ Caution | Starts code review — may produce very long output |
| `/init` | ✅ | Possibly | ⚠️ Caution | Initialize CLAUDE.md — may prompt for confirmation |
| `/doctor` | ✅ | No | ⚠️ Caution | Diagnose environment — output can be lengthy |
| `/stats` | ✅ | No | ❌ No | Shows terminal graphs/charts, not renderable via Telegram |
| `/rewind` | No | Yes (selection) | ❌ No | Interactive message selector — requires terminal UI |
| `/resume` | No | Yes (selection) | ❌ No | Interactive session picker — requires terminal UI |
| `/rename` | No (needs name) | No | ⚠️ Possible | Needs parameter: `/rename new-name` |
| `/permissions` | ✅ | Yes | ❌ No | Interactive permission management |
| `/hooks` | ✅ | Yes | ❌ No | Interactive hook configuration |
| `/agents` | ✅ | Yes | ❌ No | Interactive agent management |
| `/login` | ✅ | Yes (browser) | ❌ No | Opens browser for authentication |
| `/logout` | ✅ | No | ⚠️ Caution | Logs out — destructive, should not be easily accessible |

### Recommendations for Additional Forwarding

Consider adding `/context` to CC_COMMANDS — it is parameterless, non-interactive, and provides useful context window usage info that complements `/cost`.

---

## 4. Telegram Bot API Version Reference

| Version | Date | Key Features for Bots |
|---------|------|----------------------|
| 7.0 | Dec 2023 | `reply_parameters`, `link_preview_options`, reactions |
| 7.2 | Mar 2024 | `setMessageReaction`, business connections |
| 7.3 | May 2024 | Expandable blockquotes |
| 7.5 | Jun 2024 | Message effects, paid media |
| 7.10 | Sep 2024 | `copy_text` button |
| 8.0 | Nov 2024 | Gifts, verified accounts |
| 9.0 | Mar 2025 | Business branding, Star transactions |
| 9.1 | Jul 2025 | Checklists, 12-option polls, `getMyStarBalance` |
| 9.2 | Aug 2025 | Suggested posts, direct messages in channels |
| 9.3 | Dec 2025 | **`sendMessageDraft` (streaming)**, topics in private chats, gift upgrades |

Sources: [Bot API Changelog](https://core.telegram.org/bots/api-changelog), [Bot API Documentation](https://core.telegram.org/bots/api)
