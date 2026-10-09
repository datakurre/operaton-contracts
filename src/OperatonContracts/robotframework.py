"""Robot Framework integration: the ``OperatonContracts`` library and suite checks.

Requires the ``robot`` extra (``robotframework``). The rest of the package
works without it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from robot.api import get_model
from robot.api.deco import keyword
from robot.api.deco import library
from robot.api.parsing import ModelVisitor
from robot.libraries.BuiltIn import BuiltIn
from robot.libraries.BuiltIn import RobotNotRunningError

from OperatonContracts.contracts import aliases
from OperatonContracts.contracts import import_contracts
from OperatonContracts.contracts import load_contract
from OperatonContracts.contracts import validate_input
from OperatonContracts.templates import TaskTemplate
from OperatonContracts.templates import contract_properties

TASK_SCOPE = "${BPMN:TASK}"
VALIDATE_KEYWORD = "Validate Task Input"
# Directories never collected as task suites (purjo collects suites
# recursively; tests and tooling are excluded from robot.zip by .wrapignore).
SKIPPED_DIRS = frozenset(
    {
        "tests",
        "lib",
        "examples",
        "node_modules",
        "__pycache__",
        "venv",
        "site-packages",
    }
)
_MISSING = object()


def _suite_directory() -> str | None:
    """Return the directory of the running suite, if Robot is running."""
    try:
        source = BuiltIn().get_variable_value("${SUITE SOURCE}")
    except RobotNotRunningError:
        return None
    if not source:
        return None
    path = Path(source)
    return str(path if path.is_dir() else path.parent)


@library(scope="GLOBAL", auto_keywords=False)
class OperatonContracts:
    """Validates Robot task variables against ``TaskContract`` models.

    Import it with the name of the module that holds the contracts:
    ``Library    OperatonContracts    OperatonTasks``. purjo and
    ``python -m robot`` run with the robot package on ``sys.path``; otherwise
    the module is imported from the running suite's directory.
    """

    def __init__(self, contracts: str = "OperatonTasks") -> None:
        directory = _suite_directory()
        self._module = import_contracts(contracts, [directory] if directory else [])

    @keyword("Validate Task Input")
    def validate_task_input(self, contract: str) -> dict[str, Any]:
        """Validate the task's input variables against ``contract``.

        Reads ``${alias}`` for every contract field, validates the values,
        and returns them normalized and JSON-compatible (dates become
        ``YYYY-MM-DD`` strings), keyed by alias. Unset variables are left out
        so contract defaults apply; suites normally declare typed defaults
        (``${False}``, ``${0}``, ``@{EMPTY}``) that match the contract's.
        """
        model = load_contract(self._module, contract)
        builtin = BuiltIn()
        variables: dict[str, Any] = {}
        for alias in aliases(model):
            value = builtin.get_variable_value(f"${{{alias}}}", _MISSING)
            if value is not _MISSING:
                variables[alias] = value
        return validate_input(model, variables)


def normalize(name: str) -> str:
    """Normalize a name the way Robot Framework matches keywords, tasks, and
    variables: ignoring case, spaces, and underscores."""
    return "".join(name.split()).replace("_", "").casefold()


def _unwrap(token: str) -> str:
    """Return ``name`` from ``${name}``, ``@{name}``, ``&{name}``, or ``name``."""
    if len(token) > 3 and token[1] == "{" and token.endswith("}"):
        return token[2:-1]
    return token


def _variable_name(token: str) -> str:
    """Return the bare name of ``${name}``, ``@{name: type}``, or ``name``."""
    return _unwrap(token).split(":", 1)[0].strip()


# Variable values that are a string or None, never e.g. a bool or a list.
_UNTYPED_VALUES = frozenset({"${EMPTY}", "${SPACE}", "${None}", "${NONE}"})


# Default sigils and the JSON Schema types whose values they produce.
_SIGIL_TYPES = {"@": "array", "&": "object"}


def _sigil(declared: str, values: tuple[str, ...]) -> str:
    """Return ``@`` or ``&`` for list or dict defaults, else an empty string."""
    if declared[0] in _SIGIL_TYPES:
        return declared[0]
    if len(values) == 1 and values[0][:2] in ("@{", "&{"):
        return values[0][0]
    return ""


def _is_typed(declared: str, values: tuple[str, ...]) -> bool:
    """Whether a suite default yields a non-string value at runtime."""
    if declared[0] in "@&" or ":" in declared[2:-1]:
        return True
    return (
        len(values) == 1
        and values[0].startswith(("${", "@{", "&{"))
        and values[0] not in _UNTYPED_VALUES
    )


@dataclass
class _Suite:
    path: Path
    # normalized name -> (declared name, values)
    variables: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)
    # normalized task name -> normalized output names / contract names
    task_outputs: dict[str, set[str]] = field(default_factory=dict)
    task_contracts: dict[str, set[str]] = field(default_factory=dict)


class _SuiteVisitor(ModelVisitor):  # type: ignore[misc]
    def __init__(self, suite: _Suite) -> None:
        self.suite = suite
        self.task: str | None = None

    def visit_Variable(self, node: Any) -> None:
        name = normalize(_variable_name(node.name))
        self.suite.variables[name] = (node.name, tuple(node.value))

    def visit_TestCase(self, node: Any) -> None:
        self.task = normalize(node.name)
        self.suite.task_outputs[self.task] = set()
        self.suite.task_contracts[self.task] = set()
        self.generic_visit(node)
        self.task = None

    def visit_Var(self, node: Any) -> None:
        scope = normalize(_unwrap(node.scope or ""))
        if self.task is not None and scope == normalize("BPMN:TASK"):
            name = normalize(_variable_name(node.name))
            self.suite.task_outputs[self.task].add(name)

    def visit_KeywordCall(self, node: Any) -> None:
        keyword_name = (node.keyword or "").rsplit(".", 1)[-1]
        if (
            self.task is not None
            and normalize(keyword_name) == normalize(VALIDATE_KEYWORD)
            and node.args
        ):
            self.suite.task_contracts[self.task].add(node.args[0])


def _suite_paths(root: Path) -> list[Path]:
    """Collect task suites, pruning hidden, tooling, and virtualenv directories."""
    paths: list[Path] = []
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if not name.startswith(".")
            and name not in SKIPPED_DIRS
            and not (Path(directory) / name / "pyvenv.cfg").exists()
        ]
        paths.extend(
            Path(directory) / name
            for name in filenames
            if name.endswith(".robot") and not name.startswith("test_")
        )
    return sorted(paths)


class RobotSuites:
    """The robot package's task suites, for checking them against contracts."""

    def __init__(self, root: Path) -> None:
        self.root = root
        # normalized task name -> every suite defining it
        self.tasks: dict[str, list[_Suite]] = {}
        for path in _suite_paths(root):
            suite = _Suite(path)
            _SuiteVisitor(suite).visit(get_model(path))
            for task in suite.task_outputs:
                self.tasks.setdefault(task, []).append(suite)

    def check(self, spec: TaskTemplate, task: str) -> list[str]:
        """Return mismatches between the suite defining ``task`` and ``spec``."""
        matches = self.tasks.get(normalize(task), [])
        if not matches:
            return [f"{spec.topic}: no Robot suite defines task {task!r}"]
        if len(matches) > 1:
            names = ", ".join(str(m.path.relative_to(self.root)) for m in matches)
            return [
                f"{spec.topic}: task {task!r} is defined in several suites "
                f"({names}); purjo would run all of them"
            ]
        suite = matches[0]
        key = normalize(task)
        errors: list[str] = []
        for alias, schema, _required in contract_properties(spec.inputs):
            declared = suite.variables.get(normalize(alias))
            if declared is None:
                errors.append(
                    f"{suite.path.name}: input {alias!r} needs a default "
                    "in *** Variables ***"
                )
            elif schema.get("type", "string") != "string" and not _is_typed(*declared):
                errors.append(
                    f"{suite.path.name}: default of {declared[0]} is a string; "
                    f"use a typed default such as ${{False}}, ${{0}}, @{{EMPTY}}, "
                    "or &{EMPTY}"
                )
            elif (sigil := _sigil(*declared)) and _SIGIL_TYPES[sigil] != schema.get(
                "type"
            ):
                errors.append(
                    f"{suite.path.name}: default of {declared[0]} is "
                    f"{'a list' if sigil == '@' else 'a dictionary'}, but input "
                    f"{alias!r} is {schema.get('type', 'not a JSON array or object')}"
                )
        for alias, _schema, _required in contract_properties(spec.outputs):
            if normalize(alias) not in suite.task_outputs[key]:
                errors.append(
                    f"{suite.path.name}: task {task!r} must set output "
                    f"{alias!r} with VAR ... scope={TASK_SCOPE}"
                )
        contract = spec.inputs.__name__
        if contract not in suite.task_contracts[key]:
            errors.append(
                f"{suite.path.name}: task {task!r} must call "
                f"{VALIDATE_KEYWORD}    {contract}"
            )
        return errors
