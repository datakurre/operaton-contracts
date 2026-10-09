"""``operaton-contracts`` command: generate, check, and validate templates.

Configured in the robot package's ``pyproject.toml``::

    [tool.operaton-contracts]
    specs = "scripts.element_templates:TEMPLATES"   # module:attribute
    icon = "scripts/logo.svg"                       # optional
    schema-url = "https://…?job=release"            # optional, pinned default
    reserved-topics = ["legacy.topic"]              # optional
"""

from __future__ import annotations

import argparse
import importlib
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from OperatonContracts.templates import DEFAULT_SCHEMA_URL
from OperatonContracts.templates import TEMPLATE_DIR
from OperatonContracts.templates import TaskTemplate
from OperatonContracts.checks import check_package
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

    @property
    def template_dir(self) -> Path:
        return self.root / TEMPLATE_DIR


def load_config(root: Path) -> Config:
    """Load the configuration and import the specs relative to ``root``."""
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
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    specs = getattr(importlib.import_module(module_name), attribute or "TEMPLATES")
    if not all(isinstance(spec, TaskTemplate) for spec in specs):
        raise ConfigError(f"{table['specs']} must be a sequence of TaskTemplate")
    icon = table.get("icon")
    return Config(
        root=root,
        specs=tuple(specs),
        icon_svg=(root / icon).read_bytes() if icon else b"",
        schema_url=str(table.get("schema-url", DEFAULT_SCHEMA_URL)),
        reserved_topics=tuple(table.get("reserved-topics", ())),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="operaton-contracts",
        description="Generate, check, and validate Operaton element templates.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="check",
        choices=("generate", "check", "validate"),
        help="generate templates, check them offline (default), or validate "
        "them against the pinned upstream schema",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="robot package directory (default: current directory)",
    )
    arguments = parser.parse_args(argv)
    try:
        config = load_config(arguments.root.resolve())
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 2

    if arguments.command == "validate":
        validate(sorted(config.template_dir.glob("*.json")), config.schema_url)
        return 0
    rendered = render_all(
        config.specs, icon_svg=config.icon_svg, schema_url=config.schema_url
    )
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
    print("Element templates are up to date")
    return 0
