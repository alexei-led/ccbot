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
