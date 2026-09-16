import os
import re
from pathlib import Path

import typer

from softmax.agent import detect_coding_agent

BEGIN = "<!-- BEGIN:coworld-agent-rules -->"
END = "<!-- END:coworld-agent-rules -->"
SOFTMAX_SITE_ORIGIN = "https://softmax.com"
GUIDANCE_BLOCK = (
    f"{BEGIN}\n"
    f"Before working in this Coworld project, read {SOFTMAX_SITE_ORIGIN}/agents.md "
    "(the Softmax agent guide; it is generated and kept current).\n"
    "Run `coworld docs` for the documentation index and `coworld docs --local` "
    "for the references installed with the CLI.\n"
    "Disable these automatic updates with COWORLD_AGENT_GUIDANCE=0 or a .coworld-no-agent-guidance file.\n"
    f"{END}"
)
IMPORT_BLOCK = f"{BEGIN}\n@AGENTS.md\n{END}"
REPAIR = "Repair the guidance file or set COWORLD_AGENT_GUIDANCE=0 to opt out."


def find_project_root(cwd: Path) -> Path | None:
    cwd = cwd.resolve()
    ancestors = (cwd, *cwd.parents)
    stops = {Path.home().resolve(), Path(cwd.anchor)}
    # Both checkout directories and worktree .git files establish the boundary.
    boundary = next(path for path in ancestors if path in stops or (path / ".git").exists())
    ancestors = ancestors[: ancestors.index(boundary) + 1]
    root = None
    for path in ancestors:
        if path in stops:
            break
        marker = path / ".coworld-project"
        if marker.is_file() and marker.read_text().strip() in {"player", "coworld"}:
            root = path
            break
    if root is None:
        return None
    if any((path / ".coworld-no-agent-guidance").is_file() for path in ancestors[ancestors.index(root) :]):
        return None
    return root


def upsert_guidance(original: bytes, block: str = GUIDANCE_BLOCK) -> bytes:
    begin, end = BEGIN.encode(), END.encode()
    lines = original.splitlines(keepends=True)
    markers = [(i, line.rstrip(b"\r\n")) for i, line in enumerate(lines) if line.rstrip(b"\r\n") in (begin, end)]
    if [marker for _, marker in markers] not in ([], [begin, end]):
        typer.echo(f"Malformed or duplicate Coworld guidance markers. {REPAIR}", err=True)
        raise typer.Exit(1)
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    replacement = block.encode().replace(b"\n", newline)
    if markers:
        start_line, end_line = markers[0][0], markers[1][0]
        return (
            b"".join(lines[:start_line])
            + replacement
            + lines[end_line].removeprefix(end)
            + b"".join(lines[end_line + 1 :])
        )
    separator = (newline if original.endswith(b"\n") else newline * 2) if original else b""
    return original + separator + replacement + newline


def update_agent_guidance(start: Path) -> None:
    if os.environ.get("COWORLD_AGENT_GUIDANCE") == "0":
        return
    agent = detect_coding_agent()
    if agent is None:
        return
    root = find_project_root(start)
    if root is None:
        return
    paths = [root / "AGENTS.md"]
    if agent == "claude-code":
        paths.append(root / "CLAUDE.md")
    updates: list[tuple[Path, bytes]] = []
    seen: set[Path] = set()
    for path in paths:
        target = path.resolve()
        if not target.is_relative_to(root):
            typer.echo(f"{path} points outside the project. {REPAIR}", err=True)
            raise typer.Exit(1)
        if target in seen:
            continue
        seen.add(target)
        original = target.read_bytes() if target.exists() else b""
        block = GUIDANCE_BLOCK if path.name == "AGENTS.md" else IMPORT_BLOCK
        if (
            path.name == "CLAUDE.md"
            and BEGIN.encode() not in original.splitlines()
            and END.encode() not in original.splitlines()
            and re.search(rb"(?m)^@(?:\./)?AGENTS\.md\r?$", original)
        ):
            continue
        updated = upsert_guidance(original, block)
        if updated != original:
            updates.append((target, updated))
    for path, content in updates:
        path.write_bytes(content)
        typer.echo(f"Updated Coworld guidance: {path}", err=True)
