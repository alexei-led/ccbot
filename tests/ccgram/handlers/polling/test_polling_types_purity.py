"""Purity invariants for ``ccgram.handlers.polling.polling_types``.

Round 4 introduced the F4 pure-decision-kernel pattern; Round 5 made the
purity invariant provable at the import level. ``polling_types`` is the
contract that ``window_tick.decide`` depends on. If importing
``polling_types`` ever pulls in ``polling_state`` (or anything heavier), the
F4 promise — "the pure kernel can be loaded without instantiating the
stateful singletons" — breaks. These two tests catch the regression
before runtime.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

POLLING_TYPES_PATH = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "ccgram"
    / "handlers"
    / "polling"
    / "polling_types.py"
)


def test_polling_types_does_not_load_polling_state() -> None:
    """Subprocess load-time check: importing polling_types must NOT execute polling_state.

    A clean interpreter is required because the pytest process has likely
    already loaded polling_state (via fixtures or other tests). Running
    ``python -c "import …"`` in a subprocess is the only way to observe the
    cold-import behaviour the F4 invariant is actually about.
    """
    code = (
        "import sys; "
        "import ccgram.handlers.polling.polling_types; "
        "assert 'ccgram.handlers.polling.polling_state' not in sys.modules, "
        "'polling_types must NOT pull in polling_state at import time'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"polling_types load-time purity broken:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


def test_polling_types_imports_are_restricted() -> None:
    """AST check: polling_types may only import stdlib + ccgram.providers.base.

    Anything else is a regression — the pure-types module gets to depend on
    the providers contract (for ``StatusUpdate``) and on stdlib only. In
    particular, anything under ``ccgram.handlers.*`` or ``telegram*`` (other
    than TYPE_CHECKING-guarded forward references) is forbidden.
    """
    source = POLLING_TYPES_PATH.read_text()
    tree = ast.parse(source)

    # Walk only top-level statements; TYPE_CHECKING-guarded imports live
    # inside an ``if TYPE_CHECKING:`` block which we do not descend into.
    runtime_imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            runtime_imports.append(node.module)
        elif isinstance(node, ast.Import):
            runtime_imports.extend(alias.name for alias in node.names)

    # ``ast.ImportFrom`` strips leading dots, so a relative import
    # ``from ...providers.base import StatusUpdate`` shows up as
    # ``module="providers.base"``. We allow both the absolute and bare-relative
    # forms.
    allowed = (
        "__future__",
        "collections",
        "collections.abc",
        "dataclasses",
        "typing",
        "ccgram.providers.base",
        "providers.base",
    )
    forbidden = [mod for mod in runtime_imports if mod not in allowed]
    assert not forbidden, (
        f"polling_types must only import stdlib + ccgram.providers.base; "
        f"forbidden top-level imports: {forbidden}"
    )
