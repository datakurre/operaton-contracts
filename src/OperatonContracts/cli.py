"""``operaton-contracts`` command: templates and the bundled agent skill.

Exit status: 0 on success, 1 when checks or validation fail (or the skill
cannot be installed), 2 for usage and configuration errors.

``generate``, ``check``, and ``validate`` work on element templates;
``install-skill`` copies the bundled agent skill into ``.agents/skills/``.

Configured in the robot package's ``pyproject.toml``::

    [tool.operaton-contracts]
    specs = "OperatonTasks:TEMPLATES"                # co-located with task contracts
    # Or use "OperatonTemplates:TEMPLATES" for a separate build-time module.
    icon = "logo.svg"                               # optional; a spec's icon wins
    schema-url = "https://…?job=release"            # optional, pinned default
    reserved-topics = ["legacy.topic"]              # optional
"""

from __future__ import annotations

import argparse
import importlib
import sys
import tomllib
from collections.abc import Sequence
from types import ModuleType
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from OperatonContracts.checks import check_package
from OperatonContracts.skills import CLAUDE_SKILLS_DIR
from OperatonContracts.skills import SKILLS_DIR
from OperatonContracts.skills import SkillError
from OperatonContracts.skills import install_skill
from OperatonContracts.skills import link_skill
from OperatonContracts.templates import DEFAULT_SCHEMA_URL
from OperatonContracts.templates import TEMPLATE_DIR
from OperatonContracts.templates import TaskTemplate
from OperatonContracts.templates import TemplateError
from OperatonContracts.templates import drift
from OperatonContracts.templates import render_all
from OperatonContracts.templates import validate
from OperatonContracts.templates import write_templates

CONFIG_TABLE = "operaton-contracts"


class ConfigError(ValueError):
    """The ``[tool.operaton-contracts]`` configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    root: Path
    specs: tuple[TaskTemplate, ...]
    icon_svg: bytes
    schema_url: str
    reserved_topics: tuple[str, ...]
    icons: dict[str, bytes] = field(default_factory=dict)

    @property
    def template_dir(self) -> Path:
        return self.root / TEMPLATE_DIR


def _import_specs(root: Path, module_name: str) -> ModuleType:
    """Import ``module_name`` from ``root``, ignoring a copy cached elsewhere."""
    cached = sys.modules.get(module_name)
    cached_file = getattr(cached, "__file__", None)
    if cached is not None and (
        cached_file is None or not Path(cached_file).resolve().is_relative_to(root)
    ):
        del sys.modules[module_name]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        raise ConfigError(
            f"Cannot import the specs module {module_name!r} from {root}: {error}"
        ) from error


def _read_icon(root: Path, icon: object, label: str) -> bytes:
    """Read an icon file that must lie inside the project ``root``."""
    path = (root / icon).resolve() if isinstance(icon, str) else None
    if path is None or not path.is_relative_to(root) or not path.is_file():
        raise ConfigError(f"{label} {icon!r} is not a file in {root}")
    return path.read_bytes()


def load_config(root: Path) -> Config:
    """Load the configuration and import the specs relative to ``root``."""
    root = root.resolve()
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        raise ConfigError(f"{pyproject} not found")
    with pyproject.open("rb") as stream:
        table = tomllib.load(stream).get("tool", {}).get(CONFIG_TABLE)
    if not isinstance(table, dict) or not isinstance(table.get("specs"), str):
        raise ConfigError(
            f'Set [tool.{CONFIG_TABLE}] specs = "module:ATTRIBUTE" in {pyproject}'
        )
    module_name, _, attribute = table["specs"].partition(":")
    module = _import_specs(root, module_name)
    specs = getattr(module, attribute or "TEMPLATES", None)
    if (
        not isinstance(specs, (list, tuple))
        or not specs
        or not all(isinstance(spec, TaskTemplate) for spec in specs)
    ):
        raise ConfigError(
            f"{table['specs']} must be a non-empty sequence of TaskTemplate"
        )
    reserved = table.get("reserved-topics", [])
    if not isinstance(reserved, list) or not all(
        isinstance(topic, str) for topic in reserved
    ):
        raise ConfigError("reserved-topics must be a list of topic names")
    schema_url = table.get("schema-url", DEFAULT_SCHEMA_URL)
    if not isinstance(schema_url, str):
        raise ConfigError("schema-url must be a string")
    icon = table.get("icon")
    if icon is not None:
        icon_svg = _read_icon(root, icon, "icon")
    icons: dict[str, bytes] = {}
    for spec in specs:
        if spec.icon is not None and spec.icon not in icons:
            icons[spec.icon] = _read_icon(root, spec.icon, f"{spec.topic}: icon")
    return Config(
        root=root,
        specs=tuple(specs),
        icon_svg=icon_svg if icon is not None else b"",
        schema_url=schema_url,
        reserved_topics=tuple(reserved),
        icons=icons,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="operaton-contracts",
        description="Generate, check, and validate Operaton element templates, "
        "or install the bundled agent skill.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="check",
        choices=("generate", "check", "validate", "install-skill"),
        help="generate templates, check them offline (default), validate "
        "them against the pinned upstream schema, or install the agent skill",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="robot package directory (default: current directory)",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=SKILLS_DIR,
        help="install-skill: skills directory, relative to --root "
        f"(default: {SKILLS_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="install-skill: replace an installed copy that has local changes, "
        "or an existing .claude/skills entry",
    )
    parser.add_argument(
        "--claude",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="install-skill: link the skill into .claude/skills/ for Claude "
        "Code (default: only when the project has a .claude/ directory)",
    )
    arguments = parser.parse_args(argv)
    if arguments.command == "install-skill":
        skills_dir = arguments.root / arguments.skills_dir
        claude = arguments.claude
        if claude is None:
            claude = (arguments.root / ".claude").is_dir()
        try:
            print(install_skill(skills_dir, force=arguments.force))
            if claude:
                print(
                    link_skill(
                        arguments.root / CLAUDE_SKILLS_DIR,
                        skills_dir,
                        force=arguments.force,
                    )
                )
        except SkillError as error:
            print(error, file=sys.stderr)
            return 1
        return 0
    try:
        config = load_config(arguments.root)
        rendered = render_all(
            config.specs,
            icon_svg=config.icon_svg,
            schema_url=config.schema_url,
            icons=config.icons,
            template_dir=config.template_dir,
        )
    except (ConfigError, TemplateError) as error:
        print(error, file=sys.stderr)
        return 2

    if arguments.command == "validate":
        try:
            validate(sorted(config.template_dir.glob("*.json")), config.schema_url)
        except TemplateError as error:
            print(error, file=sys.stderr)
            return 1
        return 0
    if arguments.command == "generate":
        for message in write_templates(config.template_dir, rendered):
            print(message)
        return 0

    errors = check_package(
        config.root, config.specs, reserved_topics=config.reserved_topics
    )
    errors.extend(drift(config.template_dir, rendered))
    for message in errors:
        print(message, file=sys.stderr)
    if errors:
        return 1
    print("Element templates are up to date and the package is consistent")
    return 0
