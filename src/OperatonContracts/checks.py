"""Consistency checks between template specs, purjo topics, and task suites."""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from typing import Protocol

from OperatonContracts.templates import TaskTemplate

MISSING_ROBOT = (
    "Robot suite checks need Robot Framework: install operaton-contracts[robot]"
)


class _TaskSuites(Protocol):
    def check(self, spec: TaskTemplate, task: str) -> list[str]: ...


def _robot_suites(root: Path) -> _TaskSuites | None:
    try:
        from OperatonContracts.robotframework import RobotSuites
    except ImportError:
        return None
    return RobotSuites(root)


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def check_package(
    root: Path,
    specs: Sequence[TaskTemplate],
    *,
    reserved_topics: Iterable[str] = (),
) -> list[str]:
    """Return mismatches between specs, external task topics, and task suites.

    The suite checks need Robot Framework; without it, configured topics are
    reported as unchecked instead of silently passing.
    """
    errors: list[str] = []
    with (root / "pyproject.toml").open("rb") as stream:
        tool = tomllib.load(stream).get("tool", {}).get("purjo", {})
    topics: dict[str, dict[str, Any]] = tool.get("topics", {})

    for label, values in (
        ("topic", [spec.topic for spec in specs]),
        ("template id", [spec.template_id for spec in specs]),
        ("filename", [spec.filename for spec in specs]),
    ):
        errors.extend(f"Duplicate {label}: {value}" for value in _duplicates(values))
    reserved = set(reserved_topics)
    errors.extend(
        f"Topic is reserved: {spec.topic}" for spec in specs if spec.topic in reserved
    )
    spec_topics = {spec.topic for spec in specs}
    errors.extend(
        f"Topic has no template spec: {topic}"
        for topic in sorted(set(topics) - spec_topics)
    )

    suites = _robot_suites(root)
    unchecked = False
    for spec in specs:
        config = topics.get(spec.topic)
        if config is None:
            errors.append(f"Topic missing from [tool.purjo.topics]: {spec.topic}")
            continue
        if config.get("process-variables") is not False:
            errors.append(f"{spec.topic}: set process-variables = false")
        if suites is None:
            unchecked = True
            continue
        errors.extend(suites.check(spec, config.get("name", "")))
    if unchecked:
        errors.append(MISSING_ROBOT)
    return errors
