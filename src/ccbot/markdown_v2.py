"""Markdown → Telegram MarkdownV2 conversion layer.

Wraps `telegramify_markdown` and adds special handling for expandable
blockquotes (delimited by sentinel tokens from TranscriptParser).
Expandable quotes are escaped and formatted as Telegram >…|| syntax
separately, so the library doesn't mangle them.

Key function: convert_markdown(text) → MarkdownV2 string.
"""

import re

import telegramify_markdown

from .transcript_parser import TranscriptParser

_EXPQUOTE_RE = re.compile(
    re.escape(TranscriptParser.EXPANDABLE_QUOTE_START)
    + r"([\s\S]*?)"
    + re.escape(TranscriptParser.EXPANDABLE_QUOTE_END)
)

# Characters that must be escaped in Telegram MarkdownV2 plain text
_MDV2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def _escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _MDV2_ESCAPE_RE.sub(r"\\\1", text)


# Max rendered chars for a single expandable quote block.
# Leaves room for surrounding text within Telegram's 4096 char message limit.
_EXPQUOTE_MAX_RENDERED = 3800


def _render_expandable_quote(m: re.Match[str]) -> str:
    """Render an expandable blockquote block in raw MarkdownV2.

    Truncates the rendered output to _EXPQUOTE_MAX_RENDERED chars
    to ensure the final message fits within Telegram's 4096 limit.
    """
    inner = m.group(1)
    escaped = _escape_mdv2(inner)
    lines = escaped.split("\n")
    # Build quoted lines, truncating if needed to stay within budget
    built: list[str] = []
    total_len = 0
    suffix = "\n>… \\(truncated\\)||"
    budget = _EXPQUOTE_MAX_RENDERED - len(suffix)
    truncated = False
    for line in lines:
        # +1 for ">" prefix, +1 for "\n" separator
        line_cost = 1 + len(line) + 1
        if total_len + line_cost > budget:
            # Try to fit a partial line
            remaining = budget - total_len - 2  # -2 for ">" and "\n"
            if remaining > 20:
                built.append(f">{line[:remaining]}")
            truncated = True
            break
        built.append(f">{line}")
        total_len += line_cost
    if truncated:
        return "\n".join(built) + suffix
    return "\n".join(built) + "||"


def convert_markdown(text: str) -> str:
    """Convert standard Markdown to Telegram MarkdownV2 format.

    Expandable blockquote sections (marked by sentinel tokens from
    TranscriptParser) are extracted, escaped, and formatted separately
    so that telegramify_markdown doesn't mangle the >...|| syntax.
    """
    # Extract expandable quote blocks before telegramify
    segments: list[tuple[bool, str]] = []  # (is_quote, content)
    last_end = 0
    for m in _EXPQUOTE_RE.finditer(text):
        if m.start() > last_end:
            segments.append((False, text[last_end : m.start()]))
        segments.append((True, m.group(0)))
        last_end = m.end()
    if last_end < len(text):
        segments.append((False, text[last_end:]))

    if not segments:
        return telegramify_markdown.markdownify(text, normalize_whitespace=False)

    parts: list[str] = []
    for is_quote, segment in segments:
        if is_quote:
            parts.append(_EXPQUOTE_RE.sub(_render_expandable_quote, segment))
        else:
            parts.append(
                telegramify_markdown.markdownify(segment, normalize_whitespace=False)
            )
    return "".join(parts)
