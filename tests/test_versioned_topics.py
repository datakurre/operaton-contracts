"""Topics that only kept template versions use: served and checked."""

from __future__ import annotations

import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from pydantic import Field

from OperatonContracts import TaskContract
from OperatonContracts.checks import MISSING_ROBOT
from OperatonContracts.checks import check_package
from OperatonContracts.templates import TEMPLATE_DIR
from OperatonContracts.templates import TaskTemplate
from OperatonContracts.templates import _template_topic
from OperatonContracts.templates import dumps
from OperatonContracts.templates import kept_topics
from OperatonContracts.templates import render

SCHEMA_URL = "https://example.invalid/schema.json"


class GreetInputV1(TaskContract):
    name: str = Field(alias="name", title="Name")


class GreetInput(TaskContract):
    name: str = Field(alias="name", title="Name")
    language: str = Field(alias="language", title="Language")


class GreetOutput(TaskContract):
    greeting: str = Field(alias="greeting", title="Greeting")


V1 = TaskTemplate(
    topic="example.greet",
    template_id="org.example.greet",
    name="Greet",
    description="Greets.",
    filename="greet.json",
    inputs=GreetInputV1,
    outputs=GreetOutput,
)
V2 = TaskTemplate(
    **{
        **V1.__dict__,
        "topic": "example.greet.v2",
        "inputs": GreetInput,
        "version": 2,
        "keep_versions": (1,),
    }
)
PYPROJECT = """
[tool.purjo.topics."example.greet"]
name = "Greet V1"
process-variables = false

[tool.purjo.topics."example.greet.v2"]
name = "Greet"
process-variables = false
"""
SUITE = """*** Settings ***
Library     OperatonContracts    OperatonTasks

*** Variables ***
${BPMN:TASK}    local
${name}         ${EMPTY}
${language}     ${EMPTY}

*** Tasks ***
Greet V1
    ${input}=    Validate Task Input    GreetInputV1
    VAR    ${greeting}=    Hello ${input}[name]    scope=${BPMN:TASK}

Greet
    ${input}=    Validate Task Input    GreetInput
    VAR    ${greeting}=    Hello ${input}[name]    scope=${BPMN:TASK}
"""


def template(spec: TaskTemplate) -> dict[str, object]:
    return render(spec, icon_svg=b"<svg/>", schema_url=SCHEMA_URL)


@contextmanager
def package(pyproject: str = PYPROJECT, suite: str = SUITE) -> Iterator[Path]:
    """A robot package whose template file keeps version 1 on its old topic."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "pyproject.toml").write_text(pyproject)
        (root / "greet.robot").write_text(suite)
        (root / TEMPLATE_DIR).mkdir(parents=True)
        (root / TEMPLATE_DIR / "greet.json").write_text(
            dumps([template(V2), template(V1)])
        )
        yield root


@contextmanager
def without_robot() -> Iterator[None]:
    """Make Robot Framework and the integration module unimportable."""
    with patch.dict(sys.modules):
        sys.modules.pop("OperatonContracts.robotframework", None)
        for name in [name for name in sys.modules if name.split(".")[0] == "robot"]:
            sys.modules[name] = None  # type: ignore[assignment]
        sys.modules["robot"] = None  # type: ignore[assignment]
        yield


class KeptTopicTests(unittest.TestCase):
    def check(self, root: Path) -> list[str]:
        return check_package(root, [V2], template_dir=root / TEMPLATE_DIR)

    def test_kept_versions_name_the_topics_only_they_use(self) -> None:
        with package() as root:
            directory = root / TEMPLATE_DIR
            self.assertEqual(
                kept_topics([V2], directory),
                {"example.greet": "version 1 of org.example.greet"},
            )
            # A kept version on the current topic adds nothing, nor do specs
            # without kept versions or topics another spec serves now.
            same = TaskTemplate(**{**V2.__dict__, "topic": "example.greet"})
            self.assertEqual(kept_topics([same], directory), {})
            self.assertEqual(kept_topics([V1], directory), {})
            other = TaskTemplate(
                **{**V1.__dict__, "template_id": "org.example.other", "filename": "o"}
            )
            self.assertEqual(kept_topics([V2, other], directory), {})

    def test_template_topics_are_read_defensively(self) -> None:
        self.assertEqual(_template_topic(template(V1)), "example.greet")
        topic = {"binding": {"name": "camunda:topic"}}
        for broken in (
            {},
            {"properties": "x"},
            {"properties": ["x", {"binding": "x"}, {"binding": {"name": "other"}}]},
            {"properties": [{**topic, "value": 1}]},
            {"properties": [{**topic, "value": ""}]},
        ):
            with self.subTest(template=broken):
                self.assertIsNone(_template_topic(broken))

    def test_check_accepts_a_served_topic_of_a_kept_version(self) -> None:
        with package() as root:
            self.assertEqual(self.check(root), [])
            # Without the template directory the old topic is unknown.
            self.assertEqual(
                check_package(root, [V2]),
                [
                    "Topic has no template spec: example.greet (add a "
                    "TaskTemplate for it, or serve it from another package)"
                ],
            )

    def test_check_requires_the_kept_topic_to_be_served(self) -> None:
        current = PYPROJECT.split("\n\n")[1]
        with package(pyproject="\n" + current) as root:
            self.assertEqual(
                self.check(root),
                [
                    "Topic of kept version 1 of org.example.greet missing from "
                    "[tool.purjo.topics]: example.greet (diagrams modeled with "
                    "that version still use it; keep serving it, or drop the "
                    "version from keep_versions)"
                ],
            )

    def test_check_requires_the_kept_topic_task_and_task_scope(self) -> None:
        with package(
            pyproject=PYPROJECT.replace("process-variables = false", "", 1),
            suite=SUITE.replace("Greet V1", "Greet Old"),
        ) as root:
            self.assertEqual(
                self.check(root),
                [
                    "example.greet: set process-variables = false",
                    "example.greet: no Robot suite defines task 'Greet V1'",
                ],
            )

    def test_check_reports_a_missing_template_file(self) -> None:
        with package() as root:
            (root / TEMPLATE_DIR / "greet.json").unlink()
            errors = self.check(root)
        self.assertEqual(len(errors), 2)
        self.assertIn("kept versions of org.example.greet need the", errors[0])
        self.assertIn("Topic has no template spec: example.greet", errors[1])

    def test_kept_topics_are_unchecked_without_robot(self) -> None:
        with package() as root, without_robot():
            self.assertEqual(self.check(root), [MISSING_ROBOT])
