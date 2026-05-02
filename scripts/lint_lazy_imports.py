"""Lint check that enforces the F6 lazy-import contract.

Walks every ``.py`` file under a source root, parses with ``ast``, and finds
every ``Import``/``ImportFrom`` node nested inside a function body. Each such
in-function import must be one of:

* preceded by a ``# Lazy: <reason>`` comment on the previous source line, or
* nested inside an ``if TYPE_CHECKING:`` block, or
* nested inside a function whose name matches ``_reset.*_for_testing`` /
  ``reset_for_testing``.

Any other in-function import is reported as undocumented and the script exits
non-zero. Run via ``make lint`` (chained off the ``lint-lazy`` target) or
directly: ``python scripts/lint_lazy_imports.py [path ...]``.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

_LAZY_COMMENT = re.compile(r"#\s*Lazy:")
_RESET_FN_NAME = re.compile(r"^_?reset.*_for_testing$")
_MIN_ARGV_FOR_PATHS = 2


def iter_python_files(root: Path) -> Iterator[Path]:
    """Yield every ``.py`` file beneath *root*, sorted for stable output."""
    yield from sorted(root.rglob("*.py"))


def _is_type_checking_test(node: ast.AST) -> bool:
    """Return True if *node* is a ``TYPE_CHECKING`` test for an ``if`` block."""
    if isinstance(node, ast.Name) and node.id == "TYPE_CHECKING":
        return True
    return isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"


def _has_lazy_comment_above(source_lines: list[str], lineno: int) -> bool:
    """Return True if a contiguous comment block above *lineno* contains ``# Lazy:``.

    Multi-line ``# Lazy: <reason>`` annotations are common — the marker sits on
    the first line of the block, the rest of the lines wrap the reason. Walking
    back through contiguous ``#``-prefixed lines (and blank separators) lets
    the lint accept that style without requiring the marker to be glued to the
    import.
    """
    idx = lineno - 2
    while idx >= 0:
        stripped = source_lines[idx].strip()
        if not stripped:
            idx -= 1
            continue
        if not stripped.startswith("#"):
            return False
        if _LAZY_COMMENT.search(stripped):
            return True
        idx -= 1
    return False


def _find_violations_in_function(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
    in_type_checking: bool,
) -> Iterator[tuple[int, str]]:
    """Walk *fn* recursively and yield ``(lineno, snippet)`` violations."""
    if _RESET_FN_NAME.match(fn.name):
        return
    yield from _walk_block(fn.body, source_lines, in_type_checking)


def _sub_bodies(stmt: ast.stmt) -> Iterator[list[ast.stmt]]:
    """Yield each statement-list body that *stmt* contains, if any.

    Covers compound statements (``Try``, ``TryStar``, ``With``, ``For``,
    ``While``, plain ``If``) so the lazy-import walker can recurse through
    control flow without losing function scope. ``If(TYPE_CHECKING)`` is
    handled by the caller.
    """
    if isinstance(stmt, ast.Try | ast.TryStar):
        yield stmt.body
        for handler in stmt.handlers:
            yield handler.body
        yield stmt.orelse
        yield stmt.finalbody
        return
    if isinstance(stmt, ast.If | ast.For | ast.AsyncFor | ast.While):
        yield stmt.body
        yield stmt.orelse
        return
    if isinstance(stmt, ast.With | ast.AsyncWith):
        yield stmt.body
        return
    if isinstance(stmt, ast.Match):
        for case in stmt.cases:
            yield case.body


def _check_import(
    stmt: ast.Import | ast.ImportFrom,
    source_lines: list[str],
    in_type_checking: bool,
) -> tuple[int, str] | None:
    """Return a violation tuple for *stmt* unless it is excused."""
    if in_type_checking:
        return None
    if _has_lazy_comment_above(source_lines, stmt.lineno):
        return None
    snippet = (
        source_lines[stmt.lineno - 1].strip()
        if stmt.lineno - 1 < len(source_lines)
        else "<unknown>"
    )
    return (stmt.lineno, snippet)


def _walk_outer_block(
    body: Iterable[ast.stmt],
    source_lines: list[str],
    in_type_checking: bool,
) -> Iterator[tuple[int, str]]:
    """Walk a non-function block (module or class body).

    Recurses through control flow into any nested ``def``/``class``,
    preserving the ``in_type_checking`` flag and honoring nested
    ``if TYPE_CHECKING:`` so that imports in a class body wrapped in
    ``if`` / ``try`` / ``with`` / ``for`` / ``while`` / ``match`` /
    ``except*`` are still seen by the linter.
    """
    for stmt in body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _find_violations_in_function(
                stmt, source_lines, in_type_checking
            )
            continue
        if isinstance(stmt, ast.ClassDef):
            yield from _walk_outer_block(stmt.body, source_lines, in_type_checking)
            continue
        if isinstance(stmt, ast.If) and _is_type_checking_test(stmt.test):
            yield from _walk_outer_block(stmt.body, source_lines, in_type_checking=True)
            yield from _walk_outer_block(stmt.orelse, source_lines, in_type_checking)
            continue
        for sub_body in _sub_bodies(stmt):
            yield from _walk_outer_block(sub_body, source_lines, in_type_checking)


def _walk_stmt(
    stmt: ast.stmt,
    source_lines: list[str],
    in_type_checking: bool,
) -> Iterator[tuple[int, str]]:
    """Yield violations for a single statement inside a function body."""
    if isinstance(stmt, ast.If) and _is_type_checking_test(stmt.test):
        yield from _walk_block(stmt.body, source_lines, in_type_checking=True)
        yield from _walk_block(stmt.orelse, source_lines, in_type_checking)
        return
    if isinstance(stmt, ast.Import | ast.ImportFrom):
        violation = _check_import(stmt, source_lines, in_type_checking)
        if violation is not None:
            yield violation
        return
    if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
        yield from _find_violations_in_function(stmt, source_lines, in_type_checking)
        return
    if isinstance(stmt, ast.ClassDef):
        # Class body inside a function executes at function-call time, so
        # its imports are functionally lazy and must be annotated. Walk
        # via _walk_block so Import statements are checked rather than
        # silently skipped as eager top-level imports would be.
        yield from _walk_block(stmt.body, source_lines, in_type_checking)
        return
    sub = list(_sub_bodies(stmt))
    if sub:
        for sub_body in sub:
            yield from _walk_block(sub_body, source_lines, in_type_checking)
        return
    for child in ast.iter_child_nodes(stmt):
        yield from _walk_node(child, source_lines, in_type_checking)


def _walk_block(
    body: Iterable[ast.stmt],
    source_lines: list[str],
    in_type_checking: bool,
) -> Iterator[tuple[int, str]]:
    """Yield ``(lineno, snippet)`` for every undocumented in-function import."""
    for stmt in body:
        yield from _walk_stmt(stmt, source_lines, in_type_checking)


def _walk_node(
    node: ast.AST,
    source_lines: list[str],
    in_type_checking: bool,
) -> Iterator[tuple[int, str]]:
    """Recurse into *node*, descending into nested functions and blocks."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        yield from _find_violations_in_function(node, source_lines, in_type_checking)
        return
    if isinstance(node, ast.If) and _is_type_checking_test(node.test):
        yield from _walk_block(node.body, source_lines, in_type_checking=True)
        yield from _walk_block(node.orelse, source_lines, in_type_checking)
        return
    for child in ast.iter_child_nodes(node):
        yield from _walk_node(child, source_lines, in_type_checking)


def find_violations(path: Path) -> list[tuple[int, str]]:
    """Parse *path* and return every undocumented in-function import."""
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    return list(_walk_outer_block(tree.body, source_lines, in_type_checking=False))


def lint(roots: Iterable[Path]) -> list[tuple[Path, int, str]]:
    """Lint every file under *roots* and return the flat violation list."""
    flat: list[tuple[Path, int, str]] = []
    for root in roots:
        for path in iter_python_files(root):
            for lineno, snippet in find_violations(path):
                flat.append((path, lineno, snippet))
    return flat


def main(argv: list[str]) -> int:
    """CLI entry point: print violations and exit non-zero if any are found."""
    if len(argv) < _MIN_ARGV_FOR_PATHS:
        repo_root = Path(__file__).resolve().parent.parent
        roots = [repo_root / "src" / "ccgram"]
    else:
        roots = [Path(arg).resolve() for arg in argv[1:]]
    violations = lint(roots)
    if not violations:
        print("lint-lazy: no undocumented in-function imports.")
        return 0
    for path, lineno, snippet in violations:
        print(f"{path}:{lineno}: undocumented in-function import: {snippet}")
    print(f"\nlint-lazy: {len(violations)} undocumented in-function import(s).")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
