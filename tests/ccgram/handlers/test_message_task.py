import ast
import dataclasses
from pathlib import Path

import pytest

from ccgram.handlers.message_task import (
    ContentTask,
    MessageTask,
    StatusClearTask,
    StatusUpdateTask,
    thread_key,
)


class TestContentTask:
    def test_is_frozen(self):
        task = ContentTask(window_id="@0", parts=("hello",))
        with pytest.raises(dataclasses.FrozenInstanceError):
            task.window_id = "@1"  # type: ignore[misc]

    def test_parts_is_tuple(self):
        task = ContentTask(window_id="@0", parts=("a", "b"))
        assert isinstance(task.parts, tuple)
        assert task.parts == ("a", "b")

    def test_defaults(self):
        task = ContentTask(window_id="@0", parts=("x",))
        assert task.content_type == "text"
        assert task.tool_use_id is None
        assert task.tool_name is None
        assert task.thread_id is None

    def test_tool_use_fields(self):
        task = ContentTask(
            window_id="@0",
            parts=("result",),
            content_type="tool_result",
            tool_use_id="tu_123",
            tool_name="Read",
        )
        assert task.content_type == "tool_result"
        assert task.tool_use_id == "tu_123"
        assert task.tool_name == "Read"

    def test_requires_window_id(self):
        with pytest.raises(TypeError):
            ContentTask(parts=("x",))  # type: ignore[call-arg]

    def test_requires_parts(self):
        with pytest.raises(TypeError):
            ContentTask(window_id="@0")  # type: ignore[call-arg]

    def test_hashable(self):
        task = ContentTask(window_id="@0", parts=("hello",))
        d = {task: 1}
        assert d[task] == 1


class TestStatusUpdateTask:
    def test_is_frozen(self):
        task = StatusUpdateTask(window_id="@0", text="working...")
        with pytest.raises(dataclasses.FrozenInstanceError):
            task.text = "done"  # type: ignore[misc]

    def test_optional_text(self):
        task = StatusUpdateTask(window_id="@0", text=None)
        assert task.text is None

    def test_defaults(self):
        task = StatusUpdateTask(window_id="@0", text="ok")
        assert task.thread_id is None


class TestStatusClearTask:
    def test_is_frozen(self):
        task = StatusClearTask(window_id="@0")
        with pytest.raises(dataclasses.FrozenInstanceError):
            task.window_id = "@1"  # type: ignore[misc]

    def test_optional_window_id(self):
        task = StatusClearTask(window_id=None)
        assert task.window_id is None

    def test_optional_thread_id(self):
        task = StatusClearTask(window_id="@0")
        assert task.thread_id is None


class TestMessageTaskUnion:
    def test_union_covers_all_variants(self):
        args = set(MessageTask.__args__)
        assert args == {ContentTask, StatusUpdateTask, StatusClearTask}

    def test_match_dispatches_all_three(self):
        tasks: list[MessageTask] = [
            ContentTask(window_id="@0", parts=("hi",)),
            StatusUpdateTask(window_id="@0", text="busy"),
            StatusClearTask(window_id="@0"),
        ]
        labels = []
        for t in tasks:
            match t:
                case ContentTask():
                    labels.append("content")
                case StatusUpdateTask():
                    labels.append("status_update")
                case StatusClearTask():
                    labels.append("status_clear")
        assert labels == ["content", "status_update", "status_clear"]


class TestThreadKey:
    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            (None, 0),
            (0, 0),
            (42, 42),
            (1, 1),
        ],
    )
    def test_normalises_thread_id(self, input_val, expected):
        assert thread_key(input_val) == expected


class TestModuleImports:
    def test_imports_nothing_from_handlers(self):
        src = Path("src/ccgram/handlers/message_task.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module and node.module.startswith("ccgram.handlers"):
                raise AssertionError(f"forbidden import: from {node.module}")
            if node.level and node.level > 0:
                mod = node.module or ""
                raise AssertionError(
                    f"forbidden relative import: from {'.' * node.level}{mod}"
                )
