"""Pi command discovery for Telegram-exposed slash commands.

Discovers Telegram-suitable Pi commands from the built-in command set plus
on-disk skills, prompt templates, and extension commands.
"""

from __future__ import annotations

import re
from pathlib import Path

from ccgram.command_catalog import parse_frontmatter
from ccgram.providers.base import DiscoveredCommand


def _pi_home() -> Path:
    return Path.home() / ".pi" / "agent"


def _agents_home() -> Path:
    return Path.home() / ".agents"

_PI_EXTENSION_COMMAND_RE = re.compile(
    r"pi\.registerCommand\(\s*[\"'](?P<name>[^\"']+)[\"']",
)

# Telegram-friendly Pi built-ins. Interactive TUI flows stay out.
_PI_TELEGRAM_BUILTINS: dict[str, str] = {
    "/clear": "Clear conversation history",
    "/changelog": "Show version history",
    "/compact": "Compact conversation context",
    "/export": "Export session to HTML",
    "/name": "Set session display name",
    "/reload": "Reload extensions, skills, prompts, and themes",
    "/session": "Show session info",
    "/share": "Upload as private GitHub gist",
}


def telegram_builtins() -> list[DiscoveredCommand]:
    """Return the Telegram-safe Pi built-in commands."""
    return [
        DiscoveredCommand(name=name, description=desc, source="builtin")
        for name, desc in _PI_TELEGRAM_BUILTINS.items()
    ]


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _command_description(path: Path, *, fallback: str) -> str:
    frontmatter = parse_frontmatter(path)
    description = frontmatter.get("description", "")
    if description:
        hint = frontmatter.get("argument-hint", "")
        return f"{hint} — {description}" if hint else description
    if frontmatter:
        return fallback
    body = _first_nonempty_line(_safe_read_text(path))
    return body or fallback


def _skill_command(path: Path) -> DiscoveredCommand | None:
    if path.name == "SKILL.md":
        skill_dir = path.parent
        name = parse_frontmatter(path).get("name", skill_dir.name)
        description = _command_description(path, fallback=f"/{name}")
        return DiscoveredCommand(name=name, description=description, source="skill")

    if path.suffix.lower() != ".md" or path.name.startswith("."):
        return None

    name = parse_frontmatter(path).get("name", path.stem)
    description = _command_description(path, fallback=f"/{name}")
    return DiscoveredCommand(name=name, description=description, source="skill")


def _discover_skill_roots(base_dir: Path) -> list[Path]:
    roots = [_pi_home() / "skills", _agents_home() / "skills"]
    current = base_dir.resolve()
    for parent in (current, *current.parents):
        roots.extend([parent / ".pi" / "skills", parent / ".agents" / "skills"])
        if (parent / ".git").is_dir():
            break
    seen: set[Path] = set()
    ordered: list[Path] = []
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        ordered.append(root)
    return ordered


def _discover_skills(base_dir: str) -> list[DiscoveredCommand]:
    discovered: list[DiscoveredCommand] = []
    for root in _discover_skill_roots(Path(base_dir)):
        if not root.is_dir():
            continue
        allow_root_markdown = root.name == "skills" and root.parent.name in {
            ".pi",
            "agent",
        }
        try:
            entries = sorted(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_file() and allow_root_markdown and entry.suffix.lower() == ".md":
                cmd = _skill_command(entry)
                if cmd:
                    discovered.append(cmd)
                continue
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if skill_md.is_file():
                cmd = _skill_command(skill_md)
                if cmd:
                    discovered.append(cmd)
    return discovered


def _discover_prompt_templates(base_dir: str) -> list[DiscoveredCommand]:
    discovered: list[DiscoveredCommand] = []
    roots = [_pi_home() / "prompts"]
    current = Path(base_dir).resolve()
    for parent in (current, *current.parents):
        roots.append(parent / ".pi" / "prompts")
        if (parent / ".git").is_dir():
            break

    seen: set[Path] = set()
    for root in roots:
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        try:
            files = sorted(root.glob("*.md"))
        except OSError:
            continue
        for path in files:
            if path.name.startswith("."):
                continue
            name = path.stem
            description = _command_description(path, fallback=f"/{name}")
            discovered.append(
                DiscoveredCommand(name=name, description=description, source="command")
            )
    return discovered

_EXTENSION_SKIP_DIRS = frozenset({"node_modules", "dist", "build", ".git"})


def _discover_extension_commands(base_dir: str) -> list[DiscoveredCommand]:
    discovered: list[DiscoveredCommand] = []
    roots = [_pi_home() / "extensions"]
    current = Path(base_dir).resolve()
    for parent in (current, *current.parents):
        roots.append(parent / ".pi" / "extensions")
        if (parent / ".git").is_dir():
            break

    seen_roots: set[Path] = set()
    for root in roots:
        if root in seen_roots or not root.is_dir():
            continue
        seen_roots.add(root)
        try:
            entries = sorted(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            candidates: list[Path]
            if entry.is_file() and entry.suffix.lower() in {".ts", ".js", ".mjs", ".cjs"}:
                candidates = [entry]
            elif entry.is_dir():
                try:
                    candidates = [
                        path
                        for path in entry.rglob("*")
                        if path.is_file()
                        and path.suffix.lower() in {".ts", ".js", ".mjs", ".cjs"}
                        and not path.name.startswith(".")
                        and not (_EXTENSION_SKIP_DIRS & {p.name for p in path.relative_to(entry).parents})
                    ]
                except OSError:
                    continue
            else:
                continue

            for path in candidates:
                text = _safe_read_text(path)
                if not text:
                    continue
                matches = list(_PI_EXTENSION_COMMAND_RE.finditer(text))
                for match in matches:
                    name = match.group("name").strip()
                    if not name:
                        continue
                    discovered.append(
                        DiscoveredCommand(
                            name=name,
                            description=f"/{name}",
                            source="command",
                        )
                    )
    return discovered


def discover_pi_commands(base_dir: str) -> list[DiscoveredCommand]:
    """Discover Telegram-suitable Pi commands from filesystem sources."""
    commands = []
    commands.extend(telegram_builtins())
    commands.extend(_discover_skills(base_dir))
    commands.extend(_discover_prompt_templates(base_dir))
    commands.extend(_discover_extension_commands(base_dir))

    deduped: list[DiscoveredCommand] = []
    seen: set[str] = set()
    for cmd in commands:
        if not cmd.name or cmd.name in seen:
            continue
        deduped.append(cmd)
        seen.add(cmd.name)
    return deduped
