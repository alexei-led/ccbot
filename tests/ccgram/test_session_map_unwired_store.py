"""Regression test: parse_session_map() must work without SessionManager wiring.

The fix here pins the contract that ``parse_session_map`` is a pure free
function. It used to crash with ``RuntimeError("WindowStateStore not yet
wired")`` whenever the caller imported it without first instantiating
``SessionManager`` — pytest's conftest masked the regression because it
imports SessionManager at collection time.

Runs the assertion in a fresh interpreter so conftest cannot wire the
proxy first.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path


def test_parse_session_map_works_without_session_manager(tmp_path: Path) -> None:
    transcript = tmp_path / "x.jsonl"
    transcript.write_text('{"type":"assistant"}\n')
    payload = {
        "ccgram:@7": {
            "session_id": "x",
            "cwd": "/repo",
            "window_name": "repo",
            "transcript_path": str(transcript),
            "provider_name": "claude",
        }
    }
    script = textwrap.dedent(
        f"""
        import json
        import sys
        from ccgram.session_map import parse_session_map
        # Prove SessionManager has not been imported in this interpreter.
        assert "ccgram.session" not in sys.modules, sorted(sys.modules)
        result = parse_session_map({payload!r}, "ccgram:")
        print(json.dumps(result))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    parsed = json.loads(last_line)
    assert parsed["@7"]["session_id"] == "x"
