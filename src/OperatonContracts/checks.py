"""Consistency checks between template specs, purjo topics, and task suites."""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from typing import Protocol

from OperatonContracts.templates import TaskTemplate
from OperatonContracts.templates import TemplateError
from OperatonContracts.templates import kept_topics

MISSING_ROBOT = (
    "Robot suite checks need Robot Framework: install operaton-contracts[robot]"
)


class _TaskSuites(Protocol):
    def check(self, spec: TaskTemplate, task: str) -> list[str]: ...

    def check_task(self, topic: str, task: str) -> list[str]: ...


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
    template_dir: Path | None = None,
) -> list[str]:
    """Return mismatches between specs, external task topics, and task suites.

    The suite checks need Robot Framework; without it, configured topics are
    reported as unchecked instead of silently passing. With ``template_dir``,
    topics that only kept template versions use are accepted, and must still
    be served by a Robot task, because diagrams modeled with those versions
    keep using them.
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
    kept: dict[str, str] = {}
    if template_dir is not None:
        try:
            kept = kept_topics(specs, template_dir)
        except TemplateError as error:
            errors.append(str(error))
    errors.extend(
        f"Topic has no template spec: {topic} (add a TaskTemplate for it, "
        "or serve it from another package)"
        for topic in sorted(set(topics) - spec_topics - set(kept))
    )

    suites = _robot_suites(root)
    unchecked = False
    for topic, version in kept.items():
        config = topics.get(topic)
        if config is None:
            errors.append(
                f"Topic of kept {version} missing from [tool.purjo.topics]: "
                f"{topic} (diagrams modeled with that version still use it; "
                "keep serving it, or drop the version from keep_versions)"
            )
            continue
        if config.get("process-variables") is not False:
            errors.append(f"{topic}: set process-variables = false")
        if suites is None:
            unchecked = True
            continue
        errors.extend(suites.check_task(topic, config.get("name", "")))
    for spec in specs:
        config = topics.get(spec.topic)
        if config is None:
            errors.append(
                f"Topic missing from [tool.purjo.topics]: {spec.topic} "
                f'(add [tool.purjo.topics."{spec.topic}"] with the Robot task name)'
            )
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
