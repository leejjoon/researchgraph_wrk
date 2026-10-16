"""Git interaction helpers for researchgraph."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from researchgraph.model import Actor


def run_git(args: Sequence[str], cwd: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def try_git(args: Sequence[str], cwd: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def get_git_actor(cwd: Path | str) -> Actor:
    """Derive default human actor from git configuration."""
    name_proc = try_git(["config", "user.name"], cwd=cwd)
    name = name_proc.stdout.strip() if name_proc.returncode == 0 and name_proc.stdout.strip() else "User"

    email_proc = try_git(["config", "user.email"], cwd=cwd)
    email = email_proc.stdout.strip() if email_proc.returncode == 0 and email_proc.stdout.strip() else ""

    return Actor(kind="human", name=name)


def format_git_author(actor: Actor, cwd: Path | str | None = None) -> str:
    """Format an Actor for git --author flag."""
    email = f"{actor.name.lower().replace(' ', '.')}@local"
    if cwd is not None:
        email_proc = try_git(["config", "user.email"], cwd=cwd)
        if email_proc.returncode == 0 and email_proc.stdout.strip():
            email = email_proc.stdout.strip()
    return f"{actor.name} <{email}>"


def git_commit_files(
    paths: Sequence[Path | str],
    message: str,
    actor: Actor,
    cwd: Path | str,
) -> None:
    """Stage specified paths and commit with message and author."""
    for p in paths:
        rel_path = Path(p).relative_to(cwd) if Path(p).is_absolute() else p
        run_git(["add", str(rel_path)], cwd=cwd)

    author_flag = f"--author={format_git_author(actor, cwd=cwd)}"
    run_git(["commit", "-m", message, author_flag], cwd=cwd)
