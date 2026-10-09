"""Install the agent skill bundled with this package.

The skill teaches coding agents how to build and maintain robot packages with
``operaton-contracts``. It is installed into the agent-neutral
``.agents/skills/`` directory of a project and can be linked into
``.claude/skills/`` for Claude Code, which reads skills only from there.
"""

from __future__ import annotations

import os
import shutil
from importlib.resources.abc import Traversable
from importlib.resources import files
from pathlib import Path

SKILL_NAME = "purjo-operaton-task-package"
SKILLS_DIR = Path(".agents") / "skills"
CLAUDE_SKILLS_DIR = Path(".claude") / "skills"


class SkillError(RuntimeError):
    """The installed skill differs from the packaged one."""


def _read(directory: Traversable, prefix: str = "") -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for entry in directory.iterdir():
        path = f"{prefix}{entry.name}"
        if entry.is_dir():
            if entry.name != "__pycache__":
                contents.update(_read(entry, f"{path}/"))
        else:
            contents[path] = entry.read_bytes()
    return contents


def packaged_skill() -> dict[str, bytes]:
    """Return the bundled skill's files keyed by relative path."""
    return _read(files("OperatonContracts") / "skills" / SKILL_NAME)


def _remove(path: Path) -> None:
    """Remove a file, a symbolic link (not its target), or a directory tree."""
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _write(destination: Path, skill: dict[str, bytes]) -> None:
    for relative, content in skill.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def install_skill(skills_dir: Path, *, force: bool = False) -> str:
    """Install or update the skill in ``skills_dir`` and describe the result.

    An existing entry that differs from the packaged skill (a modified copy, a
    file, or a symbolic link) is replaced only with ``force``, since local
    edits would be lost. A symbolic link is replaced, never followed.
    """
    destination = skills_dir / SKILL_NAME
    skill = packaged_skill()
    action = "Installed"
    try:
        if destination.is_symlink() or destination.exists():
            if (
                not destination.is_symlink()
                and destination.is_dir()
                and _read(destination) == skill
            ):
                return f"{destination} is up to date"
            if not force:
                raise SkillError(
                    f"{destination} differs from the packaged skill; "
                    "rerun with --force to replace it"
                )
            _remove(destination)
            action = "Updated"
        _write(destination, skill)
    except OSError as error:
        raise SkillError(f"Cannot install the skill into {destination}: {error}")
    return f"{action} {destination}"


def link_skill(link_dir: Path, skills_dir: Path, *, force: bool = False) -> str:
    """Expose the installed skill in ``link_dir`` and describe the result.

    Creates a relative symbolic link, so the project can move; where symbolic
    links are unavailable, copies the skill instead. An entry that already
    resolves to the installed skill (including through a linked ``link_dir``)
    is left alone; any other existing entry is replaced only with ``force``.
    """
    link = link_dir / SKILL_NAME
    installed = (skills_dir / SKILL_NAME).resolve()
    try:
        if link.exists() and link.resolve() == installed:
            return f"{link} is up to date"
        target = Path(os.path.relpath(installed, link_dir.resolve()))
        if link.is_symlink() or link.exists():
            if not force:
                raise SkillError(
                    f"{link} already exists and is not a link to {target}; "
                    "rerun with --force to replace it"
                )
            _remove(link)
        link_dir.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            _write(link, _read(installed))
            return f"Copied the skill to {link} (symbolic links are unavailable)"
    except OSError as error:
        raise SkillError(f"Cannot link the skill into {link}: {error}")
    return f"Linked {link} -> {target}"
