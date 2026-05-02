from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "lint_lazy_imports.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("lint_lazy_imports", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["lint_lazy_imports"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lint_module():
    return _load_module()


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def test_documented_lazy_import_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "documented.py",
        """
        def fn():
            # Lazy: avoid cycle with handlers.foo
            from .foo import bar
            return bar
        """,
    )
    assert lint_module.find_violations(path) == []


def test_undocumented_lazy_import_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "undocumented.py",
        """
        def fn():
            from .foo import bar
            return bar
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_type_checking_block_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "type_checking.py",
        """
        from typing import TYPE_CHECKING

        def fn():
            if TYPE_CHECKING:
                from .foo import bar
            return None
        """,
    )
    assert lint_module.find_violations(path) == []


def test_reset_for_testing_function_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "reset_helper.py",
        """
        def _reset_state_for_testing():
            from .foo import bar
            return bar

        def reset_for_testing():
            from .baz import qux
            return qux
        """,
    )
    assert lint_module.find_violations(path) == []


def test_module_level_import_ignored(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "module_level.py",
        """
        from .foo import bar

        def fn():
            return bar
        """,
    )
    assert lint_module.find_violations(path) == []


def test_method_inside_class_lazy_import_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "method.py",
        """
        class Widget:
            def fn(self):
                from .foo import bar
                return bar
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1


def test_documented_import_in_method_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "documented_method.py",
        """
        class Widget:
            def fn(self):
                # Lazy: cycle with handlers.foo
                from .foo import bar
                return bar
        """,
    )
    assert lint_module.find_violations(path) == []


def test_async_function_undocumented_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "async_fn.py",
        """
        async def fn():
            from .foo import bar
            return bar
        """,
    )
    assert len(lint_module.find_violations(path)) == 1


def test_main_returns_zero_when_clean(lint_module, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "clean.py",
        """
        def fn():
            # Lazy: ok
            from .foo import bar
            return bar
        """,
    )
    rc = lint_module.main(["lint_lazy_imports.py", str(tmp_path)])
    assert rc == 0


def test_main_returns_one_when_violations(lint_module, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "dirty.py",
        """
        def fn():
            from .foo import bar
            return bar
        """,
    )
    rc = lint_module.main(["lint_lazy_imports.py", str(tmp_path)])
    assert rc == 1


def test_undocumented_import_in_try_body_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "try_body.py",
        """
        def fn():
            try:
                from .foo import bar
                return bar
            except ImportError:
                return None
        """,
    )
    assert len(lint_module.find_violations(path)) == 1


def test_documented_import_in_try_body_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "try_body_ok.py",
        """
        def fn():
            try:
                # Lazy: optional dep
                from .foo import bar
                return bar
            except ImportError:
                return None
        """,
    )
    assert lint_module.find_violations(path) == []


def test_undocumented_import_in_except_body_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "except_body.py",
        """
        def fn():
            try:
                pass
            except ValueError:
                from .foo import bar
                return bar
        """,
    )
    assert len(lint_module.find_violations(path)) == 1


def test_undocumented_import_in_finally_body_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "finally_body.py",
        """
        def fn():
            try:
                pass
            finally:
                from .foo import bar
        """,
    )
    assert len(lint_module.find_violations(path)) == 1


def test_undocumented_import_in_if_body_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "if_body.py",
        """
        def fn(flag):
            if flag:
                from .foo import bar
                return bar
            return None
        """,
    )
    assert len(lint_module.find_violations(path)) == 1


def test_undocumented_import_in_with_body_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "with_body.py",
        """
        def fn(handle):
            with handle:
                from .foo import bar
                return bar
        """,
    )
    assert len(lint_module.find_violations(path)) == 1


def test_undocumented_import_in_for_body_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "for_body.py",
        """
        def fn(items):
            for item in items:
                from .foo import bar
                return bar
        """,
    )
    assert len(lint_module.find_violations(path)) == 1


def test_undocumented_import_in_while_body_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "while_body.py",
        """
        def fn(cond):
            while cond:
                from .foo import bar
                return bar
        """,
    )
    assert len(lint_module.find_violations(path)) == 1


def test_undocumented_import_in_nested_try_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "nested.py",
        """
        def fn(x):
            if x:
                try:
                    from .foo import bar
                    return bar
                except OSError:
                    pass
        """,
    )
    assert len(lint_module.find_violations(path)) == 1


def test_multiline_lazy_comment_block_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "multi_comment.py",
        """
        def fn():
            # Lazy: this annotation wraps over multiple lines because the
            # cycle reason needs more than one line of explanation to be
            # comprehensible to future readers.
            from .foo import bar
            return bar
        """,
    )
    assert lint_module.find_violations(path) == []


def test_lazy_above_blank_line_then_import_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "blank_separator.py",
        """
        def fn():
            # Lazy: still applies despite blank separator below.

            from .foo import bar
            return bar
        """,
    )
    assert lint_module.find_violations(path) == []


def test_non_comment_line_breaks_lazy_walk(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "broken_walk.py",
        """
        def fn():
            # Lazy: this annotation is for the FIRST import below.
            from .foo import bar

            from .baz import qux
            return bar, qux
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .baz import qux" in violations[0][1]


def test_nested_function_import_is_caught(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "nested_fn.py",
        """
        def outer():
            def inner():
                from .foo import bar
                return bar
            return inner
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_nested_function_lazy_import_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "nested_fn_lazy.py",
        """
        def outer():
            def inner():
                # Lazy: documented inside nested function
                from .foo import bar
                return bar
            return inner
        """,
    )
    assert lint_module.find_violations(path) == []


def test_try_star_import_is_caught(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "try_star.py",
        """
        def fn():
            try:
                x = 1
            except* ValueError:
                from .foo import bar
                return bar
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_try_star_lazy_import_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "try_star_lazy.py",
        """
        def fn():
            try:
                x = 1
            except* ValueError:
                # Lazy: documented inside except* handler
                from .foo import bar
                return bar
        """,
    )
    assert lint_module.find_violations(path) == []


def test_method_inside_function_class_is_caught(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "fn_class_method.py",
        """
        def outer():
            class Inner:
                def method(self):
                    from .foo import bar
                    return bar
            return Inner
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_method_inside_nested_class_is_caught(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "nested_class_method.py",
        """
        class Outer:
            class Inner:
                def method(self):
                    from .foo import bar
                    return bar
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_method_inside_doubly_nested_function_class_is_caught(
    lint_module, tmp_path: Path
) -> None:
    path = _write(
        tmp_path,
        "doubly_nested.py",
        """
        def outer():
            class Inner:
                class InnerInner:
                    def method(self):
                        from .foo import bar
                        return bar
            return Inner
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_nested_class_lazy_import_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "nested_class_lazy.py",
        """
        class Outer:
            class Inner:
                def method(self):
                    # Lazy: documented inside nested class
                    from .foo import bar
                    return bar
        """,
    )
    assert lint_module.find_violations(path) == []


def test_undocumented_import_in_match_case_fails(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "match_case.py",
        """
        def fn(x):
            match x:
                case 1:
                    from .foo import bar
                    return bar
                case _:
                    return None
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_top_level_type_checking_else_branch_caught(
    lint_module, tmp_path: Path
) -> None:
    path = _write(
        tmp_path,
        "tc_else.py",
        """
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            pass
        else:
            def fn():
                from .foo import bar
                return bar
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_class_body_control_flow_caught(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "class_if.py",
        """
        FLAG = True

        class Outer:
            if FLAG:
                def method(self):
                    from .foo import bar
                    return bar
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_class_body_try_block_caught(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "class_try.py",
        """
        class Outer:
            try:
                pass
            except Exception:
                def method(self):
                    from .foo import bar
                    return bar
        """,
    )
    violations = lint_module.find_violations(path)
    assert len(violations) == 1
    assert "from .foo import bar" in violations[0][1]


def test_documented_import_in_match_case_passes(lint_module, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "match_case_lazy.py",
        """
        def fn(x):
            match x:
                case 1:
                    # Lazy: optional path for specific case
                    from .foo import bar
                    return bar
                case _:
                    return None
        """,
    )
    assert lint_module.find_violations(path) == []
