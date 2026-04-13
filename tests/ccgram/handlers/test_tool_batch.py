import pytest

from ccgram.handlers.tool_batch import (
    BATCH_MAX_ENTRIES,
    BATCH_MAX_LENGTH,
    ToolBatch,
    ToolBatchEntry,
    _batch_result_prefix,
    _extract_task_create_title,
    format_batch_message,
    is_batch_eligible,
)


class TestFormatBatchMessage:
    def test_single_entry_pending(self) -> None:
        entries = [ToolBatchEntry(tool_use_id="t1", tool_use_text="Read src/foo.py")]
        result = format_batch_message(entries)
        assert result.startswith("\u26a1 1 tool call")
        assert "Read src/foo.py" in result
        assert "\u23f3" in result

    def test_single_entry_with_result(self) -> None:
        entries = [
            ToolBatchEntry(
                tool_use_id="t1",
                tool_use_text="Read src/foo.py",
                tool_result_text="42 lines",
            )
        ]
        result = format_batch_message(entries)
        assert "1 tool call" in result
        assert "42 lines" in result
        assert "\u23f3" not in result

    def test_multiple_entries(self) -> None:
        entries = [
            ToolBatchEntry(tool_use_id="t1", tool_use_text="Read src/foo.py"),
            ToolBatchEntry(tool_use_id="t2", tool_use_text="Edit src/bar.py"),
            ToolBatchEntry(tool_use_id="t3", tool_use_text="Bash make test"),
        ]
        result = format_batch_message(entries)
        assert "3 tool calls" in result

    def test_subagent_label_included(self) -> None:
        entries = [ToolBatchEntry(tool_use_id="t1", tool_use_text="Read src/foo.py")]
        result = format_batch_message(entries, subagent_label="\U0001f916 write-tests")
        assert "\U0001f916 write-tests" in result

    def test_task_create_batch_renders_numbered_list(self) -> None:
        entries = [
            ToolBatchEntry(
                tool_use_id="t1",
                tool_use_text="**TaskCreate** `Build the widget`",
                tool_name="TaskCreate",
            ),
            ToolBatchEntry(
                tool_use_id="t2",
                tool_use_text="**TaskCreate** `Test the widget`",
                tool_name="TaskCreate",
            ),
        ]
        result = format_batch_message(entries)
        assert "Creating 2 tasks" in result
        assert "1. Build the widget" in result
        assert "2. Test the widget" in result

    def test_task_create_batch_completed(self) -> None:
        entries = [
            ToolBatchEntry(
                tool_use_id="t1",
                tool_use_text="**TaskCreate** `Build the widget`",
                tool_name="TaskCreate",
                tool_result_text="ok",
            ),
        ]
        result = format_batch_message(entries)
        assert "Created 1 task" in result


class TestExtractTaskCreateTitle:
    def test_markdown_format(self) -> None:
        entry = ToolBatchEntry(
            tool_use_id="t1",
            tool_use_text="**TaskCreate** `Build the widget`",
        )
        assert _extract_task_create_title(entry) == "Build the widget"

    def test_plain_format(self) -> None:
        entry = ToolBatchEntry(
            tool_use_id="t1",
            tool_use_text="TaskCreate Build the widget",
        )
        assert _extract_task_create_title(entry) == "Build the widget"

    def test_fallback_raw_text(self) -> None:
        entry = ToolBatchEntry(
            tool_use_id="t1",
            tool_use_text="something else entirely",
        )
        assert _extract_task_create_title(entry) == "something else entirely"

    def test_empty_text(self) -> None:
        entry = ToolBatchEntry(tool_use_id="t1", tool_use_text="")
        assert _extract_task_create_title(entry) == ""


class TestIsBatchEligible:
    def _make_task(self, task_type: str = "content", content_type: str = "text"):
        from ccgram.handlers.message_queue import MessageTask

        return MessageTask(task_type=task_type, content_type=content_type)  # type: ignore[arg-type]

    @pytest.mark.parametrize("content_type", ["tool_use", "tool_result"])
    def test_tool_types_eligible_with_batched_window(
        self, content_type: str, monkeypatch
    ) -> None:
        from ccgram.handlers import tool_batch

        monkeypatch.setattr(tool_batch, "_should_batch", lambda _wid: True)
        task = self._make_task(content_type=content_type)
        assert is_batch_eligible(task, "@0") is True

    @pytest.mark.parametrize("content_type", ["text", "thinking", "status"])
    def test_non_tool_types_not_eligible(self, content_type: str, monkeypatch) -> None:
        from ccgram.handlers import tool_batch

        monkeypatch.setattr(tool_batch, "_should_batch", lambda _wid: True)
        task = self._make_task(content_type=content_type)
        assert is_batch_eligible(task, "@0") is False

    def test_not_eligible_when_batch_mode_disabled(self, monkeypatch) -> None:
        from ccgram.handlers import tool_batch

        monkeypatch.setattr(tool_batch, "_should_batch", lambda _wid: False)
        task = self._make_task(content_type="tool_use")
        assert is_batch_eligible(task, "@0") is False


class TestBatchResultPrefix:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("All tests passed", "\u2705"),
            ("success", "\u2705"),
            ("exit code 0", "\u2705"),
            ("error: file not found", "\u274c"),
            ("FAILED test_foo", "\u274c"),
            ("exit code 1", "\u274c"),
            ("42 lines", "\u23bf"),
            ("ok", "\u23bf"),
        ],
    )
    def test_prefix_selection(self, text: str, expected: str) -> None:
        assert _batch_result_prefix(text) == expected


class TestBatchDataStructures:
    def test_tool_batch_entry_defaults(self) -> None:
        entry = ToolBatchEntry(tool_use_id="t1", tool_use_text="Read foo.py")
        assert entry.tool_result_text is None
        assert entry.tool_name is None

    def test_tool_batch_defaults(self) -> None:
        batch = ToolBatch(window_id="@0", thread_id=42)
        assert batch.entries == []
        assert batch.telegram_msg_id is None
        assert batch.total_length == 0

    def test_constants(self) -> None:
        assert BATCH_MAX_ENTRIES == 10
        assert BATCH_MAX_LENGTH == 2800
