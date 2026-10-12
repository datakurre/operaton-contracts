"""Input and output property features of external task element templates."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Literal

from jsonschema import Draft7Validator
from pydantic import Field
from pydantic import StringConstraints
from pydantic import create_model

from OperatonContracts import TaskContract
from OperatonContracts import template_hints
from OperatonContracts.templates import AdditionalInputs
from OperatonContracts.templates import ElementType
from OperatonContracts.templates import ErrorDefinition
from OperatonContracts.templates import TaskSetting
from OperatonContracts.templates import TaskTemplate
from OperatonContracts.templates import TemplateError
from OperatonContracts.templates import TemplateGroup
from OperatonContracts.templates import dumps
from OperatonContracts.templates import render

SCHEMA_URL = "https://example.invalid/schema.json"
UPSTREAM_SCHEMA = (
    Path(__file__).parent / "data" / "operaton-element-templates-schema-v0.8.3.json"
)
Channel = Literal["email", "sms", "push"]
CHANNEL_CHOICES = [
    {"name": "E-mail", "value": "email"},
    {"name": "SMS", "value": "sms"},
    {"name": "Push", "value": "push"},
]


_UNSET: Any = object()


def field(
    annotation: Any,
    default: Any = _UNSET,
    *,
    default_factory: Any = None,
    title: str = "Field",
    **hints: Any,
) -> tuple[Any, dict[str, Any]]:
    """Describe a contract field and its template hints for ``contract``."""
    options: dict[str, Any] = {"title": title}
    if default is not _UNSET:
        options["default"] = default
    if default_factory is not None:
        options["default_factory"] = default_factory
    if hints:
        options["json_schema_extra"] = template_hints(**hints)
    return annotation, options


def contract(
    model_name: str = "Demo", /, **fields: tuple[Any, dict[str, Any]]
) -> type[TaskContract]:
    """Build a contract whose aliases are the given field names."""
    definitions: dict[str, Any] = {
        f"field_{index}": (annotation, Field(alias=alias, **options))
        for index, (alias, (annotation, options)) in enumerate(fields.items())
    }
    model: type[TaskContract] = create_model(
        model_name, __base__=TaskContract, **definitions
    )
    return model


class NoOutput(TaskContract):
    pass


def spec(
    inputs: type[TaskContract] | None = None,
    outputs: type[TaskContract] = NoOutput,
    **options: Any,
) -> TaskTemplate:
    return TaskTemplate(
        topic="showcase.features",
        template_id="org.example.features",
        name="Features",
        description="Every property feature.",
        filename="features.json",
        inputs=inputs or contract(),
        outputs=outputs,
        **options,
    )


def rendered(template_spec: TaskTemplate) -> dict[str, Any]:
    """Render a spec and require the pinned upstream schema to accept it."""
    template = render(template_spec, icon_svg=b"<svg/>", schema_url=SCHEMA_URL)
    Draft7Validator(json.loads(UPSTREAM_SCHEMA.read_text())).validate(template)
    return template


def named(template: dict[str, Any], name: str) -> dict[str, Any]:
    """Return the input property bound to ``name``."""
    return next(
        prop for prop in template["properties"] if prop["binding"].get("name") == name
    )


def sourced(template: dict[str, Any], source: str) -> dict[str, Any]:
    """Return the output property mapped from ``source``."""
    return next(
        prop
        for prop in template["properties"]
        if prop["binding"].get("source") == source
    )


class InputFeatureTests(unittest.TestCase):
    def test_scalar_inputs_take_presentation_and_validation_hints(self) -> None:
        template = rendered(
            spec(
                contract(
                    customerId=field(str, value="${ customerId }"),
                    note=field(
                        str,
                        "",
                        type="Text",
                        value=None,
                        placeholder="Free text or an expression",
                        constraints={"maxLength": 500},
                    ),
                    reference=field(str, "", optional=True),
                    replyTo=field(str, "", optional=True, value="${replyTo}"),
                    code=field(
                        str,
                        value="${guestId}",
                        constraints={
                            "minLength": 3,
                            "pattern": {
                                "value": "^(guest-[0-9a-f-]{36}|\\$\\{.+\\})$",
                                "message": "Use guest-<uuid> or an expression.",
                            },
                        },
                    ),
                    plain=field(str, constraints={"pattern": "^[a-z]+$"}),
                    blank=field(str, constraints={"notEmpty": False}),
                    schemaVersion=field(
                        str, "2", type="Hidden", editable=False, optional=False
                    ),
                    kept=field(str, "", optional=False),
                )
            )
        )
        self.assertEqual(named(template, "customerId")["value"], "${ customerId }")
        note = named(template, "note")
        self.assertEqual(
            (note["type"], note["placeholder"], note["constraints"]),
            ("Text", "Free text or an expression", {"maxLength": 500}),
        )
        self.assertNotIn("value", note)
        # An optional input is left out of the XML when empty, so it has no
        # pre-filled value unless one is hinted.
        reference = named(template, "reference")
        self.assertIs(reference["optional"], True)
        self.assertNotIn("value", reference)
        self.assertNotIn("constraints", reference)
        self.assertEqual(named(template, "replyTo")["value"], "${replyTo}")
        self.assertEqual(
            named(template, "code")["constraints"],
            {
                "notEmpty": True,
                "minLength": 3,
                "pattern": {
                    "value": "^(guest-[0-9a-f-]{36}|\\$\\{.+\\})$",
                    "message": "Use guest-<uuid> or an expression.",
                },
            },
        )
        self.assertEqual(
            named(template, "plain")["constraints"],
            {"notEmpty": True, "pattern": "^[a-z]+$"},
        )
        self.assertNotIn("constraints", named(template, "blank"))
        hidden = named(template, "schemaVersion")
        self.assertEqual(
            (hidden["type"], hidden["value"], hidden["editable"]),
            ("Hidden", "2", False),
        )
        # Only optional=True is rendered.
        self.assertNotIn("optional", hidden)
        self.assertNotIn("optional", named(template, "kept"))

    def test_choices_are_labelled_and_displayed(self) -> None:
        template = rendered(
            spec(
                contract(
                    channel=field(Channel, "email", choices=CHANNEL_CHOICES),
                    template=field(
                        str,
                        "welcome",
                        type="Dropdown",
                        choices=[
                            {"name": "Welcome", "value": "welcome"},
                            {"name": "Reminder", "value": "reminder"},
                        ],
                    ),
                    notifyVia=field(
                        list[Channel],
                        default_factory=list,
                        choices=CHANNEL_CHOICES[:2],
                        display=None,
                        value=["email"],
                        constraints={"minItems": 1, "maxItems": 2},
                    ),
                    flags=field(list[Channel], default_factory=list),
                    boxes=field(
                        list[Channel], default_factory=list, display="checklist"
                    ),
                    free=field(
                        list[str],
                        default_factory=list,
                        choices=[{"name": "Urgent", "value": "urgent"}],
                    ),
                )
            )
        )
        channel = named(template, "channel")
        self.assertEqual(
            (channel["type"], channel["value"], channel["choices"]),
            ("Dropdown", "email", CHANNEL_CHOICES),
        )
        self.assertEqual(
            [choice["value"] for choice in named(template, "template")["choices"]],
            ["welcome", "reminder"],
        )
        notify = named(template, "notifyVia")
        self.assertEqual(notify["choices"], CHANNEL_CHOICES[:2])
        self.assertEqual(notify["constraints"], {"minItems": 1, "maxItems": 2})
        self.assertNotIn("display", notify)
        self.assertNotIn("itemType", notify)
        self.assertEqual(named(template, "flags")["display"], "taglist")
        self.assertEqual(named(template, "boxes")["display"], "checklist")
        self.assertEqual(named(template, "free")["display"], "taglist")

    def test_lists_take_item_types_values_and_item_constraints(self) -> None:
        template = rendered(
            spec(
                contract(
                    to=field(list[str], default_factory=list, value=None),
                    tags=field(
                        list[str], default_factory=list, value=["new", "priority"]
                    ),
                    holidays=field(
                        list[date],
                        default_factory=list,
                        item_type="Date",
                        value=["2026-12-24"],
                        constraints={"minItems": 0, "maxItems": 10},
                    ),
                    ticketCodes=field(
                        list[str],
                        default_factory=list,
                        constraints={
                            "pattern": {
                                "value": "^[A-Z]{3}$",
                                "message": "Use three upper-case letters.",
                            },
                            "maxItems": 5,
                        },
                    ),
                    numbers=field(list[int], default_factory=list, type="List"),
                    days=field(
                        list[int], default_factory=list, type="List", item_type="Date"
                    ),
                )
            )
        )
        to = named(template, "to")
        self.assertEqual((to["type"], to["itemType"]), ("List", "String"))
        self.assertNotIn("value", to)
        self.assertEqual(named(template, "tags")["value"], ["new", "priority"])
        holidays = named(template, "holidays")
        self.assertEqual(
            (holidays["itemType"], holidays["value"], holidays["constraints"]),
            ("Date", ["2026-12-24"], {"minItems": 0, "maxItems": 10}),
        )
        self.assertEqual(named(template, "ticketCodes")["constraints"]["maxItems"], 5)
        self.assertNotIn("itemType", named(template, "numbers"))
        self.assertEqual(named(template, "days")["itemType"], "Date")

    def test_conditions_give_the_referenced_property_an_id(self) -> None:
        template = rendered(
            spec(
                contract(
                    channel=field(Channel, "email"),
                    phoneNumber=field(
                        str, "", condition={"property": "channel", "equals": "sms"}
                    ),
                    address=field(
                        str,
                        "",
                        condition={
                            "type": "simple",
                            "property": "channel",
                            "oneOf": ["email", "push"],
                        },
                    ),
                    footer=field(
                        str, "", condition={"property": "address", "isActive": True}
                    ),
                    style=field(
                        Literal["plain", "rich"],
                        "plain",
                        choices=[
                            {"name": "Plain", "value": "plain"},
                            {
                                "name": "Rich",
                                "value": "rich",
                                "condition": {"property": "channel", "equals": "email"},
                            },
                        ],
                    ),
                    notification=field(
                        dict[str, str],
                        default_factory=dict,
                        entries=[
                            {"id": "priority", "key": "priority", "value": "low"},
                            {
                                "key": "reason",
                                "condition": {"property": "priority", "equals": "high"},
                            },
                            {
                                "key": "sender",
                                "condition": {"property": "channel", "equals": "sms"},
                            },
                        ],
                    ),
                ),
                outputs=contract(
                    "Out",
                    receipt=field(
                        str, condition={"property": "channel", "equals": "email"}
                    ),
                ),
            )
        )
        self.assertEqual(named(template, "channel")["id"], "channel")
        self.assertEqual(named(template, "address")["id"], "address")
        self.assertNotIn("id", named(template, "phoneNumber"))
        self.assertEqual(
            named(template, "phoneNumber")["condition"],
            {"property": "channel", "equals": "sms"},
        )
        self.assertEqual(
            sourced(template, "${receipt}")["condition"]["equals"], "email"
        )

    def test_script_inputs_bind_a_script_format(self) -> None:
        script = "def items = execution.getVariable('items') ?: []\nitems.size()"
        template = rendered(
            spec(
                contract(
                    score=field(
                        int, 0, type="Text", value=script, script_format="groovy"
                    )
                )
            )
        )
        score = named(template, "score")
        self.assertEqual(score["value"], script)
        self.assertEqual(
            score["binding"],
            {
                "type": "camunda:inputParameter",
                "name": "score",
                "scriptFormat": "groovy",
            },
        )

    def test_maps_take_additional_entries_and_hinted_constraints(self) -> None:
        template = rendered(
            spec(
                contract(
                    headers=field(
                        dict[str, str],
                        default_factory=dict,
                        additional_entries=True,
                        entries=[
                            {"key": "Content-Type", "value": "application/json"},
                            {"key": "Accept", "value": "application/json"},
                        ],
                        constraints={
                            "notEmpty": True,
                            "keyPattern": {
                                "value": "^[A-Za-z-]+$",
                                "message": "Use a header name.",
                            },
                        },
                    ),
                    labels=field(
                        dict[str, str], default_factory=dict, additional_entries=True
                    ),
                    fixed=field(
                        dict[str, str],
                        default_factory=dict,
                        additional_entries=False,
                        entries=[{"key": "fi"}],
                        editable=False,
                    ),
                )
            )
        )
        headers = named(template, "headers")
        self.assertIs(headers["additionalEntries"], True)
        self.assertEqual(len(headers["entries"]), 2)
        self.assertEqual(headers["constraints"]["keyPattern"]["value"], "^[A-Za-z-]+$")
        self.assertIs(named(template, "labels")["additionalEntries"], True)
        fixed = named(template, "fixed")
        self.assertNotIn("additionalEntries", fixed)
        self.assertIs(fixed["editable"], False)

    def test_key_patterns_apply_to_additional_entries_of_fixed_maps(self) -> None:
        Key = Annotated[str, StringConstraints(pattern="^[a-z]+$")]
        template = rendered(
            spec(
                contract(
                    labels=field(
                        dict[Key, str],
                        default_factory=dict,
                        additional_entries=True,
                        entries=[{"key": "fi"}],
                    )
                )
            )
        )
        self.assertEqual(
            named(template, "labels")["constraints"], {"keyPattern": "^[a-z]+$"}
        )

    def test_templates_without_groups_leave_properties_ungrouped(self) -> None:
        template = rendered(
            spec(
                contract(name=field(str)),
                outputs=contract("Out", greeting=field(str)),
                groups=(),
                additional_inputs=AdditionalInputs("More"),
            )
        )
        self.assertNotIn("groups", template)
        self.assertFalse([prop for prop in template["properties"] if "group" in prop])

    def test_invalid_input_hints_are_rejected(self) -> None:
        cases: list[tuple[Any, str]] = [
            (field(str, source="${x}"), "input hints cannot set source"),
            (field(str, choices=CHANNEL_CHOICES), "choices need a Dropdown or List"),
            (field(Channel, choices=[]), "non-empty list of string name/value"),
            (field(Channel, choices=[{"name": "x"}]), "non-empty list of string"),
            (
                field(Channel, choices=CHANNEL_CHOICES[:1] * 2),
                "choice values must be unique",
            ),
            (
                field(Channel, choices=[{"name": "Fax", "value": "fax"}]),
                "choices 'fax' are not contract values email, sms, push",
            ),
            (field(str, type="Dropdown"), "a Dropdown needs Literal choices"),
            (
                field(list[Channel], default_factory=list, display="grid"),
                "display must be one of checklist, taglist",
            ),
            (
                field(list[Channel], default_factory=list, item_type="Date"),
                "a List with choices takes no item_type",
            ),
            (
                field(list[str], default_factory=list, display="taglist"),
                "display needs a List with choices",
            ),
            (field(str, item_type="Date"), "item_type needs a List property"),
            (
                field(list[str], default_factory=list, item_type="Number"),
                "item_type must be one of String, Date",
            ),
            (field(str, additional_entries=True), "additional_entries need a Map"),
            (
                field(
                    dict[Literal["fi", "en"], str],
                    default_factory=dict,
                    additional_entries=True,
                ),
                "additional_entries need free map keys",
            ),
            (
                field(dict[str, str], default_factory=dict, additional_entries="yes"),
                "additional_entries must be a boolean",
            ),
            (
                field(dict[str, str], default_factory=dict, script_format="groovy"),
                "a Map cannot be a script",
            ),
            (
                field(list[str], default_factory=list, value=[1]),
                "does not fit template type List",
            ),
            (field(bool, False, placeholder="x"), "placeholder needs a String or Text"),
            (field(str, placeholder=""), "placeholder must be a non-empty string"),
            (field(str, constraints=["notEmpty"]), "constraints must be an object"),
            (
                field(str, constraints={"minItems": 1}),
                "a String cannot have constraint\\(s\\) minItems",
            ),
            (
                field(str, constraints={"pattern": {"message": "x"}}),
                "constraint pattern must be a string or an object",
            ),
            (
                field(str, constraints={"pattern": {"value": "x", "flags": "i"}}),
                "constraint pattern must be a string or an object",
            ),
            (
                field(str, constraints={"notEmpty": "yes"}),
                "constraint notEmpty must be a boolean",
            ),
            (
                field(str, constraints={"maxLength": True}),
                "constraint maxLength must be a non-negative integer",
            ),
            (
                field(str, constraints={"maxLength": -1}),
                "constraint maxLength must be a non-negative integer",
            ),
            (field(bool, False, optional=True), "only String, Text, Dropdown inputs"),
            (field(str, optional=True), "an optional input needs a contract default"),
            (
                field(str, "", optional=True, constraints={"notEmpty": True}),
                "cannot be optional and notEmpty",
            ),
            (field(str, "", optional="yes"), "optional must be a boolean"),
            (field(str, editable=0), "editable must be a boolean"),
            (field(str, "", condition="channel"), "a condition needs a property"),
            (
                field(str, "", condition={"property": "other"}),
                "a condition needs a property and exactly one of",
            ),
            (
                field(
                    str, "", condition={"property": "other", "equals": 1, "oneOf": []}
                ),
                "exactly one of equals, oneOf, isActive",
            ),
            (
                field(str, "", condition={"property": "other", "equals": 1, "x": 1}),
                "a condition needs a property",
            ),
            (
                field(
                    str,
                    "",
                    condition={"type": "feel", "property": "other", "equals": 1},
                ),
                "a condition needs a property",
            ),
            (
                field(str, "", condition={"property": "target", "equals": "x"}),
                "a condition cannot depend on its own property",
            ),
            (
                field(str, "", condition={"property": "missing", "equals": "x"}),
                "condition property 'missing' is not an input alias or an entry id",
            ),
            (
                field(str, script_format="groovy", value=None),
                "script_format needs a String, Text, or Hidden",
            ),
            (
                field(
                    list[str], default_factory=list, script_format="groovy", value=["x"]
                ),
                "script_format needs a String, Text, or Hidden",
            ),
            (field(str, script_format=1), "script_format must be a non-empty string"),
        ]
        for definition, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(TemplateError, message):
                    render(
                        spec(contract(target=definition)),
                        icon_svg=b"",
                        schema_url=SCHEMA_URL,
                    )

    def test_conditions_cannot_compare_lists_or_maps(self) -> None:
        for annotation in (list[str], dict[str, str]):
            with self.subTest(annotation=annotation):
                with self.assertRaisesRegex(
                    TemplateError, "a condition cannot compare the (List|Map) input"
                ):
                    render(
                        spec(
                            contract(
                                many=field(annotation, default_factory=annotation),
                                note=field(
                                    str,
                                    "",
                                    condition={"property": "many", "equals": "x"},
                                ),
                            )
                        ),
                        icon_svg=b"",
                        schema_url=SCHEMA_URL,
                    )


class AdditionalInputTests(unittest.TestCase):
    def test_additional_inputs_render_a_map_for_user_named_inputs(self) -> None:
        template = rendered(
            spec(
                contract(lookups=field(list[str], default_factory=list)),
                outputs=contract("Out", messageId=field(str)),
                groups=(
                    TemplateGroup("inputs", "Inputs"),
                    TemplateGroup("fields", "Fields"),
                    TemplateGroup("outputs", "Results"),
                ),
                additional_inputs=AdditionalInputs(
                    label="Fields to load",
                    description="Each row names a variable and the field to load.",
                    group="fields",
                    mirror_outputs=True,
                    constraints={
                        "notEmpty": True,
                        "pattern": {
                            "value": "^[A-Za-z_]\\w*(\\.[^.\\s]+)+$",
                            "message": "Use an entity path like <entity>.<field>.",
                        },
                        "keyPattern": "^[a-z_][a-z0-9_]*$",
                    },
                ),
            )
        )
        # Contract inputs come first, then the user-added ones, then outputs.
        kinds = [prop["binding"]["type"] for prop in template["properties"][2:]]
        self.assertEqual(
            kinds,
            [
                "camunda:inputParameter",
                "camunda:additionalInputParameters",
                "camunda:outputParameter",
            ],
        )
        additional = template["properties"][3]
        self.assertEqual(
            {key: additional[key] for key in ("label", "type", "group")},
            {"label": "Fields to load", "type": "Map", "group": "fields"},
        )
        self.assertIs(additional["mirrorOutputs"], True)
        self.assertEqual(additional["constraints"]["keyPattern"], "^[a-z_][a-z0-9_]*$")
        self.assertIn("description", additional)
        self.assertNotIn("entries", additional)

    def test_additional_inputs_default_to_the_input_group(self) -> None:
        template = rendered(spec(additional_inputs=AdditionalInputs("Texts")))
        self.assertEqual(
            template["properties"][2],
            {
                "label": "Texts",
                "type": "Map",
                "group": "inputs",
                "binding": {"type": "camunda:additionalInputParameters"},
            },
        )

    def test_invalid_additional_inputs_are_rejected(self) -> None:
        cases: list[tuple[dict[str, Any], str]] = [
            ({"additional_inputs": "Texts"}, "must be an AdditionalInputs"),
            ({"additional_inputs": AdditionalInputs("")}, "need a label"),
            (
                {"additional_inputs": AdditionalInputs("x", mirror_outputs=1)},  # type: ignore[arg-type]
                "mirror_outputs must be a boolean",
            ),
            (
                {
                    "additional_inputs": AdditionalInputs("x", mirror_outputs=True),
                    "element_type": ElementType.MESSAGE_END_EVENT,
                },
                "a message end event cannot map outputs",
            ),
            (
                {"additional_inputs": AdditionalInputs("x", group="missing")},
                "unknown group id 'missing'",
            ),
            (
                {
                    "additional_inputs": AdditionalInputs(
                        "x", constraints={"minItems": 1}
                    )
                },
                "a Map cannot have constraint\\(s\\) minItems",
            ),
        ]
        for options, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(TemplateError, message):
                    render(spec(**options), icon_svg=b"", schema_url=SCHEMA_URL)


class OutputFeatureTests(unittest.TestCase):
    def test_outputs_take_optional_source_and_script_hints(self) -> None:
        template = rendered(
            spec(
                outputs=contract(
                    "Out",
                    id=field(str, value="guestId", optional=True),
                    score=field(int, source="${ score }"),
                    summary=field(
                        str,
                        value="summary",
                        optional=True,
                        source='"${customerId}: ${score}"',
                        script_format="groovy",
                        editable=False,
                    ),
                    plain=field(str, optional=False),
                    skipped=field(str, value=""),
                )
            )
        )
        guest = sourced(template, "${id}")
        self.assertEqual((guest["value"], guest["optional"]), ("guestId", True))
        self.assertEqual(sourced(template, "${ score }")["value"], "score")
        summary = sourced(template, '"${customerId}: ${score}"')
        self.assertEqual(summary["binding"]["scriptFormat"], "groovy")
        self.assertIs(summary["editable"], False)
        self.assertNotIn("optional", sourced(template, "${plain}"))
        self.assertIs(sourced(template, "${skipped}")["optional"], True)

    def test_invalid_output_hints_are_rejected(self) -> None:
        cases: list[tuple[Any, str]] = [
            (field(str, placeholder="x"), "output hints may only set"),
            (
                field(str, value="", optional=False),
                "an output without a target variable is always optional",
            ),
            (field(str, optional="yes"), "optional must be a boolean"),
            (field(str, source=""), "source must be a non-empty string"),
            (
                field(str, script_format="groovy"),
                "script_format needs the script as the source hint",
            ),
            (
                field(str, "", condition={"property": "x"}),
                "a condition needs a property",
            ),
        ]
        for definition, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(TemplateError, message):
                    render(
                        spec(outputs=contract("Out", target=definition)),
                        icon_svg=b"",
                        schema_url=SCHEMA_URL,
                    )


class TaskSettingTests(unittest.TestCase):
    def test_settings_bind_engine_properties_after_the_topic(self) -> None:
        priority = {
            "pattern": {
                "value": "^(\\d+|\\$\\{.+\\})?$",
                "message": "Must be a number or an expression.",
            }
        }
        template = rendered(
            spec(
                contract(name=field(str)),
                groups=(
                    TemplateGroup("inputs", "Inputs"),
                    TemplateGroup("outputs", "Results"),
                    TemplateGroup("jobs", "Job execution"),
                ),
                settings=(
                    TaskSetting(
                        "taskPriority",
                        placeholder="e.g. 50 or ${priority}",
                        constraints=priority,
                    ),
                    TaskSetting("asyncBefore", value=True, group="jobs"),
                    TaskSetting("asyncAfter", value=False, group="jobs"),
                    TaskSetting(
                        "exclusive",
                        value=True,
                        hidden=True,
                        label="Always exclusive",
                        description="Fixed by the template.",
                    ),
                    TaskSetting("jobPriority", value="10", group="jobs"),
                ),
            )
        )
        settings = template["properties"][2:7]
        self.assertEqual(
            [prop["binding"] for prop in settings],
            [
                {"type": "property", "name": f"camunda:{name}"}
                for name in (
                    "taskPriority",
                    "asyncBefore",
                    "asyncAfter",
                    "exclusive",
                    "jobPriority",
                )
            ],
        )
        self.assertEqual(
            settings[0],
            {
                "label": "Task priority",
                "type": "String",
                "placeholder": "e.g. 50 or ${priority}",
                "constraints": priority,
                "binding": {"type": "property", "name": "camunda:taskPriority"},
            },
        )
        self.assertEqual(
            settings[1],
            {
                "label": "Asynchronous before",
                "type": "Boolean",
                "value": True,
                "group": "jobs",
                "binding": {"type": "property", "name": "camunda:asyncBefore"},
            },
        )
        self.assertIs(settings[2]["value"], False)
        self.assertEqual(
            {key: settings[3][key] for key in ("label", "description", "type")},
            {
                "label": "Always exclusive",
                "description": "Fixed by the template.",
                "type": "Hidden",
            },
        )
        self.assertEqual(settings[4]["value"], "10")
        # The contract inputs follow the settings.
        self.assertEqual(template["properties"][7]["binding"]["name"], "name")

    def test_hidden_text_settings_drop_presentation(self) -> None:
        template = rendered(
            spec(
                settings=(
                    TaskSetting(
                        "jobPriority",
                        value="5",
                        hidden=True,
                        placeholder="unused",
                        constraints={"notEmpty": True},
                    ),
                )
            )
        )
        self.assertEqual(
            template["properties"][2],
            {
                "label": "Job priority",
                "type": "Hidden",
                "value": "5",
                "binding": {"type": "property", "name": "camunda:jobPriority"},
            },
        )

    def test_invalid_settings_are_rejected(self) -> None:
        cases: list[tuple[Any, str]] = [
            ("asyncBefore", "settings must be TaskSetting objects"),
            (TaskSetting("retries"), "named one of asyncBefore, asyncAfter"),
            (TaskSetting("asyncBefore", value="true"), "value must be a bool"),
            (TaskSetting("jobPriority", value=10), "value must be a str"),  # type: ignore[arg-type]
            (TaskSetting("exclusive", hidden=True), "a hidden setting needs a value"),
            (
                TaskSetting("asyncAfter", placeholder="x"),
                "a boolean setting takes no placeholder or constraints",
            ),
            (
                TaskSetting("jobPriority", constraints={"minItems": 1}),
                "cannot have constraint\\(s\\) minItems",
            ),
            (TaskSetting("jobPriority", group="missing"), "unknown group id 'missing'"),
        ]
        for setting, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(TemplateError, message):
                    render(
                        spec(settings=(setting,)), icon_svg=b"", schema_url=SCHEMA_URL
                    )
        with self.assertRaisesRegex(TemplateError, "setting exclusive is given twice"):
            render(
                spec(settings=(TaskSetting("exclusive"), TaskSetting("exclusive"))),
                icon_svg=b"",
                schema_url=SCHEMA_URL,
            )


class ErrorDefinitionTests(unittest.TestCase):
    def test_errors_render_a_property_and_a_scope(self) -> None:
        template = rendered(
            spec(
                contract(amount=field(str)),
                outputs=contract("Out", receipt=field(str)),
                errors=(
                    ErrorDefinition(
                        id="payment-failed",
                        expression='${ error.code == "DECLINED" }',
                        code="PAYMENT_DECLINED",
                        name="Payment failed",
                        message="Payment was declined",
                        description="Expression evaluated on the worker's result.",
                        group="outputs",
                    ),
                    ErrorDefinition(
                        id="timeout",
                        expression="${ externalTask.getErrorMessage() == 'timeout' }",
                        code="TIMEOUT",
                        name="Timeout",
                        label="Time out when",
                        hidden=True,
                    ),
                ),
            )
        )
        # Error definitions follow the outputs.
        declined, timeout = template["properties"][-2:]
        self.assertEqual(
            declined,
            {
                "label": "Throw error when",
                "description": "Expression evaluated on the worker's result.",
                "type": "String",
                "value": '${ error.code == "DECLINED" }',
                "group": "outputs",
                "binding": {
                    "type": "camunda:errorEventDefinition",
                    "errorRef": "payment-failed",
                },
            },
        )
        self.assertEqual(
            (timeout["label"], timeout["type"]), ("Time out when", "Hidden")
        )
        self.assertNotIn("group", timeout)
        self.assertEqual(
            template["scopes"][0],
            {
                "type": "bpmn:Error",
                "id": "payment-failed",
                "properties": [
                    {
                        "label": "Error code",
                        "type": "String",
                        "value": "PAYMENT_DECLINED",
                        "binding": {"type": "property", "name": "errorCode"},
                    },
                    {
                        "label": "Error message",
                        "type": "String",
                        "value": "Payment was declined",
                        "binding": {"type": "property", "name": "camunda:errorMessage"},
                    },
                    {
                        "label": "Error name",
                        "type": "Hidden",
                        "value": "Payment failed",
                        "binding": {"type": "property", "name": "name"},
                    },
                ],
            },
        )
        # A hidden error fixes its code, and has no message property.
        self.assertEqual(
            [
                (prop["binding"]["name"], prop["type"])
                for prop in template["scopes"][1]["properties"]
            ],
            [("errorCode", "Hidden"), ("name", "Hidden")],
        )

    def test_templates_without_errors_have_no_scopes(self) -> None:
        self.assertNotIn("scopes", rendered(spec()))

    def test_invalid_errors_are_rejected(self) -> None:
        valid: dict[str, Any] = {
            "id": "e",
            "expression": "${true}",
            "code": "E",
            "name": "Error",
        }
        cases: list[tuple[Any, str]] = [
            ("e", "errors must be ErrorDefinition objects"),
            (ErrorDefinition(**{**valid, "id": ""}), "id must be a non-empty string"),
            (
                ErrorDefinition(**{**valid, "expression": ""}),
                "expression must be a non-empty string",
            ),
            (ErrorDefinition(**{**valid, "code": ""}), "code must be a non-empty"),
            (ErrorDefinition(**{**valid, "name": ""}), "name must be a non-empty"),
            (ErrorDefinition(**valid, label=""), "label must be a non-empty string"),
            (ErrorDefinition(**valid, message=1), "message must be a string"),  # type: ignore[arg-type]
            (ErrorDefinition(**valid, group="missing"), "unknown group id 'missing'"),
        ]
        for error, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(TemplateError, message):
                    render(spec(errors=(error,)), icon_svg=b"", schema_url=SCHEMA_URL)
        with self.assertRaisesRegex(TemplateError, "error 'e' is defined twice"):
            render(
                spec(errors=(ErrorDefinition(**valid), ErrorDefinition(**valid))),
                icon_svg=b"",
                schema_url=SCHEMA_URL,
            )


class ReviewedEdgeTests(unittest.TestCase):
    def reject(self, message: str, *inputs: Any, **options: Any) -> None:
        fields = {f"f{index}": definition for index, definition in enumerate(inputs)}
        with self.subTest(message=message):
            with self.assertRaisesRegex(TemplateError, message):
                render(
                    spec(contract(**fields), **options),
                    icon_svg=b"",
                    schema_url=SCHEMA_URL,
                )

    def test_unhinted_properties_keep_their_serialized_form(self) -> None:
        """Templates without the new hints must not drift, key order included."""
        template = rendered(
            spec(
                contract(
                    name=field(str, title="Name"),
                    mode=field(Literal["short", "long"], "short", title="Mode"),
                    tags=field(
                        list[Literal["a", "b"]], default_factory=list, title="Tags"
                    ),
                    ids=field(list[str], default_factory=list, title="IDs"),
                    dryRun=field(bool, False, title="Dry run"),
                    picks=field(
                        Literal["a", "b"], title="Picks", type="List", value=["a"]
                    ),
                    labels=field(dict[str, str], default_factory=dict, title="Labels"),
                ),
                outputs=contract("Out", result=field(str, title="Result")),
            )
        )
        choices = '[{"name": "a", "value": "a"}, {"name": "b", "value": "b"}]'
        binding = '"binding": {"type": "camunda:inputParameter", "name": '
        self.assertEqual(
            [json.dumps(prop) for prop in template["properties"][2:]],
            [
                '{"label": "Name", "type": "String", "value": "${name}", '
                '"constraints": {"notEmpty": true}, "group": "inputs", '
                + binding
                + '"name"}}',
                '{"label": "Mode", "type": "Dropdown", "choices": [{"name": '
                '"short", "value": "short"}, {"name": "long", "value": "long"}], '
                '"value": "short", "group": "inputs", ' + binding + '"mode"}}',
                '{"label": "Tags", "type": "List", "display": "taglist", '
                f'"choices": {choices}, "value": [], "group": "inputs", '
                + binding
                + '"tags"}}',
                '{"label": "IDs", "type": "List", "itemType": "String", '
                '"value": [], "group": "inputs", ' + binding + '"ids"}}',
                '{"label": "Dry run", "type": "Boolean", "value": false, '
                '"group": "inputs", ' + binding + '"dryRun"}}',
                # A Literal shown as a List keeps its choices, without a display.
                f'{{"label": "Picks", "type": "List", "choices": {choices}, '
                '"value": ["a"], "group": "inputs", ' + binding + '"picks"}}',
                '{"label": "Labels", "type": "Map", "group": "inputs", '
                + binding
                + '"labels"}, "additionalEntries": true}',
                '{"label": "Result", "type": "String", "value": "result", '
                '"group": "outputs", "binding": {"type": '
                '"camunda:outputParameter", "source": "${result}"}}',
            ],
        )
        self.assertTrue(dumps(template).endswith("}\n"))

    def test_conditions_are_kept_on_entries_choices_and_lists(self) -> None:
        template = rendered(
            spec(
                contract(
                    channel=field(Channel, "email"),
                    recipients=field(list[str], default_factory=list),
                    style=field(
                        Literal["plain", "rich"],
                        "plain",
                        choices=[
                            {"name": "Plain", "value": "plain"},
                            {
                                "name": "Rich",
                                "value": "rich",
                                "condition": {"property": "channel", "equals": "email"},
                            },
                        ],
                    ),
                    note=field(
                        str, "", condition={"property": "recipients", "isActive": True}
                    ),
                    notification=field(
                        dict[str, str],
                        default_factory=dict,
                        entries=[
                            {"id": "priority", "key": "priority", "value": "low"},
                            {
                                "key": "reason",
                                "condition": {"property": "priority", "equals": "high"},
                            },
                        ],
                    ),
                ),
                outputs=contract(
                    "Out",
                    channel=field(
                        str,
                        value="usedChannel",
                        condition={"property": "channel", "equals": "sms"},
                    ),
                ),
            )
        )
        self.assertEqual(
            named(template, "style")["choices"][1]["condition"],
            {"property": "channel", "equals": "email"},
        )
        # isActive compares nothing, so it may refer to a List.
        self.assertEqual(named(template, "recipients")["id"], "recipients")
        self.assertEqual(
            named(template, "notification")["entries"][1]["condition"],
            {"property": "priority", "equals": "high"},
        )
        # An output may depend on the input that shares its alias.
        self.assertEqual(
            sourced(template, "${channel}")["condition"]["property"], "channel"
        )

    def test_invalid_conditions_are_rejected_everywhere(self) -> None:
        def entry(condition: Any, **extra: Any) -> Any:
            return field(
                dict[str, str],
                default_factory=dict,
                entries=[{"key": "k", "condition": condition, **extra}],
            )

        self.reject("entry 'k': a condition needs a property", entry("x"))
        self.reject("entry 'k': a condition needs a property", entry({"equals": 1}))
        self.reject(
            "entry 'k': a condition needs a property", entry({"property": "other"})
        )
        self.reject(
            "entry 'k': a condition cannot depend on its own property",
            entry({"property": "k", "equals": "x"}, id="k"),
        )
        for condition, message in (
            ({"equals": {"a": 1}}, "equals must be a string, number, or boolean"),
            ({"equals": None}, "equals must be a string, number, or boolean"),
            ({"oneOf": "x"}, "oneOf must be a list of strings or numbers"),
            ({"oneOf": [True, 1.5]}, "oneOf must be a list of strings or numbers"),
            ({"isActive": "yes"}, "isActive must be a boolean"),
        ):
            self.reject(
                message, field(str, "", condition={"property": "other", **condition})
            )
        self.reject(
            "an input with a condition needs a contract default",
            field(str, condition={"property": "other", "equals": "x"}),
        )
        self.reject(
            "condition property 'f1' is both an input alias and an entry id",
            field(
                dict[str, str],
                default_factory=dict,
                entries=[
                    {"key": "a", "id": "f1"},
                    {"key": "b", "condition": {"property": "f1", "equals": "x"}},
                ],
            ),
            field(str, ""),
        )
        self.reject(
            "entry ids must be unique in the template",
            field(
                dict[str, str],
                default_factory=dict,
                entries=[{"key": "a", "id": "same"}, {"key": "b", "id": "same"}],
            ),
        )

    def test_hints_that_would_break_the_contract_are_rejected(self) -> None:
        self.reject(
            "additional_entries need free map values",
            field(
                dict[str, Literal["x", "y"]],
                default_factory=dict,
                additional_entries=True,
                entries=[{"key": "k"}],
            ),
        )
        self.reject(
            "value 'sms' is not one of the hinted choices",
            field(Channel, "sms", choices=CHANNEL_CHOICES[:1]),
        )
        self.reject(
            "value 'push' is not one of the hinted choices",
            field(
                list[Channel],
                default_factory=list,
                choices=CHANNEL_CHOICES[:1],
                value=["email", "push"],
            ),
        )
        for definition in (
            field(bool, False, script_format="groovy", value=True),
            field(Channel, "email", script_format="groovy", value="email"),
            field(str, "", script_format="groovy"),
        ):
            self.reject("script_format needs a String, Text, or Hidden", definition)
        # An expression is not one of the choices, but may still select one.
        template = rendered(
            spec(
                contract(
                    channel=field(Channel, choices=CHANNEL_CHOICES[:1]),
                    via=field(
                        list[Channel],
                        default_factory=list,
                        choices=CHANNEL_CHOICES[:1],
                        value=["${channel}"],
                    ),
                )
            )
        )
        self.assertEqual(named(template, "channel")["value"], "${channel}")

    def test_spec_values_are_type_checked(self) -> None:
        error = {"id": "e", "expression": "${true}", "code": "E", "name": "Error"}
        cases: list[tuple[dict[str, Any], str]] = [
            ({"settings": TaskSetting("exclusive")}, "settings must be a tuple"),
            ({"errors": None}, "errors must be a tuple"),
            ({"groups": None}, "groups must be a tuple"),
            (
                {"settings": (TaskSetting("jobPriority", constraints=["a"]),)},  # type: ignore[arg-type]
                "constraints must be an object",
            ),
            (
                {"settings": (TaskSetting("jobPriority", label=1),)},  # type: ignore[arg-type]
                "label must be a string",
            ),
            (
                {"settings": (TaskSetting("jobPriority", placeholder=1),)},  # type: ignore[arg-type]
                "placeholder must be a string",
            ),
            (
                {"additional_inputs": AdditionalInputs("x", constraints=["a"])},  # type: ignore[arg-type]
                "constraints must be an object",
            ),
            (
                {"additional_inputs": AdditionalInputs("x", description=1)},  # type: ignore[arg-type]
                "description must be a string",
            ),
            (
                {"errors": (ErrorDefinition(**error, description=1),)},  # type: ignore[arg-type]
                "description must be a string",
            ),
        ]
        for options, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(TemplateError, message):
                    render(spec(**options), icon_svg=b"", schema_url=SCHEMA_URL)
