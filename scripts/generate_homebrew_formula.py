#!/usr/bin/env python3
"""Generate a Homebrew formula for ccbot with all Python resource blocks.

Usage: python scripts/generate_homebrew_formula.py <version>

Fetches the sdist from PyPI, resolves all transitive dependencies via pip,
fetches each dependency's sdist URL + sha256 from PyPI, and prints the
complete Homebrew formula to stdout.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PYPI_JSON_URL = "https://pypi.org/pypi/{name}/{version}/json"
PYPI_PKG_URL = "https://pypi.org/pypi/{name}/json"
POLL_INTERVAL = 10
POLL_TIMEOUT = 300


def fetch_pypi_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def fetch_sdist_info(name: str, version: str | None = None) -> tuple[str, str]:
    """Fetch sdist URL and sha256 for a package from PyPI."""
    if version:
        url = PYPI_JSON_URL.format(name=name, version=version)
    else:
        url = PYPI_PKG_URL.format(name=name)

    data = fetch_pypi_json(url)
    for entry in data["urls"]:
        if entry["packagetype"] == "sdist":
            return entry["url"], entry["digests"]["sha256"]

    raise SystemExit(f"ERROR: No sdist found for {name} {version or 'latest'}")


def wait_for_pypi(version: str) -> tuple[str, str]:
    """Wait for ccbot sdist to appear on PyPI, return (url, sha256)."""
    url = PYPI_JSON_URL.format(name="ccbot", version=version)
    deadline = time.monotonic() + POLL_TIMEOUT

    while True:
        try:
            data = fetch_pypi_json(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and time.monotonic() < deadline:
                print(f"Waiting for PyPI to serve {version}...", file=sys.stderr)
                time.sleep(POLL_INTERVAL)
                continue
            raise

        for entry in data["urls"]:
            if entry["packagetype"] == "sdist":
                return entry["url"], entry["digests"]["sha256"]

        if time.monotonic() >= deadline:
            break
        print("sdist not yet available, retrying...", file=sys.stderr)
        time.sleep(POLL_INTERVAL)

    raise SystemExit(
        f"ERROR: sdist for ccbot {version} not found within {POLL_TIMEOUT}s"
    )


def _pip_cmd() -> list[str]:
    """Return the pip command prefix — prefer 'uv pip', fall back to 'python -m pip'."""
    if shutil.which("uv"):
        return ["uv", "pip"]
    return [sys.executable, "-m", "pip"]


def resolve_deps(version: str, tmpdir: Path) -> list[tuple[str, str]]:
    """Use pip to resolve all transitive deps (excluding ccbot itself)."""
    reqs_file = tmpdir / "reqs.txt"
    subprocess.check_call(
        [
            *_pip_cmd(),
            "install",
            "--dry-run",
            "--ignore-installed",
            "--report",
            str(reqs_file),
            f"ccbot=={version}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=sys.stderr,
    )

    report = json.loads(reqs_file.read_text())
    deps = []
    for item in report.get("install", []):
        meta = item["metadata"]
        name = meta["name"]
        ver = meta["version"]
        if name.lower() == "ccbot":
            continue
        deps.append((name, ver))

    return sorted(deps, key=lambda x: x[0].lower())


def generate_resource_blocks(deps: list[tuple[str, str]]) -> str:
    """Generate Homebrew resource blocks for each dependency."""
    blocks = []
    for name, version in deps:
        try:
            sdist_url, sha256 = fetch_sdist_info(name, version)
        except (SystemExit, urllib.error.HTTPError):
            print(
                f"WARNING: Could not find sdist for {name}=={version}, skipping",
                file=sys.stderr,
            )
            continue

        blocks.append(
            f'  resource "{name}" do\n'
            f'    url "{sdist_url}"\n'
            f'    sha256 "{sha256}"\n'
            f"  end"
        )

    return "\n\n".join(blocks)


def build_formula(sdist_url: str, sha256: str, resources: str) -> str:
    return f"""\
class Ccbot < Formula
  include Language::Python::Virtualenv

  desc "Control Claude Code sessions remotely via Telegram"
  homepage "https://github.com/alexei-led/ccbot"
  url "{sdist_url}"
  sha256 "{sha256}"
  license "MIT"

  depends_on "python@3.14"
  depends_on "tmux"

{resources}

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{{bin}}/ccbot --version")
  end
end
"""


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <version>", file=sys.stderr)
        raise SystemExit(1)

    version = sys.argv[1]

    print(f"Fetching sdist info for ccbot {version}...", file=sys.stderr)
    sdist_url, sha256 = wait_for_pypi(version)
    print(f"  url: {sdist_url}", file=sys.stderr)
    print(f"  sha256: {sha256}", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        print("Resolving dependencies...", file=sys.stderr)
        deps = resolve_deps(version, tmppath)
        print(f"  found {len(deps)} dependencies", file=sys.stderr)

    print("Fetching sdist info for dependencies...", file=sys.stderr)
    resources = generate_resource_blocks(deps)

    formula = build_formula(sdist_url, sha256, resources)
    print(formula)


if __name__ == "__main__":
    main()
