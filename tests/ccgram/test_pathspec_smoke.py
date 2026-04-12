"""Smoke test confirming pathspec is importable and functional."""

import pathspec


def test_pathspec_glob_matches_py_files() -> None:
    spec = pathspec.PathSpec.from_lines("gitignore", ["*.py"])
    assert spec.match_file("foo.py")
    assert spec.match_file("bar.py")
    assert not spec.match_file("foo.txt")
    assert not spec.match_file("README.md")


def test_pathspec_glob_recursive() -> None:
    spec = pathspec.PathSpec.from_lines("gitignore", ["**/*.log"])
    assert spec.match_file("logs/app.log")
    assert spec.match_file("deep/nested/error.log")
    assert not spec.match_file("app.py")
