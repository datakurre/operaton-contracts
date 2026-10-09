"""Tests for element templates, package checks, and the Robot Framework library."""

from __future__ import annotations

import io
import json
import runpy
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from typing import Any
from typing import Literal
from unittest.mock import patch

from pydantic import Field
from pydantic import ValidationError

import OperatonContracts
from OperatonContracts import OperatonContracts as OperatonContractsLibrary
from OperatonContracts import TaskContract
from OperatonContracts import template_hints
from OperatonContracts import cli
from OperatonContracts import robotframework
from OperatonContracts.checks import check_package
from OperatonContracts import templates as operaton_templates
from OperatonContracts.templates import TaskTemplate
from OperatonContracts.templates import TemplateError
from OperatonContracts.templates import TemplateGroup
from OperatonContracts.templates import render

SCHEMA_URL = "https://example.invalid/schema.json"


class DemoInput(TaskContract):
    name: str = Field(alias="name", title="Name", description="Who to greet")
    mode: Literal["short", "long"] = Field(alias="mode", title="Mode")
    tags: list[Literal["a", "b"]] = Field(
        alias="tags", title="Tags", default_factory=list
    )
    ids: list[str] = Field(
        alias="ids",
        title="IDs",
        min_length=1,
        json_schema_extra=template_hints(value=["${id}"]),
    )
    day: date = Field(alias="day", title="Day", strict=False)
    note: str = Field(alias="note", title="Note", default="")
    count: int = Field(
        alias="count", title="Count", json_schema_extra=template_hints(type="String")
    )
    dry_run: bool = Field(alias="dryRun", title="Dry run", default=False)


class DemoOutput(TaskContract):
    greeting: str = Field(alias="greeting", title="Greeting", description="Text")
    result: dict[str, Any] = Field(alias="result", title="Result")


DEMO = TaskTemplate(
    topic="demo.greet",
    template_id="fi.example.demo-greet",
    name="Demo: Greet",
    description="Greets.",
    filename="demo-greet.json",
    inputs=DemoInput,
    outputs=DemoOutput,
)

DEMO_PYPROJECT = """
[tool.purjo.topics."demo.greet"]
name = "Greet"
process-variables = false
"""

DEMO_SUITE = """*** Variables ***
${BPMN:TASK}    local
${name}    ${EMPTY}
${mode}    short
@{tags}    @{EMPTY}
@{ids}    @{EMPTY}
${day}    ${EMPTY}
${note}    ${EMPTY}
${count: int}    0
${dry_run}    ${False}


*** Tasks ***
greet
    ${input}=    OperatonContracts.Validate Task Input    DemoInput
    VAR    ${greeting: str}=    Hello ${name}    scope=BPMN:TASK
    VAR    ${result}=    ${{{}}}    scope=${BPMN:TASK}
    VAR    ${local}=    ignored    scope=LOCAL
    Helper


*** Keywords ***
Helper
    VAR    ${elsewhere}=    ignored    scope=${BPMN:TASK}
    Validate Task Input    HelperInput
"""


def _property(template: dict[str, Any], name: str) -> dict[str, Any]:
    return next(
        prop
        for prop in template["properties"]
        if name
        in (prop["binding"].get("name"), prop["binding"].get("source"), prop["label"])
    )


class DemoPackage:
    """A temporary robot package configured for the ``operaton-contracts`` CLI."""

    count = 0

    def __init__(self, pyproject: str = DEMO_PYPROJECT, suite: str = DEMO_SUITE):
        DemoPackage.count += 1
        module = f"demo_specs_{DemoPackage.count}"
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        (self.root / "pyproject.toml").write_text(pyproject + f"""
[tool.operaton-contracts]
specs = "{module}:TEMPLATES"
icon = "icon.svg"
schema-url = "{SCHEMA_URL}"
reserved-topics = ["legacy.topic"]
""")
        (self.root / f"{module}.py").write_text(
            f"from {__name__} import DEMO\n\nTEMPLATES = (DEMO,)\n"
        )
        (self.root / "greet.robot").write_text(suite)
        (self.root / "icon.svg").write_bytes(b"<svg/>")

    def __enter__(self) -> DemoPackage:
        return self

    def __exit__(self, *_args: object) -> None:
        self._directory.cleanup()

    def main(self, *argv: str) -> int:
        return cli.main([*argv, "--root", str(self.root)])


class SchemaResponse(io.BytesIO):
    def __enter__(self) -> SchemaResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class ElementTemplateRenderTests(unittest.TestCase):
    def test_render_maps_contract_schema_to_template_properties(self) -> None:
        template = render(DEMO, icon_svg=b"<svg/>", schema_url=SCHEMA_URL)

        self.assertEqual(
            list(template),
            [
                "$schema",
                "name",
                "id",
                "description",
                "version",
                "appliesTo",
                "groups",
                "properties",
                "icon",
            ],
        )
        self.assertEqual(
            template["icon"]["contents"], "data:image/svg+xml;base64,PHN2Zy8+"
        )
        self.assertEqual(
            template["groups"],
            [
                {"id": "inputs", "label": "Inputs"},
                {"id": "outputs", "label": "Results"},
            ],
        )
        self.assertEqual(
            _property(template, "name"),
            {
                "label": "Name",
                "description": "Who to greet",
                "type": "String",
                "value": "${name}",
                "constraints": {"notEmpty": True},
                "group": "inputs",
                "binding": {"type": "camunda:inputParameter", "name": "name"},
            },
        )
        mode = _property(template, "mode")
        self.assertEqual(mode["type"], "Dropdown")
        self.assertEqual(mode["choices"][1], {"name": "long", "value": "long"})
        tags = _property(template, "tags")
        self.assertEqual((tags["type"], tags["display"]), ("List", "taglist"))
        self.assertNotIn("itemType", tags)
        self.assertEqual(tags["value"], [])
        self.assertNotIn("constraints", tags)
        ids = _property(template, "ids")
        self.assertEqual((ids["itemType"], ids["value"]), ("String", ["${id}"]))
        self.assertEqual(ids["constraints"], {"notEmpty": True})
        self.assertEqual(_property(template, "day")["constraints"], {"notEmpty": True})
        self.assertNotIn("constraints", _property(template, "note"))
        self.assertEqual(_property(template, "note")["value"], "")
        self.assertEqual(_property(template, "count")["type"], "String")
        self.assertIs(_property(template, "dryRun")["value"], False)
        self.assertEqual(
            _property(template, "${greeting}"),
            {
                "label": "Greeting",
                "description": "Text",
                "type": "String",
                "value": "greeting",
                "group": "outputs",
                "binding": {
                    "type": "camunda:outputParameter",
                    "source": "${greeting}",
                },
            },
        )
        self.assertNotIn("description", _property(template, "${result}"))

    def test_contracts_require_aliases_titles_and_supported_types(self) -> None:
        class NoAlias(TaskContract):
            value: str = Field(title="Value")

        class NoTitle(TaskContract):
            value: str = Field(alias="value")

        class Unsupported(TaskContract):
            value: int = Field(alias="value", title="Value")

        for model, message in (
            (NoAlias, "needs an alias"),
            (NoTitle, "needs a title"),
            (Unsupported, "add a type hint"),
        ):
            spec = TaskTemplate(
                topic="t",
                template_id="t",
                name="t",
                description="t",
                filename="t.json",
                inputs=model,
                outputs=DemoOutput,
            )
            with self.assertRaisesRegex(TemplateError, message):
                render(spec, icon_svg=b"", schema_url=SCHEMA_URL)

    def test_group_ids_must_be_declared(self) -> None:
        spec = TaskTemplate(**{**DEMO.__dict__, "output_group": "missing"})
        with self.assertRaisesRegex(TemplateError, "unknown group id 'missing'"):
            render(spec, icon_svg=b"", schema_url=SCHEMA_URL)

    def test_single_group_holds_inputs_and_outputs(self) -> None:
        spec = TaskTemplate(
            **{
                **DEMO.__dict__,
                "groups": (TemplateGroup("main", "Main"),),
                "input_group": "main",
                "output_group": "main",
            }
        )
        template = render(spec, icon_svg=b"", schema_url=SCHEMA_URL)
        self.assertEqual(template["groups"], [{"id": "main", "label": "Main"}])
        self.assertEqual(
            {prop.get("group") for prop in template["properties"]}, {None, "main"}
        )

    def test_render_rejects_values_and_types_the_schema_rejects(self) -> None:
        class BadAlias(TaskContract):
            value: str = Field(alias="a-b", title="Value")

        class BogusType(TaskContract):
            value: str = Field(
                alias="value",
                title="Value",
                json_schema_extra=template_hints(type="Map"),
            )

        class DropdownWithoutChoices(TaskContract):
            value: str = Field(
                alias="value",
                title="Value",
                json_schema_extra=template_hints(type="Dropdown"),
            )

        class WrongValue(TaskContract):
            value: int = Field(
                alias="value",
                title="Value",
                default=3,
                json_schema_extra=template_hints(type="String"),
            )

        class Optional(TaskContract):
            value: str | None = Field(alias="value", title="Value")

        for model, message in (
            (BadAlias, "plain identifier"),
            (BogusType, "'Map' is not one of"),
            (DropdownWithoutChoices, "needs Literal choices"),
            (WrongValue, "does not fit template type String"),
            (Optional, "anyOf="),
        ):
            spec = TaskTemplate(**{**DEMO.__dict__, "inputs": model})
            with self.subTest(model=model.__name__):
                with self.assertRaisesRegex(TemplateError, message):
                    render(spec, icon_svg=b"", schema_url=SCHEMA_URL)

    def test_template_hints_reject_unknown_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "label"):
            template_hints(label="x")

    def test_contracts_reject_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            DemoOutput.model_validate({"greeting": "hi", "result": {}, "extra": 1})


class FakeBuiltIn:
    def __init__(self, variables: dict[str, Any]) -> None:
        self.variables = variables

    def get_variable_value(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)


class ValidateTaskInputTests(unittest.TestCase):
    def validate(self, contract: str, **variables: Any) -> dict[str, Any]:
        builtin = FakeBuiltIn(
            {f"${{{key}}}": value for key, value in variables.items()}
        )
        with patch.object(robotframework, "BuiltIn", return_value=builtin):
            result: dict[str, Any] = OperatonContractsLibrary(
                __name__
            ).validate_task_input(contract)
        return result

    def test_reads_aliases_normalizes_and_applies_defaults(self) -> None:
        self.assertEqual(
            self.validate(
                "DemoInput",
                name=" Ada ",
                mode="long",
                ids=["i-1"],
                day="2026-01-02",
                count=3,
                unrelated="ignored",
            ),
            {
                "name": "Ada",
                "mode": "long",
                "tags": [],
                "ids": ["i-1"],
                "day": "2026-01-02",
                "note": "",
                "count": 3,
                "dryRun": False,
            },
        )

    def test_rejects_invalid_values_and_unknown_contracts(self) -> None:
        with self.assertRaisesRegex(ValidationError, "dryRun"):
            self.validate(
                "DemoInput",
                name="Ada",
                mode="long",
                ids=["i-1"],
                day="2026-01-02",
                count=3,
                dryRun="false",
            )
        for name in ("Missing", "SCHEMA_URL", "FakeBuiltIn"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "not a TaskContract"):
                    self.validate(name)


class PackageCheckTests(unittest.TestCase):
    def test_demo_package_is_consistent(self) -> None:
        with DemoPackage() as package:
            self.assertEqual(check_package(package.root, [DEMO]), [])

    def test_check_reports_topic_and_suite_mismatches(self) -> None:
        pyproject = DEMO_PYPROJECT + (
            '\n[tool.purjo.topics."demo.unmapped"]\nname = "Greet"\n'
            '\n[tool.purjo.topics."demo.process"]\nname = "Greet"\n'
            '\n[tool.purjo.topics."legacy.topic"]\nname = "Missing"\n'
            "process-variables = false\n"
        )
        suite = DEMO_SUITE.replace("${note}    ${EMPTY}\n", "").replace(
            "    VAR    ${result}=    ${{{}}}    scope=${BPMN:TASK}\n", ""
        )
        process = TaskTemplate(**{**DEMO.__dict__, "topic": "demo.process"})
        legacy = TaskTemplate(
            **{**DEMO.__dict__, "topic": "legacy.topic", "filename": "legacy.json"}
        )
        missing = TaskTemplate(**{**DEMO.__dict__, "topic": "demo.missing"})
        with DemoPackage(pyproject, suite) as package:
            errors = check_package(
                package.root,
                [DEMO, process, legacy, missing],
                reserved_topics=["legacy.topic"],
            )
        self.assertEqual(
            errors,
            [
                "Duplicate template id: fi.example.demo-greet",
                "Duplicate template id: fi.example.demo-greet",
                "Duplicate template id: fi.example.demo-greet",
                "Duplicate filename: demo-greet.json",
                "Duplicate filename: demo-greet.json",
                "Topic is reserved: legacy.topic",
                "Topic has no template spec: demo.unmapped",
                "greet.robot: input 'note' needs a default in *** Variables ***",
                "greet.robot: task 'Greet' must set output 'result' with "
                "VAR ... scope=${BPMN:TASK}",
                "demo.process: set process-variables = false",
                "greet.robot: input 'note' needs a default in *** Variables ***",
                "greet.robot: task 'Greet' must set output 'result' with "
                "VAR ... scope=${BPMN:TASK}",
                "legacy.topic: no Robot suite defines task 'Missing'",
                "Topic missing from [tool.purjo.topics]: demo.missing",
            ],
        )

    def test_check_requires_input_validation_in_task(self) -> None:
        suite = DEMO_SUITE.replace(
            "    ${input}=    OperatonContracts.Validate Task Input    DemoInput\n",
            "    Validate Task Input\n    validate_task_input    OtherInput\n",
        )
        with DemoPackage(suite=suite) as package:
            self.assertEqual(
                check_package(package.root, [DEMO]),
                [
                    "greet.robot: task 'Greet' must call "
                    "Validate Task Input    DemoInput"
                ],
            )

    def test_check_requires_typed_defaults_for_non_string_inputs(self) -> None:
        suite = DEMO_SUITE.replace("${count: int}    0", "${count}    0").replace(
            "${dry_run}    ${False}", "${dryRun}    false"
        )
        with DemoPackage(suite=suite) as package:
            self.assertEqual(
                check_package(package.root, [DEMO]),
                [
                    "greet.robot: default of ${count} is a string; use a typed "
                    "default such as ${False}, ${0}, or @{EMPTY}",
                    "greet.robot: default of ${dryRun} is a string; use a typed "
                    "default such as ${False}, ${0}, or @{EMPTY}",
                ],
            )

    def test_check_treats_empty_and_none_defaults_as_untyped(self) -> None:
        for value in ("${EMPTY}", "${None}"):
            with self.subTest(value=value):
                suite = DEMO_SUITE.replace(
                    "${dry_run}    ${False}", f"${{dryRun}}    {value}"
                )
                with DemoPackage(suite=suite) as package:
                    self.assertEqual(
                        check_package(package.root, [DEMO]),
                        [
                            f"greet.robot: default of ${{dryRun}} is a string; use "
                            "a typed default such as ${False}, ${0}, or @{EMPTY}"
                        ],
                    )

    def test_check_skips_virtual_environments(self) -> None:
        with DemoPackage() as package:
            suite = (package.root / "greet.robot").read_text()
            for relative in ("x/venv/dup.robot", "env/lib/site-packages/dup.robot"):
                (package.root / relative).parent.mkdir(parents=True)
                (package.root / relative).write_text(suite)
            (package.root / "custom-env").mkdir()
            (package.root / "custom-env" / "pyvenv.cfg").write_text("")
            (package.root / "custom-env" / "dup.robot").write_text(suite)
            self.assertEqual(check_package(package.root, [DEMO]), [])

    def test_check_collects_suites_recursively_and_rejects_duplicates(self) -> None:
        with DemoPackage() as package:
            suite = (package.root / "greet.robot").read_text()
            (package.root / "greet.robot").unlink()
            for relative in ("tasks/greet.robot", "tests/greet.robot", ".x/g.robot"):
                (package.root / relative).parent.mkdir(exist_ok=True)
                (package.root / relative).write_text(suite)
            (package.root / "test_greet.robot").write_text(suite)
            self.assertEqual(check_package(package.root, [DEMO]), [])

            (package.root / "other.robot").write_text(suite)
            self.assertEqual(
                check_package(package.root, [DEMO]),
                [
                    "demo.greet: task 'Greet' is defined in several suites "
                    "(other.robot, tasks/greet.robot); purjo would run all of them"
                ],
            )

    def test_check_handles_pyproject_without_topics(self) -> None:
        with DemoPackage(pyproject="") as package:
            self.assertEqual(
                check_package(package.root, [DEMO]),
                ["Topic missing from [tool.purjo.topics]: demo.greet"],
            )

    def test_variable_names_are_unwrapped_and_untyped(self) -> None:
        for token, name in (
            ("${x}", "x"),
            ("@{x: list[str]}", "x"),
            ("x", "x"),
            ("BPMN:TASK", "BPMN"),
        ):
            with self.subTest(token=token):
                self.assertEqual(robotframework._variable_name(token), name)


class CommandTests(unittest.TestCase):
    def test_generate_then_check_round_trip_and_drift(self) -> None:
        with DemoPackage() as package, redirect_stdout(io.StringIO()):
            template_dir = package.root / ".operaton/element-templates"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(package.main("check"), 1)
            self.assertIn("Out of date: demo-greet.json", stderr.getvalue())

            self.assertEqual(package.main("generate"), 0)
            self.assertEqual(package.main(), 0)

            stale = template_dir / "renamed.json"
            stale.write_text("{}\n")
            self.assertEqual(package.main("generate"), 0)
            self.assertFalse(stale.exists())

            (template_dir / "demo-greet.json").write_text("{}\n")
            (template_dir / "stray.json").write_text("{}\n")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(package.main("check"), 1)
            self.assertEqual(
                stderr.getvalue().splitlines(),
                [
                    "Stray element template: stray.json",
                    "Out of date: demo-greet.json; run generate",
                ],
            )

    def test_validate_uses_pinned_schema(self) -> None:
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema",
            "type": "object",
            "required": ["name"],
        }
        with DemoPackage() as package, redirect_stdout(io.StringIO()) as stdout:
            package.main("generate")
            with patch.object(
                operaton_templates,
                "urlopen",
                return_value=SchemaResponse(json.dumps(schema).encode()),
            ) as urlopen:
                self.assertEqual(package.main("validate"), 0)
            urlopen.assert_called_once_with(SCHEMA_URL, timeout=30)
        self.assertIn("Validated demo-greet.json", stdout.getvalue())

    def test_validate_reports_failures_without_tracebacks(self) -> None:
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema",
            "type": "object",
            "required": ["missing"],
        }
        with DemoPackage() as package:
            cases: list[tuple[Any, str]] = [
                (None, "No element templates"),
                (
                    SchemaResponse(json.dumps(schema).encode()),
                    "'missing' is a required",
                ),
                (OSError("offline"), "Cannot load the schema"),
                (SchemaResponse(b"not json"), "Cannot load the schema"),
            ]
            for response, message in cases:
                with self.subTest(message=message):
                    if response is not None:
                        with redirect_stdout(io.StringIO()):
                            package.main("generate")
                    stderr = io.StringIO()
                    with (
                        redirect_stderr(stderr),
                        patch.object(
                            operaton_templates,
                            "urlopen",
                            side_effect=(
                                response if isinstance(response, OSError) else None
                            ),
                            return_value=response,
                        ),
                    ):
                        self.assertEqual(package.main("validate"), 1)
                    self.assertIn(message, stderr.getvalue())

    def test_validate_explains_the_missing_templates_extra(self) -> None:
        with DemoPackage() as package, redirect_stdout(io.StringIO()):
            package.main("generate")
            stderr = io.StringIO()
            with redirect_stderr(stderr), patch.dict(sys.modules, {"jsonschema": None}):
                self.assertEqual(package.main("validate"), 1)
        self.assertIn("operaton-contracts[templates]", stderr.getvalue())


class ContractImportTests(unittest.TestCase):
    def test_contracts_module_falls_back_to_the_suite_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "fallback_contracts.py").write_text(
                f"from {__name__} import DemoInput\n"
            )
            suite = Path(directory) / "suite.robot"
            builtin = FakeBuiltIn({"${SUITE SOURCE}": str(suite)})
            with (
                patch.object(robotframework, "BuiltIn", return_value=builtin),
                patch.object(sys, "path", list(sys.path)),
            ):
                library = OperatonContractsLibrary("fallback_contracts")
                self.assertEqual(sys.path[0], directory)
            self.assertEqual(library._module.__name__, "fallback_contracts")
            sys.modules.pop("fallback_contracts")

    def test_suite_directory_handles_directories_and_missing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for source, expected in ((directory, directory), ("", None)):
                builtin = FakeBuiltIn({"${SUITE SOURCE}": source})
                with patch.object(robotframework, "BuiltIn", return_value=builtin):
                    self.assertEqual(robotframework._suite_directory(), expected)

    def test_import_errors_are_raised_when_no_fallback_applies(self) -> None:
        # Robot is not running: no suite directory to fall back to.
        with self.assertRaises(ModuleNotFoundError):
            OperatonContractsLibrary("missing_contracts_module")
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "broken_contracts.py").write_text(
                "import missing_dependency_module\n"
            )
            builtin = FakeBuiltIn({"${SUITE SOURCE}": directory})
            with (
                patch.object(robotframework, "BuiltIn", return_value=builtin),
                patch.object(sys, "path", [directory, *sys.path]),
            ):
                # The suite directory is already on sys.path.
                with self.assertRaises(ModuleNotFoundError):
                    OperatonContractsLibrary("still_missing_contracts")
                # A missing dependency of the contracts module is re-raised.
                with self.assertRaisesRegex(ModuleNotFoundError, "dependency"):
                    OperatonContractsLibrary("broken_contracts")


class CommandLineTests(unittest.TestCase):
    def test_configuration_errors_exit_with_status_2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cli.main(["--root", directory]), 2)
                (root / "pyproject.toml").write_text("[tool.other]\n")
                self.assertEqual(cli.main(["--root", directory]), 2)
                (root / "not_specs.py").write_text("TEMPLATES = ('x',)\n")
                (root / "pyproject.toml").write_text(
                    '[tool.operaton-contracts]\nspecs = "not_specs"\n'
                )
                self.assertEqual(cli.main(["--root", directory]), 2)
            lines = stderr.getvalue().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertTrue(lines[0].endswith("pyproject.toml not found"))
            self.assertIn('specs = "module:ATTRIBUTE"', lines[1])
            self.assertTrue(
                lines[2].endswith("must be a non-empty sequence of TaskTemplate")
            )

    def test_invalid_configuration_values_are_reported(self) -> None:
        cases = (
            ('specs = "no_such_specs_module"', "Cannot import the specs module"),
            ('specs = "cfg_specs:MISSING"', "non-empty sequence"),
            ('specs = "cfg_specs:EMPTY"', "non-empty sequence"),
            ('specs = "cfg_specs"\nreserved-topics = "abc"', "reserved-topics"),
            ('specs = "cfg_specs"\nreserved-topics = [1]', "reserved-topics"),
            ('specs = "cfg_specs"\nschema-url = 1', "schema-url"),
            ('specs = "cfg_specs"\nicon = "missing.svg"', "icon 'missing.svg'"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cfg_specs.py").write_text(
                f"from {__name__} import DEMO\n\nTEMPLATES = (DEMO,)\nEMPTY = ()\n"
            )
            for table, message in cases:
                with self.subTest(table=table):
                    (root / "pyproject.toml").write_text(
                        f"[tool.operaton-contracts]\n{table}\n"
                    )
                    with self.assertRaisesRegex(cli.ConfigError, message):
                        cli.load_config(root)
            sys.modules.pop("cfg_specs", None)

    def test_specs_cached_from_another_root_are_reloaded(self) -> None:
        roots = []
        try:
            for topic in ("first.topic", "second.topic"):
                directory = tempfile.mkdtemp()
                roots.append(directory)
                root = Path(directory)
                (root / "shared_specs.py").write_text(
                    f"from dataclasses import replace\nfrom {__name__} import DEMO\n"
                    f"TEMPLATES = (replace(DEMO, topic={topic!r}),)\n"
                )
                (root / "pyproject.toml").write_text(
                    '[tool.operaton-contracts]\nspecs = "shared_specs"\n'
                )
                self.assertEqual(cli.load_config(root).specs[0].topic, topic)
            # The same root reuses its cached module.
            self.assertEqual(
                cli.load_config(Path(roots[1])).specs[0].topic, "second.topic"
            )
            sys.modules["shared_specs"].__file__ = None
            self.assertEqual(
                cli.load_config(Path(roots[1])).specs[0].topic, "second.topic"
            )
        finally:
            sys.modules.pop("shared_specs", None)
            for directory in roots:
                shutil.rmtree(directory)

    def test_configuration_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "default_specs.py").write_text(
                f"from {__name__} import DEMO\n\nTEMPLATES = (DEMO,)\n"
            )
            (root / "pyproject.toml").write_text(
                '[tool.operaton-contracts]\nspecs = "default_specs"\n'
            )
            config = cli.load_config(root)
        self.assertEqual(config.specs, (DEMO,))
        self.assertEqual(config.icon_svg, b"")
        self.assertEqual(config.schema_url, operaton_templates.DEFAULT_SCHEMA_URL)
        self.assertEqual(config.reserved_topics, ())

    def test_module_entry_point(self) -> None:
        with DemoPackage() as package, redirect_stdout(io.StringIO()) as stdout:
            with patch.object(
                sys,
                "argv",
                ["operaton-contracts", "generate", "--root", str(package.root)],
            ):
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_module("OperatonContracts", run_name="__main__")
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Wrote demo-greet.json", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
