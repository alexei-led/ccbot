import pytest

from ccgram.claude_task_state import (
    classify_wait_message,
    claude_task_state,
    get_claude_task_snapshot,
)


def _assistant_tool_use(tool_id: str, name: str, input_data: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": name,
                    "input": input_data,
                }
            ]
        },
    }


def _user_tool_result(
    tool_use_id: str,
    *,
    content: str = "",
    tool_use_result: dict | None = None,
) -> dict:
    entry: dict = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                }
            ]
        },
    }
    if tool_use_result is not None:
        entry["toolUseResult"] = tool_use_result
    return entry


class TestClaudeTaskStateStore:
    def test_task_create_then_result_creates_snapshot(self) -> None:
        changed = claude_task_state.apply_entries(
            "@0",
            "session-1",
            [
                _assistant_tool_use(
                    "tool-1",
                    "TaskCreate",
                    {
                        "subject": "Review architecture",
                        "description": "Inspect current layering",
                        "activeForm": "Reviewing architecture",
                    },
                ),
                _user_tool_result(
                    "tool-1",
                    content="Task #1 created successfully",
                    tool_use_result={
                        "task": {"id": "1", "subject": "Review architecture"}
                    },
                ),
            ],
        )

        assert changed is True
        snapshot = get_claude_task_snapshot("@0")
        assert snapshot is not None
        assert snapshot.total_count == 1
        assert snapshot.open_count == 1
        assert snapshot.items[0].task_id == "1"
        assert snapshot.items[0].subject == "Review architecture"
        assert snapshot.items[0].active_form == "Reviewing architecture"

    def test_task_update_changes_status_and_blockers(self) -> None:
        claude_task_state.apply_entries(
            "@0",
            "session-1",
            [
                _assistant_tool_use(
                    "tool-1",
                    "TaskCreate",
                    {
                        "subject": "Task one",
                        "description": "Desc one",
                        "activeForm": "Doing task one",
                    },
                ),
                _user_tool_result(
                    "tool-1",
                    tool_use_result={"task": {"id": "1", "subject": "Task one"}},
                ),
            ],
        )

        changed = claude_task_state.apply_entries(
            "@0",
            "session-1",
            [
                _assistant_tool_use(
                    "tool-2",
                    "TaskUpdate",
                    {
                        "taskId": "1",
                        "status": "in_progress",
                        "addBlockedBy": ["7"],
                    },
                )
            ],
        )

        assert changed is True
        snapshot = get_claude_task_snapshot("@0")
        assert snapshot is not None
        assert snapshot.active_task_id == "1"
        assert snapshot.items[0].status == "in_progress"
        assert snapshot.items[0].blocked_by == ("7",)

        claude_task_state.apply_entries(
            "@0",
            "session-1",
            [
                _assistant_tool_use(
                    "tool-3",
                    "TaskUpdate",
                    {
                        "taskId": "1",
                        "status": "completed",
                        "removeBlockedBy": ["7"],
                    },
                )
            ],
        )

        snapshot = get_claude_task_snapshot("@0")
        assert snapshot is not None
        assert snapshot.done_count == 1
        assert snapshot.open_count == 0
        assert snapshot.items[0].blocked_by == ()

    def test_task_list_replaces_existing_snapshot(self) -> None:
        claude_task_state.apply_entries(
            "@0",
            "session-1",
            [
                _assistant_tool_use(
                    "tool-1",
                    "TaskCreate",
                    {"subject": "Old task", "description": "", "activeForm": ""},
                ),
                _user_tool_result(
                    "tool-1",
                    tool_use_result={"task": {"id": "1", "subject": "Old task"}},
                ),
            ],
        )

        changed = claude_task_state.apply_entries(
            "@0",
            "session-1",
            [
                _assistant_tool_use("tool-list", "TaskList", {}),
                _user_tool_result(
                    "tool-list",
                    content="#2 [pending] Aggregate findings [blocked by #1]",
                    tool_use_result={
                        "tasks": [
                            {
                                "id": "1",
                                "subject": "Collect findings",
                                "status": "completed",
                                "blockedBy": [],
                            },
                            {
                                "id": "2",
                                "subject": "Aggregate findings",
                                "status": "pending",
                                "blockedBy": ["1"],
                                "owner": "reviewer",
                            },
                        ]
                    },
                ),
            ],
        )

        assert changed is True
        snapshot = get_claude_task_snapshot("@0")
        assert snapshot is not None
        assert [item.task_id for item in snapshot.items] == ["1", "2"]
        assert snapshot.done_count == 1
        assert snapshot.items[1].blocked_by == ("1",)
        assert snapshot.items[1].owner == "reviewer"

    def test_todowrite_replaces_snapshot(self) -> None:
        changed = claude_task_state.apply_entries(
            "@0",
            "session-1",
            [
                _assistant_tool_use(
                    "todo-1",
                    "TodoWrite",
                    {
                        "todos": [
                            {
                                "content": "Investigate regression",
                                "status": "completed",
                            },
                            {
                                "content": "Write tests",
                                "status": "in_progress",
                                "activeForm": "Writing tests",
                            },
                        ]
                    },
                )
            ],
        )

        assert changed is True
        snapshot = get_claude_task_snapshot("@0")
        assert snapshot is not None
        assert snapshot.total_count == 2
        assert snapshot.done_count == 1
        assert snapshot.active_task_id == "2"
        assert snapshot.items[1].active_form == "Writing tests"

    def test_session_change_replaces_old_snapshot(self) -> None:
        claude_task_state.apply_entries(
            "@0",
            "session-1",
            [
                _assistant_tool_use(
                    "tool-1",
                    "TaskCreate",
                    {"subject": "Old task", "description": "", "activeForm": ""},
                ),
                _user_tool_result(
                    "tool-1",
                    tool_use_result={"task": {"id": "1", "subject": "Old task"}},
                ),
            ],
        )

        claude_task_state.apply_entries(
            "@0",
            "session-2",
            [
                _assistant_tool_use(
                    "tool-2",
                    "TaskCreate",
                    {"subject": "New task", "description": "", "activeForm": ""},
                ),
                _user_tool_result(
                    "tool-2",
                    tool_use_result={"task": {"id": "9", "subject": "New task"}},
                ),
            ],
        )

        snapshot = get_claude_task_snapshot("@0")
        assert snapshot is not None
        assert [item.task_id for item in snapshot.items] == ["9"]

    def test_mark_task_completed_requires_matching_session(self) -> None:
        claude_task_state.apply_entries(
            "@0",
            "session-1",
            [
                _assistant_tool_use(
                    "tool-1",
                    "TaskCreate",
                    {"subject": "Task one", "description": "", "activeForm": ""},
                ),
                _user_tool_result(
                    "tool-1",
                    tool_use_result={"task": {"id": "1", "subject": "Task one"}},
                ),
            ],
        )

        assert claude_task_state.mark_task_completed("@0", "session-2", "1") is False
        assert claude_task_state.mark_task_completed("@0", "session-1", "1") is True

        snapshot = get_claude_task_snapshot("@0")
        assert snapshot is not None
        assert snapshot.done_count == 1


class TestClassifyWaitMessage:
    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Claude is waiting for your input", "Waiting for input"),
            ("Claude needs your permission to use Bash", "Approval needed: Bash"),
            (
                "Claude needs your permission to use Updated plan",
                "Plan approval needed",
            ),
            ("something else", None),
        ],
    )
    def test_classifies_wait_messages(self, message: str, expected: str | None) -> None:
        assert classify_wait_message(message) == expected
