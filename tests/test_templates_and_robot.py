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
from dataclasses import replace
from datetime import date
from pathlib import Path
from enum import Enum
from enum import IntEnum
from typing import Annotated
from typing import Any
from typing import Literal
from typing import cast
from unittest.mock import patch

from jsonschema import Draft7Validator
from pydantic import Field
from pydantic import StringConstraints
from pydantic import ValidationError
from pydantic import create_model
from pydantic import model_validator

import OperatonContracts
from OperatonContracts import OperatonContracts as OperatonContractsLibrary
from OperatonContracts import TaskContract
from OperatonContracts import template_hints
from OperatonContracts import cli
from OperatonContracts import robotframework
from OperatonContracts.checks import check_package
from OperatonContracts import templates as operaton_templates
from OperatonContracts.templates import ElementType
from OperatonContracts.templates import TaskTemplate
from OperatonContracts.templates import TemplateError
from OperatonContracts.templates import TemplateGroup
from OperatonContracts.templates import drift
from OperatonContracts.templates import dumps
from OperatonContracts.templates import render
from OperatonContracts.templates import write_templates

SCHEMA_URL = "https://example.invalid/schema.json"
# A copy of the pinned upstream schema, so rendered templates validate offline.
UPSTREAM_SCHEMA = (
    Path(__file__).parent / "data" / "operaton-element-templates-schema-v0.8.3.json"
)


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
    VAR    ${result}=    ${None}    scope=${BPMN:TASK}
    VAR    ${greeting}=    ${NONE}    scope=BPMN:TASK
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

    def test_element_types_set_applies_to_and_event_definitions(self) -> None:
        class NoOutput(TaskContract):
            pass

        validator = Draft7Validator(json.loads(UPSTREAM_SCHEMA.read_text()))
        message = "bpmn:MessageEventDefinition"
        expected: dict[ElementType, dict[str, Any]] = {
            ElementType.SERVICE_TASK: {"appliesTo": ["bpmn:ServiceTask"]},
            ElementType.SEND_TASK: {"appliesTo": ["bpmn:SendTask"]},
            ElementType.BUSINESS_RULE_TASK: {"appliesTo": ["bpmn:BusinessRuleTask"]},
            ElementType.MESSAGE_INTERMEDIATE_THROW_EVENT: {
                "appliesTo": ["bpmn:IntermediateThrowEvent"],
                "elementType": {
                    "value": "bpmn:IntermediateThrowEvent",
                    "eventDefinition": message,
                },
            },
            ElementType.MESSAGE_END_EVENT: {
                "appliesTo": ["bpmn:EndEvent"],
                "elementType": {"value": "bpmn:EndEvent", "eventDefinition": message},
            },
        }
        self.assertEqual(set(expected), set(ElementType))
        for element_type, fields in expected.items():
            outputs = (
                NoOutput if element_type.name == "MESSAGE_END_EVENT" else DemoOutput
            )
            spec = replace(DEMO, element_type=element_type, outputs=outputs)
            template = render(spec, icon_svg=b"", schema_url=SCHEMA_URL)
            with self.subTest(element_type=element_type.name):
                self.assertEqual({key: template[key] for key in fields}, fields)
                self.assertEqual("elementType" in template, "elementType" in fields)
                # The forked modeler moves these bindings onto the event
                # definition named in elementType.
                self.assertEqual(
                    [prop["binding"]["name"] for prop in template["properties"][:2]],
                    ["camunda:type", "camunda:topic"],
                )
                self.assertEqual(
                    [error.message for error in validator.iter_errors(template)], []
                )
        self.assertEqual(DEMO.element_type, ElementType.SERVICE_TASK)

        end_with_outputs = replace(DEMO, element_type=ElementType.MESSAGE_END_EVENT)
        with self.assertRaisesRegex(
            TemplateError, "message end event cannot map outputs"
        ):
            render(end_with_outputs, icon_svg=b"", schema_url=SCHEMA_URL)

        bad = replace(DEMO, element_type=cast(Any, "bpmn:ServiceTask"))
        with self.assertRaisesRegex(
            TemplateError, "element_type must be an ElementType"
        ):
            render(bad, icon_svg=b"", schema_url=SCHEMA_URL)

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
                json_schema_extra=template_hints(type="Bogus"),
            )

        class MapOfString(TaskContract):
            value: str = Field(
                alias="value",
                title="Value",
                json_schema_extra=template_hints(type="Map"),
            )

        class MapOfModel(TaskContract):
            value: dict[str, int] = Field(
                alias="value",
                title="Value",
                json_schema_extra=template_hints(type="Map"),
            )

        class MapWithValue(TaskContract):
            value: dict[str, str] = Field(
                alias="value",
                title="Value",
                json_schema_extra=template_hints(value="${value}"),
            )

        class MapWithDefault(TaskContract):
            value: dict[str, str] = Field(
                alias="value", title="Value", default={"a": "b"}
            )

        class EntriesOnString(TaskContract):
            value: str = Field(
                alias="value",
                title="Value",
                json_schema_extra=template_hints(entries=[{"key": "a"}]),
            )

        def entries(hint: Any) -> type[TaskContract]:
            class BadEntries(TaskContract):
                value: dict[str, str] = Field(
                    alias="value",
                    title="Value",
                    json_schema_extra=template_hints(entries=hint),
                )

            return BadEntries

        class UnknownGroup(TaskContract):
            value: str = Field(
                alias="value",
                title="Value",
                json_schema_extra=template_hints(group="missing"),
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
            (BogusType, "'Bogus' is not one of"),
            (MapOfString, "a Map needs a dict"),
            (MapOfModel, "a Map needs a dict"),
            (MapWithValue, "a Map takes no value"),
            (MapWithDefault, "a Map takes no value"),
            (EntriesOnString, "entries need a Map"),
            (entries([]), "non-empty list"),
            (entries({"key": "a"}), "non-empty list"),
            (entries(["a"]), "string key"),
            (entries([{"label": "A"}]), "string key"),
            (entries([{"key": "a", "bogus": 1}]), "unknown entry key"),
            (entries([{"key": "a", "type": "List"}]), "entry type 'List'"),
            (entries([{"key": "a"}, {"key": "a"}]), "must be unique"),
            (UnknownGroup, "unknown group id 'missing'"),
            (DropdownWithoutChoices, "needs Literal choices"),
            (WrongValue, "does not fit template type String"),
            (Optional, "anyOf="),
        ):
            spec = TaskTemplate(**{**DEMO.__dict__, "inputs": model})
            with self.subTest(model=model.__name__):
                with self.assertRaisesRegex(TemplateError, message):
                    render(spec, icon_svg=b"", schema_url=SCHEMA_URL)

    def test_render_maps_string_dicts_to_map_properties(self) -> None:
        class MapInput(TaskContract):
            open: dict[str, str] = Field(alias="open", title="Open")
            fixed: dict[Literal["fi", "en"], str] = Field(
                alias="fixed", title="Fixed", default_factory=dict
            )
            labeled: dict[str, str] = Field(
                alias="labeled",
                title="Labeled",
                min_length=1,
                default_factory=dict,
                json_schema_extra=template_hints(
                    group="extra",
                    entries=[
                        {"key": "fi", "label": "Suomeksi"},
                        {"key": "en", "label": "In English", "type": "Text"},
                    ],
                ),
            )
            text: dict[str, str] = Field(
                alias="text",
                title="Text",
                json_schema_extra=template_hints(type="String"),
            )

        spec = TaskTemplate(
            **{
                **DEMO.__dict__,
                "inputs": MapInput,
                "groups": (
                    *operaton_templates.DEFAULT_GROUPS,
                    TemplateGroup("extra", "Extra"),
                ),
            }
        )
        template = render(spec, icon_svg=b"", schema_url=SCHEMA_URL)
        binding = {"type": "camunda:inputParameter"}
        self.assertEqual(
            _property(template, "open"),
            {
                "label": "Open",
                "type": "Map",
                "group": "inputs",
                "binding": {**binding, "name": "open"},
                "additionalEntries": True,
            },
        )
        self.assertEqual(
            _property(template, "fixed"),
            {
                "label": "Fixed",
                "type": "Map",
                "group": "inputs",
                "binding": {**binding, "name": "fixed"},
                "entries": [{"key": "fi"}, {"key": "en"}],
            },
        )
        self.assertEqual(
            _property(template, "labeled"),
            {
                "label": "Labeled",
                "type": "Map",
                "group": "extra",
                "binding": {**binding, "name": "labeled"},
                "entries": [
                    {"key": "fi", "label": "Suomeksi"},
                    {"key": "en", "label": "In English", "type": "Text"},
                ],
            },
        )
        self.assertEqual(_property(template, "text")["type"], "String")
        self.assertEqual(_property(template, "text")["value"], "${text}")

    def test_render_maps_key_and_value_schemas(self) -> None:
        class Locale(str, Enum):
            FI = "fi"
            EN = "en"

        class MapInput(TaskContract):
            single: dict[Literal["fi"], str] = Field(alias="single", title="Single")
            enum: dict[Locale, str] = Field(alias="enum", title="Enum")
            pattern: dict[
                Annotated[str, StringConstraints(pattern="^[a-z]{2}$")], str
            ] = Field(alias="pattern", title="Pattern", default={})
            names: dict[
                Annotated[str, StringConstraints(pattern="^x")],
                Annotated[str, StringConstraints(min_length=2, max_length=9)],
            ] = Field(alias="names", title="Names")
            values: dict[str, Annotated[str, StringConstraints(pattern="^v")]] = Field(
                alias="values", title="Values"
            )
            choice: dict[Literal["a", "b"], Literal["x", "y"]] = Field(
                alias="choice",
                title="Choice",
                json_schema_extra=template_hints(entries=[{"key": "a", "label": "A"}]),
            )
            nonempty: dict[str, Annotated[str, StringConstraints(min_length=1)]] = (
                Field(
                    alias="nonempty",
                    title="Non-empty",
                    json_schema_extra=template_hints(
                        entries=[
                            {"key": "fi", "optional": True, "constraints": {}},
                            {"key": "on", "type": "Boolean", "value": True},
                            {
                                "key": "pick",
                                "type": "Dropdown",
                                "choices": [{"name": "A", "value": "a"}],
                            },
                        ]
                    ),
                )
            )

        spec = TaskTemplate(**{**DEMO.__dict__, "inputs": MapInput})
        template = render(spec, icon_svg=b"", schema_url=SCHEMA_URL)
        maps = {
            prop["binding"]["name"]: {
                key: prop[key]
                for key in ("constraints", "entries", "additionalEntries")
                if key in prop
            }
            for prop in template["properties"]
            if prop["type"] == "Map"
        }
        self.assertEqual(
            maps,
            {
                "single": {"entries": [{"key": "fi"}]},
                "enum": {"entries": [{"key": "fi"}, {"key": "en"}]},
                "pattern": {
                    "constraints": {"keyPattern": "^[a-z]{2}$"},
                    "additionalEntries": True,
                },
                "names": {
                    "constraints": {
                        "notEmpty": True,
                        "minLength": 2,
                        "maxLength": 9,
                        "keyPattern": "^x",
                    },
                    "additionalEntries": True,
                },
                "values": {
                    "constraints": {"pattern": "^v"},
                    "additionalEntries": True,
                },
                "choice": {
                    "entries": [
                        {
                            "key": "a",
                            "label": "A",
                            "type": "Dropdown",
                            "choices": [
                                {"name": "x", "value": "x"},
                                {"name": "y", "value": "y"},
                            ],
                        }
                    ]
                },
                "nonempty": {
                    "constraints": {"notEmpty": True},
                    "entries": [
                        {"key": "fi", "optional": True, "constraints": {}},
                        {"key": "on", "type": "Boolean", "value": True},
                        {
                            "key": "pick",
                            "type": "Dropdown",
                            "choices": [{"name": "A", "value": "a"}],
                        },
                    ],
                },
            },
        )
        validator = Draft7Validator(json.loads(UPSTREAM_SCHEMA.read_text()))
        self.assertEqual(
            [error.message for error in validator.iter_errors(template)], []
        )

    def test_render_rejects_map_shapes_and_entries_the_schema_rejects(self) -> None:
        class IntKey(IntEnum):
            ONE = 1

        def contract(annotation: Any, **hints: Any) -> type[TaskContract]:
            return create_model(
                "MapContract",
                __base__=TaskContract,
                value=(
                    annotation,
                    Field(
                        alias="value",
                        title="Value",
                        json_schema_extra=template_hints(**hints),
                    ),
                ),
            )

        def entry(**fields: Any) -> type[TaskContract]:
            return contract(dict[str, str], entries=[{"key": "a", **fields}])

        for model, message in (
            (contract(dict[str, str], value="x"), "a Map takes no value"),
            (contract(dict[Literal["a"], str], entries=[{"key": "b"}]), "not one of"),
            (
                contract(
                    dict[Annotated[str, StringConstraints(pattern="^a")], str],
                    entries=[{"key": "b"}],
                ),
                "does not match '\\^a'",
            ),
            (
                contract(dict[Annotated[str, StringConstraints(min_length=2)], str]),
                "unsupported map key schema",
            ),
            (contract(dict[str, Literal["x", "y"]]), "need fixed keys"),
            (
                contract(
                    dict[str, Literal["x"]], entries=[{"key": "a", "type": "Text"}]
                ),
                "must be a Dropdown",
            ),
            (
                contract(
                    dict[Literal["a"], Literal["x", "y"]],
                    entries=[{"key": "a", "value": "z"}],
                ),
                "value 'z' of entry 'a' is not one of its choices",
            ),
            (
                contract(
                    dict[Literal["a"], Literal["x", "y"]],
                    entries=[
                        {
                            "key": "a",
                            "type": "Dropdown",
                            "choices": [
                                {"name": "X", "value": "x"},
                                {"name": "Z", "value": "z"},
                            ],
                        }
                    ],
                ),
                "choices 'z' of entry 'a' are not contract values x, y",
            ),
            (
                entry(
                    type="Dropdown",
                    choices=[{"name": "A", "value": "a"}],
                    value="b",
                ),
                "value 'b' of entry 'a' is not one of its choices",
            ),
            (contract(dict[IntKey, str]), "unsupported map key schema"),
            (entry(key=""), "must not be empty"),
            (entry(value=5), "must be a str"),
            (entry(type="Boolean", value="true"), "must be a bool"),
            (entry(type="Dropdown"), "needs choices"),
            (entry(choices=[{"name": "a", "value": "a"}]), "cannot have choices"),
            (entry(type="Hidden", placeholder="x"), "cannot have placeholder"),
            (entry(type="Boolean", constraints={}), "cannot have constraints"),
            (entry(label=1), "label of entry 'a' must be a string"),
            (entry(editable="no"), "editable of entry 'a' must be a boolean"),
            (entry(type="Dropdown", choices=[]), "non-empty list"),
            (entry(type="Dropdown", choices=[{"name": "a"}]), "non-empty list"),
            (entry(type="Dropdown", choices=[{"name": "a", "value": 1}]), "name/value"),
            (entry(constraints={"bogus": 1}), "may only set"),
            (entry(constraints=[]), "may only set"),
            (
                entry(optional=True, constraints={"notEmpty": True}),
                "both optional and notEmpty",
            ),
        ):
            spec = TaskTemplate(**{**DEMO.__dict__, "inputs": model})
            with self.subTest(message=message):
                with self.assertRaisesRegex(TemplateError, message):
                    render(spec, icon_svg=b"", schema_url=SCHEMA_URL)

    def test_output_hints_rename_skip_or_regroup_mappings(self) -> None:
        class HintedOutput(TaskContract):
            skipped: str = Field(
                alias="skipped",
                title="Skipped",
                json_schema_extra=template_hints(value=""),
            )
            renamed: str = Field(
                alias="renamed",
                title="Renamed",
                json_schema_extra=template_hints(value="target", group="inputs"),
            )

        spec = TaskTemplate(**{**DEMO.__dict__, "outputs": HintedOutput})
        template = render(spec, icon_svg=b"", schema_url=SCHEMA_URL)
        self.assertEqual(
            template["properties"][-2:],
            [
                {
                    "label": "Skipped",
                    "type": "String",
                    "value": "",
                    "optional": True,
                    "group": "outputs",
                    "binding": {
                        "type": "camunda:outputParameter",
                        "source": "${skipped}",
                    },
                },
                {
                    "label": "Renamed",
                    "type": "String",
                    "value": "target",
                    "group": "inputs",
                    "binding": {
                        "type": "camunda:outputParameter",
                        "source": "${renamed}",
                    },
                },
            ],
        )
        validator = Draft7Validator(json.loads(UPSTREAM_SCHEMA.read_text()))
        self.assertEqual(
            [error.message for error in validator.iter_errors(template)], []
        )

    def test_render_rejects_unsupported_output_hints(self) -> None:
        def output(**hints: Any) -> type[TaskContract]:
            return create_model(
                "HintedOutput",
                __base__=TaskContract,
                value=(
                    str,
                    Field(
                        alias="value",
                        title="Value",
                        json_schema_extra=template_hints(**hints),
                    ),
                ),
            )

        for model, message in (
            (output(type="Text"), "may only set group, value, not type"),
            (output(value=["x"]), "must be a process variable name"),
            (output(value="${expr}"), "'\\$\\{expr\\}' must be a process variable"),
            (output(value="has space"), "'has space' must be a process variable"),
            (output(group="missing"), "unknown group id 'missing'"),
        ):
            spec = TaskTemplate(**{**DEMO.__dict__, "outputs": model})
            with self.subTest(message=message):
                with self.assertRaisesRegex(TemplateError, message):
                    render(spec, icon_svg=b"", schema_url=SCHEMA_URL)

    def test_render_rejects_outputs_mapped_to_the_same_variable(self) -> None:
        class CollidingOutput(TaskContract):
            first: str = Field(
                alias="first",
                title="First",
                json_schema_extra=template_hints(value="second"),
            )
            second: str = Field(alias="second", title="Second")
            skipped: str = Field(
                alias="skipped",
                title="Skipped",
                json_schema_extra=template_hints(value=""),
            )
            also_skipped: str = Field(
                alias="alsoSkipped",
                title="Also skipped",
                json_schema_extra=template_hints(value=""),
            )

        spec = TaskTemplate(**{**DEMO.__dict__, "outputs": CollidingOutput})
        with self.assertRaisesRegex(
            TemplateError, "outputs map to the same process variable 'second'"
        ):
            render(spec, icon_svg=b"", schema_url=SCHEMA_URL)

    def test_map_schemas_need_one_string_value_schema(self) -> None:
        for schema in (
            {"type": "object", "patternProperties": {"^a": {}, "^b": {}}},
            {
                "type": "object",
                "patternProperties": {"^a": {"type": "string"}},
                "additionalProperties": {"type": "string"},
            },
            {"type": "object", "additionalProperties": {"type": "integer"}},
            {"type": "object", "additionalProperties": True},
        ):
            with self.subTest(schema=schema):
                self.assertIsNone(operaton_templates._map_schemas(schema))

    def test_unresolvable_map_refs_are_kept(self) -> None:
        schema = {"propertyNames": {"$ref": "#/$defs/Missing"}}
        self.assertEqual(operaton_templates._inline_map_refs(schema, {}), schema)

    def test_spec_icons_replace_the_configured_icon(self) -> None:
        spec = TaskTemplate(**{**DEMO.__dict__, "icon": "own.svg"})
        other = TaskTemplate(**{**DEMO.__dict__, "filename": "other.json"})
        rendered = operaton_templates.render_all(
            (spec, other),
            icon_svg=b"<default/>",
            schema_url=SCHEMA_URL,
            icons={"own.svg": b"<own/>"},
        )
        icons = {
            filename: json.loads(text)["icon"]["contents"]
            for filename, text in rendered.items()
        }
        self.assertEqual(
            icons,
            {
                "demo-greet.json": "data:image/svg+xml;base64,PG93bi8+",
                "other.json": "data:image/svg+xml;base64,PGRlZmF1bHQvPg==",
            },
        )
        with self.assertRaisesRegex(TemplateError, "icon 'own.svg' is not loaded"):
            operaton_templates.render_all((spec,), icon_svg=b"", schema_url=SCHEMA_URL)

    def test_template_hints_reject_unknown_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "label"):
            template_hints(label="x")

    def test_contracts_reject_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            DemoOutput.model_validate({"greeting": "hi", "result": {}, "extra": 1})


class RangeInput(TaskContract):
    low: int = Field(alias="low", title="Low")
    high: int = Field(alias="high", title="High")

    @model_validator(mode="after")
    def ordered(self) -> "RangeInput":
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


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
        with self.assertRaises(robotframework.InvalidTaskInput) as raised:
            self.validate(
                "DemoInput",
                name="Ada",
                mode="long",
                ids=["i-1"],
                day="2026-01-02",
                count=3,
                dryRun="false",
            )
        self.assertTrue(raised.exception.ROBOT_SUPPRESS_NAME)
        self.assertEqual(
            str(raised.exception).splitlines(),
            [
                "InvalidTaskInput",
                "DemoInput:",
                "dryRun: Input should be a valid boolean (got 'false')",
            ],
        )
        with self.assertRaises(robotframework.InvalidTaskInput) as raised:
            self.validate("DemoInput", mode="long", ids="x" * 100, day="2026-01-02")
        self.assertEqual(
            str(raised.exception).splitlines()[2:],
            [
                "name: Field required",
                f"ids: Input should be a valid list (got '{'x' * 56}...)",
                "count: Field required",
            ],
        )
        with self.assertRaises(robotframework.InvalidTaskInput) as raised:
            self.validate("RangeInput", low=2, high=1)
        self.assertEqual(
            str(raised.exception).splitlines()[1:],
            ["RangeInput:", "RangeInput: Value error, low must not exceed high"],
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
                "Topic has no template spec: demo.unmapped (add a TaskTemplate for "
                "it, or serve it from another package)",
                "greet.robot: input 'note' needs a default in *** Variables ***",
                "greet.robot: task 'Greet' must set output 'result' with "
                "VAR ... scope=${BPMN:TASK} (a ${None} placeholder does not count)",
                "demo.process: set process-variables = false",
                "greet.robot: input 'note' needs a default in *** Variables ***",
                "greet.robot: task 'Greet' must set output 'result' with "
                "VAR ... scope=${BPMN:TASK} (a ${None} placeholder does not count)",
                "legacy.topic: no Robot suite defines task 'Missing'",
                "Topic missing from [tool.purjo.topics]: demo.missing "
                '(add [tool.purjo.topics."demo.missing"] with the Robot task name)',
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
                    "default such as ${False}, ${0}, @{EMPTY}, or &{EMPTY}",
                    "greet.robot: default of ${dryRun} is a string; use a typed "
                    "default such as ${False}, ${0}, @{EMPTY}, or &{EMPTY}",
                ],
            )

    def test_check_requires_list_and_dictionary_defaults_to_match(self) -> None:
        suite = DEMO_SUITE.replace("@{tags}    @{EMPTY}", "&{tags}    &{EMPTY}")
        suite = suite.replace("${note}    ${EMPTY}", "${note}    @{EMPTY}")
        with DemoPackage(suite=suite) as package:
            self.assertEqual(
                check_package(package.root, [DEMO]),
                [
                    "greet.robot: default of &{tags} is a dictionary, but input "
                    "'tags' is array",
                    "greet.robot: default of ${note} is a list, but input 'note' "
                    "is string",
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
                            "a typed default such as ${False}, ${0}, @{EMPTY}, "
                            "or &{EMPTY}"
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
                [
                    "Topic missing from [tool.purjo.topics]: demo.greet "
                    '(add [tool.purjo.topics."demo.greet"] with the Robot task name)'
                ],
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

    def test_keep_versions_copy_published_versions_from_the_file(self) -> None:
        def render_files(spec: TaskTemplate, template_dir: Path) -> dict[str, str]:
            return operaton_templates.render_all(
                (spec,), icon_svg=b"", schema_url=SCHEMA_URL, template_dir=template_dir
            )

        with tempfile.TemporaryDirectory() as directory:
            template_dir = Path(directory)
            path = template_dir / DEMO.filename
            write_templates(template_dir, render_files(DEMO, template_dir))
            published = json.loads(path.read_text())

            # Version 2 changes the contract and keeps version 1 as published.
            v2 = replace(
                DEMO, version=2, description="Greets twice.", keep_versions=(1,)
            )
            rendered = render_files(v2, template_dir)
            self.assertIn(
                "Out of date: demo-greet.json; run generate",
                drift(template_dir, rendered),
            )
            write_templates(template_dir, rendered)
            templates = json.loads(path.read_text())
            self.assertEqual([t["version"] for t in templates], [2, 1])
            self.assertEqual(templates[1], published)
            self.assertEqual(drift(template_dir, render_files(v2, template_dir)), [])
            validator = Draft7Validator(json.loads(UPSTREAM_SCHEMA.read_text()))
            self.assertEqual(
                [error.message for error in validator.iter_errors(templates)], []
            )

            # Forgetting keep_versions or changing a version is explained.
            v3 = replace(v2, version=3, keep_versions=())
            self.assertEqual(
                drift(template_dir, render_files(v3, template_dir)),
                [
                    "demo-greet.json: version 2 of fi.example.demo-greet would be "
                    "dropped; add it to keep_versions, or run generate to drop it",
                    "demo-greet.json: version 1 of fi.example.demo-greet would be "
                    "dropped; add it to keep_versions, or run generate to drop it",
                    "Out of date: demo-greet.json; run generate",
                ],
            )
            changed = replace(v2, description="Changed.")
            self.assertEqual(
                drift(template_dir, render_files(changed, template_dir)),
                [
                    "demo-greet.json: version 2 of fi.example.demo-greet changed; "
                    "if it is published, bump version and add 2 to keep_versions",
                    "Out of date: demo-greet.json; run generate",
                ],
            )

            for bad, message in (
                (replace(v2, keep_versions=(2,)), "unique versions from 1 to 1"),
                (replace(v2, keep_versions=(1, 1)), "unique versions from 1 to 1"),
                (replace(v2, keep_versions=(0,)), "unique versions from 1 to 1"),
                (replace(v2, keep_versions=cast(Any, ("1",))), "not \\('1',\\)"),
                (replace(v2, keep_versions=cast(Any, (True,))), "not \\(True,\\)"),
                # A common typo: (1) is the integer 1, not a tuple.
                (replace(v2, keep_versions=cast(Any, 1)), "e.g. \\(1,\\), not 1"),
                (replace(v2, version=cast(Any, True)), "version must be an integer"),
                (replace(v2, version=0), "version must be an integer"),
                (
                    replace(v2, version=5, keep_versions=(3,)),
                    "kept version 3 of fi.example.demo-greet is missing",
                ),
            ):
                with self.subTest(keep_versions=bad.keep_versions):
                    with self.assertRaisesRegex(TemplateError, message):
                        render_files(bad, template_dir)
            with self.assertRaisesRegex(TemplateError, "needs the template directory"):
                operaton_templates.render_all(
                    (v2,), icon_svg=b"", schema_url=SCHEMA_URL
                )

            for content, message in (
                ("{", "invalid JSON"),
                ("[1]", "expected template objects"),
            ):
                path.write_text(content)
                with self.subTest(content=content):
                    with self.assertRaisesRegex(TemplateError, message):
                        render_files(v2, template_dir)
                    self.assertEqual(
                        [
                            message in error
                            for error in drift(
                                template_dir, render_files(DEMO, template_dir)
                            )
                        ],
                        [True, False],
                    )

    def test_keep_versions_explain_files_versions_and_ids(self) -> None:
        def render_files(spec: TaskTemplate, template_dir: Path) -> dict[str, str]:
            return operaton_templates.render_all(
                (spec,), icon_svg=b"", schema_url=SCHEMA_URL, template_dir=template_dir
            )

        def published(spec: TaskTemplate) -> dict[str, Any]:
            return render(spec, icon_svg=b"", schema_url=SCHEMA_URL)

        v1, v2, v3 = (replace(DEMO, version=version) for version in (1, 2, 3))
        with tempfile.TemporaryDirectory() as directory:
            template_dir = Path(directory)
            path = template_dir / DEMO.filename
            kept = replace(v3, keep_versions=(2, 1))

            # A renamed file is found by template id; otherwise restore it.
            with self.assertRaisesRegex(TemplateError, "restore the file"):
                render_files(kept, template_dir)
            (template_dir / "broken.json").write_text("{")
            (template_dir / "another.json").write_text(
                dumps({**published(v1), "id": "another.id"})
            )
            (template_dir / "old.json").write_text(
                dumps([published(v2), published(v1)])
            )
            with self.assertRaisesRegex(TemplateError, "rename old.json to demo-greet"):
                render_files(kept, template_dir)
            (template_dir / "old.json").rename(path)
            (template_dir / "broken.json").unlink()
            (template_dir / "another.json").unlink()
            self.assertEqual(
                [
                    t["version"]
                    for t in json.loads(render_files(kept, template_dir)[path.name])
                ],
                [3, 2, 1],
            )

            # A duplicated kept version is not silently resolved.
            path.write_text(dumps([published(v2), published(v2), published(v1)]))
            with self.assertRaisesRegex(TemplateError, "2 .* appears more than once"):
                render_files(kept, template_dir)

            # A downgrade asks for a higher version; other ids are reported.
            other = {**published(v1), "id": "other.id"}
            path.write_text(dumps([published(v3), published(v2), published(v1), other]))
            self.assertEqual(
                drift(
                    template_dir,
                    render_files(replace(v2, keep_versions=(1,)), template_dir),
                ),
                [
                    "demo-greet.json: template 'other.id' would be dropped; it "
                    "belongs in its own file",
                    "demo-greet.json: committed version 3 of fi.example.demo-greet "
                    "is newer than version 2; set version above 3",
                    "Out of date: demo-greet.json; run generate",
                ],
            )

    def test_keep_versions_round_trip_through_the_command(self) -> None:
        with DemoPackage() as package, redirect_stdout(io.StringIO()):
            self.assertEqual(package.main("generate"), 0)
            specs = next(package.root.glob("demo_specs_*.py"))
            specs.write_text(
                f"from dataclasses import replace\nfrom {__name__} import DEMO\n\n"
                "TEMPLATES = (replace(DEMO, version=2, keep_versions=(1,)),)\n"
            )
            sys.modules.pop(specs.stem, None)
            self.assertEqual(package.main("generate"), 0)
            self.assertEqual(package.main("check"), 0)
            self.assertEqual(package.main("generate"), 0)
            templates = json.loads(
                (
                    package.root / ".operaton/element-templates/demo-greet.json"
                ).read_text()
            )
            self.assertEqual([t["version"] for t in templates], [2, 1])
            sys.modules.pop(specs.stem, None)

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
            ('specs = "cfg_specs:MISSING_ICON"', "demo.greet: icon 'gone.svg'"),
            ('specs = "cfg_specs:INT_ICON"', "demo.greet: icon 1 is not a file"),
            ('specs = "cfg_specs"\nicon = "../outside.svg"', "icon '../outside.svg'"),
            ('specs = "cfg_specs"\nicon = 1', "icon 1 is not a file"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "package"
            root.mkdir()
            # An existing file outside the root must still be refused.
            (root.parent / "outside.svg").write_bytes(b"<svg/>")
            (root / "cfg_specs.py").write_text(
                f"from dataclasses import replace\nfrom {__name__} import DEMO\n\n"
                "TEMPLATES = (DEMO,)\nEMPTY = ()\n"
                "MISSING_ICON = (replace(DEMO, icon='gone.svg'),)\n"
                "INT_ICON = (replace(DEMO, icon=1),)\n"
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
        self.assertEqual(config.icons, {})

    def test_spec_icons_are_loaded_once_from_the_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "own.svg").write_bytes(b"<own/>")
            (root / "icon_specs.py").write_text(
                f"from dataclasses import replace\nfrom {__name__} import DEMO\n\n"
                "TEMPLATES = (\n"
                "    replace(DEMO, icon='own.svg'),\n"
                "    replace(DEMO, topic='b', filename='b.json', icon='own.svg'),\n"
                ")\n"
            )
            (root / "pyproject.toml").write_text(
                '[tool.operaton-contracts]\nspecs = "icon_specs"\n'
            )
            try:
                config = cli.load_config(root)
            finally:
                sys.modules.pop("icon_specs", None)
        self.assertEqual(config.icons, {"own.svg": b"<own/>"})

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
