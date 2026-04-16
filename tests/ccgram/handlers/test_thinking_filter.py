import pytest

from ccgram.handlers.message_routing import _MIN_THINKING_LENGTH


def _should_skip_thinking(text: str | None) -> bool:
    """Replicate the thinking filter logic from bot.handle_new_message."""
    stripped = (text or "").strip()
    return len(stripped) < _MIN_THINKING_LENGTH


class TestThinkingFilter:
    @pytest.mark.parametrize(
        ("text", "expected_skip"),
        [
            ("(thinking)", True),
            ("", True),
            (None, True),
            ("   ", True),
            ("short", True),
            ("a" * 19, True),
            ("a" * 20, False),
            ("This is a substantial thinking block with reasoning", False),
            ("Let me analyze the code structure and find the bug", False),
        ],
    )
    def test_trivial_thinking_skipped(self, text: str | None, expected_skip: bool):
        assert _should_skip_thinking(text) == expected_skip

    def test_min_thinking_length_is_reasonable(self):
        assert 10 <= _MIN_THINKING_LENGTH <= 50
