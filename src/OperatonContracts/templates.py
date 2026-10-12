"""Render and validate Operaton element templates from task contracts.

Element templates are rendered from ``TaskTemplate`` specs and the
``TaskContract`` models they reference. Schema validation needs the
``templates`` extra (``jsonschema``).
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from typing import NamedTuple
from urllib.request import urlopen

from OperatonContracts.contracts import TEMPLATE_KEY
from OperatonContracts.contracts import TaskContract

TEMPLATE_DIR = Path(".operaton") / "element-templates"
DEFAULT_SCHEMA_URL = (
    "https://gitlab.com/vasara-bpm/vscode-operaton-bpmn-js-modeler/"
    "-/jobs/artifacts/v0.8.3/raw/"
    "operaton-element-templates-schema-v0.8.3.json?job=release"
)
ALIAS_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Input property types the Camunda 7 element-template schema allows, and the
# JSON type each one's ``value`` must have.
VALUE_TYPES: dict[str, type] = {
    "String": str,
    "Text": str,
    "Hidden": str,
    "Dropdown": str,
    "Boolean": bool,
    "List": list,
}
# ``Map`` takes no ``value``; its fixed keys are ``entries``.
PROPERTY_TYPES = (*VALUE_TYPES, "Map")
# Keys of a Map entry object and the types an entry may have.
ENTRY_KEYS = frozenset(
    {
        "key",
        "id",
        "label",
        "type",
        "value",
        "description",
        "placeholder",
        "choices",
        "constraints",
        "editable",
        "optional",
        "condition",
    }
)
ENTRY_TYPES = ("String", "Text", "Dropdown", "Boolean", "Hidden")
# Entry keys the schema allows only for some entry types.
ENTRY_KEY_TYPES = {
    "placeholder": ("String", "Text"),
    "constraints": ("String", "Text", "Dropdown"),
    "optional": ("String", "Text", "Dropdown"),
    "choices": ("Dropdown",),
}
ENTRY_TEXT_KEYS = ("id", "label", "description", "placeholder")
CONSTRAINT_KEYS = frozenset({"notEmpty", "minLength", "maxLength", "pattern"})
# Constraints only some property types take, besides ``CONSTRAINT_KEYS``.
TYPE_CONSTRAINT_KEYS = {
    "List": frozenset({"minItems", "maxItems"}),
    "Map": frozenset({"keyPattern"}),
}
# Property types that may be optional, per the element-template schema.
OPTIONAL_TYPES = ("String", "Text", "Dropdown")
LIST_DISPLAYS = ("checklist", "taglist")
LIST_ITEM_TYPES = ("String", "Date")
# Template hints that apply to output properties, and those that do not
# apply to input properties.
OUTPUT_HINT_KEYS = frozenset(
    {"condition", "editable", "group", "optional", "script_format", "source", "value"}
)
OUTPUT_ONLY_HINT_KEYS = frozenset({"source"})
# Target process variable names an output value hint may set.
OUTPUT_NAME = re.compile(r"[^\s${}]+")


class TemplateError(ValueError):
    """A contract model cannot be rendered as an element template."""


@dataclass(frozen=True)
class TemplateGroup:
    """One property group in the modeler's properties panel."""

    id: str
    label: str


DEFAULT_GROUPS = (
    TemplateGroup("inputs", "Inputs"),
    TemplateGroup("outputs", "Results"),
)


@dataclass(frozen=True)
class AdditionalInputs:
    """A Map property for input parameters that modeler users add themselves.

    It binds to ``camunda:additionalInputParameters``: every key a user adds
    becomes an input parameter of that name, next to the contract's inputs.
    The contract does not describe these inputs, so the task reads them as
    plain variables. ``mirror_outputs`` also keeps an output mapping
    ``<name> = ${<name>}`` for each of them. ``constraints`` apply to every
    value (``notEmpty``, ``minLength``, ``maxLength``, ``pattern``) or to the
    keys (``keyPattern``). ``group`` defaults to the spec's ``input_group``.
    """

    label: str
    description: str | None = None
    group: str | None = None
    mirror_outputs: bool = False
    constraints: Mapping[str, Any] | None = None


# Settings of an external task element: the template label and whether the
# value is a boolean (else text, e.g. a number or an expression).
SETTINGS: dict[str, tuple[str, bool]] = {
    "asyncBefore": ("Asynchronous before", True),
    "asyncAfter": ("Asynchronous after", True),
    "exclusive": ("Exclusive", True),
    "jobPriority": ("Job priority", False),
    "taskPriority": ("Task priority", False),
}


@dataclass(frozen=True)
class TaskSetting:
    """An engine setting of the task that modeler users may adjust.

    ``name`` is one of ``asyncBefore``, ``asyncAfter``, ``exclusive``
    (booleans), ``jobPriority``, or ``taskPriority`` (text: a number or an
    expression). ``value`` pre-fills it; ``hidden`` fixes that value without
    showing the setting. ``label`` defaults to the setting's name in the
    modeler. ``placeholder`` and ``constraints`` apply to the text settings.
    """

    name: str
    value: bool | str | None = None
    label: str | None = None
    description: str | None = None
    group: str | None = None
    hidden: bool = False
    placeholder: str | None = None
    constraints: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ErrorDefinition:
    """A BPMN error the engine throws when ``expression`` holds.

    The expression is evaluated when the worker completes or fails the task,
    and may refer to ``externalTask``. ``id`` names the error within the
    template; ``code`` is the error code that boundary events catch, ``name``
    the error's name, and ``message`` its optional message. Modeler users may
    edit the expression, code, and message unless ``hidden`` fixes them.
    ``label`` and ``description`` describe the expression field.
    """

    id: str
    expression: str
    code: str
    name: str
    message: str | None = None
    label: str = "Throw error when"
    description: str | None = None
    group: str | None = None
    hidden: bool = False


class BpmnElement(NamedTuple):
    """A BPMN type and, for events, the event definition it needs."""

    type: str
    event_definition: str | None = None


class ElementType(Enum):
    """BPMN elements that C7/Operaton can implement as an external task.

    For message events, the forked modeler adds the event definition named in
    ``elementType`` and binds ``camunda:type`` and ``camunda:topic`` to it.
    """

    SERVICE_TASK = BpmnElement("bpmn:ServiceTask")
    SEND_TASK = BpmnElement("bpmn:SendTask")
    BUSINESS_RULE_TASK = BpmnElement("bpmn:BusinessRuleTask")
    MESSAGE_INTERMEDIATE_THROW_EVENT = BpmnElement(
        "bpmn:IntermediateThrowEvent", "bpmn:MessageEventDefinition"
    )
    MESSAGE_END_EVENT = BpmnElement("bpmn:EndEvent", "bpmn:MessageEventDefinition")

    def template_fields(self) -> dict[str, Any]:
        """Return ``appliesTo`` and, for message events, ``elementType``."""
        element: BpmnElement = self.value
        fields: dict[str, Any] = {"appliesTo": [element.type]}
        if element.event_definition is not None:
            fields["elementType"] = {
                "value": element.type,
                "eventDefinition": element.event_definition,
            }
        return fields


@dataclass(frozen=True)
class TaskTemplate:
    """Template-level metadata for one external task topic.

    ``input_group`` and ``output_group`` are group ids from ``groups``; use
    the same id for both to show every property in one group. ``icon`` is an
    SVG path, relative to the project root, that replaces the configured
    ``icon`` for this template. ``keep_versions`` lists earlier published
    versions that ``generate`` copies unchanged from the existing template
    file, so the modeler can still resolve and upgrade diagrams using them.
    ``element_type`` is the BPMN element the template applies to.
    ``additional_inputs`` adds a Map for inputs that modeler users name
    themselves. Without ``groups`` the properties are not grouped.
    ``settings`` exposes engine settings such as ``asyncBefore``, and
    ``errors`` defines BPMN errors thrown from the worker's result.
    """

    topic: str
    template_id: str
    name: str
    description: str
    filename: str
    inputs: type[TaskContract]
    outputs: type[TaskContract]
    groups: tuple[TemplateGroup, ...] = DEFAULT_GROUPS
    input_group: str = "inputs"
    output_group: str = "outputs"
    version: int = 1
    icon: str | None = None
    keep_versions: tuple[int, ...] = ()
    element_type: ElementType = ElementType.SERVICE_TASK
    additional_inputs: AdditionalInputs | None = None
    settings: tuple[TaskSetting, ...] = ()
    errors: tuple[ErrorDefinition, ...] = ()


def contract_properties(
    model: type[TaskContract],
) -> list[tuple[str, dict[str, Any], bool]]:
    for name, info in model.model_fields.items():
        if info.alias is None:
            raise TemplateError(f"{model.__name__}.{name} needs an alias")
        if not ALIAS_PATTERN.fullmatch(info.alias):
            raise TemplateError(
                f"{model.__name__}.{name}: alias {info.alias!r} must be a plain "
                "identifier usable as a Robot variable name"
            )
        if info.title is None:
            raise TemplateError(f"{model.__name__}.{name} needs a title")
    schema = model.model_json_schema(by_alias=True)
    required = set(schema.get("required", ()))
    defs: dict[str, Any] = schema.get("$defs", {})
    return [
        (alias, _inline_map_refs(prop, defs), alias in required)
        for alias, prop in schema.get("properties", {}).items()
    ]


def _inline_map_refs(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Inline ``$ref`` key and value schemas of a map, e.g. ``dict[MyEnum, str]``."""
    inlined = dict(schema)
    for key in ("propertyNames", "additionalProperties"):
        ref = inlined.get(key)
        if isinstance(ref, dict) and "$ref" in ref:
            name = ref["$ref"].rpartition("/")[2]
            if name in defs:
                inlined[key] = defs[name]
    return inlined


def _choices(values: Iterable[Any]) -> list[dict[str, Any]]:
    return [{"name": str(value), "value": value} for value in values]


def _map_schemas(
    schema: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return the key and value schemas of a string-valued map, else None."""
    if schema.get("type") != "object" or "properties" in schema:
        return None
    patterns: dict[str, Any] = schema.get("patternProperties", {})
    values = schema.get("additionalProperties")
    if len(patterns) == 1 and values is None:
        ((pattern, values),) = patterns.items()
        keys: dict[str, Any] = {"pattern": pattern}
    elif patterns:
        return None
    else:
        keys = schema.get("propertyNames", {})
    if not isinstance(values, dict) or values.get("type") != "string":
        return None
    return keys, values


def _entry(alias: str, entry: Any) -> dict[str, Any]:
    """Check one Map entry against the element-template schema's rules."""
    if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
        raise TemplateError(f"{alias}: every entry needs a string key")
    key = entry["key"]
    if not key:
        raise TemplateError(f"{alias}: entry keys must not be empty")
    unknown = sorted(set(entry) - ENTRY_KEYS)
    if unknown:
        raise TemplateError(f"{alias}: unknown entry key(s): {', '.join(unknown)}")
    entry_type = entry.get("type", "String")
    if entry_type not in ENTRY_TYPES:
        raise TemplateError(
            f"{alias}: entry type {entry_type!r} is not one of {', '.join(ENTRY_TYPES)}"
        )
    for name, types in ENTRY_KEY_TYPES.items():
        if name in entry and entry_type not in types:
            raise TemplateError(
                f"{alias}: entry {key!r} of type {entry_type} cannot have {name}"
            )
    if entry_type == "Dropdown" and "choices" not in entry:
        raise TemplateError(f"{alias}: Dropdown entry {key!r} needs choices")
    value_type = bool if entry_type == "Boolean" else str
    if "value" in entry and not isinstance(entry["value"], value_type):
        raise TemplateError(
            f"{alias}: value of entry {key!r} must be a {value_type.__name__}"
        )
    for name in ENTRY_TEXT_KEYS:
        if name in entry and not isinstance(entry[name], str):
            raise TemplateError(f"{alias}: {name} of entry {key!r} must be a string")
    for name in ("editable", "optional"):
        if name in entry and not isinstance(entry[name], bool):
            raise TemplateError(f"{alias}: {name} of entry {key!r} must be a boolean")
    choices = entry.get("choices", [{"name": "", "value": ""}])
    if (
        not isinstance(choices, list)
        or not choices
        or not all(
            isinstance(choice, dict)
            and set(choice) == {"name", "value"}
            and all(isinstance(part, str) for part in choice.values())
            for choice in choices
        )
    ):
        raise TemplateError(
            f"{alias}: choices of entry {key!r} must be a non-empty list of "
            "string name/value objects"
        )
    constraints = entry.get("constraints", {})
    if not isinstance(constraints, dict) or set(constraints) - CONSTRAINT_KEYS:
        raise TemplateError(
            f"{alias}: constraints of entry {key!r} may only set "
            f"{', '.join(sorted(CONSTRAINT_KEYS))}"
        )
    if entry.get("optional") and constraints.get("notEmpty"):
        raise TemplateError(
            f"{alias}: entry {key!r} cannot be both optional and notEmpty"
        )
    if "condition" in entry:
        _condition(f"{alias}: entry {key!r}", entry["condition"], entry.get("id"))
    return dict(entry)


def _entries(alias: str, entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list) or not entries:
        raise TemplateError(f"{alias}: entries must be a non-empty list")
    checked = [_entry(alias, entry) for entry in entries]
    keys = [entry["key"] for entry in checked]
    if len(set(keys)) != len(keys):
        raise TemplateError(f"{alias}: entry keys must be unique")
    return checked


def _allowed_keys(alias: str, keys: dict[str, Any]) -> list[str] | None:
    """Return the fixed keys a map's key schema allows, or None for any key."""
    fixed = [keys["const"]] if "const" in keys else keys.get("enum")
    if fixed is not None and all(isinstance(key, str) for key in fixed):
        return list(fixed)
    unsupported = sorted(set(keys) - {"type", "pattern", "title", "description"})
    if fixed is not None or unsupported or keys.get("type", "string") != "string":
        raise TemplateError(
            f"{alias}: unsupported map key schema {keys!r}; use str, "
            "Literal, an Enum of strings, or a key pattern"
        )
    return None


def _check_dropdown_entry(
    alias: str, entry: dict[str, Any], value_choices: Sequence[Any]
) -> None:
    """Keep a Dropdown entry's choices and default within the contract values."""
    choice_values = [choice["value"] for choice in entry["choices"]]
    outside = [value for value in choice_values if value not in value_choices]
    if value_choices and outside:
        raise TemplateError(
            f"{alias}: choices {', '.join(map(repr, outside))} of entry "
            f"{entry['key']!r} are not contract values "
            f"{', '.join(map(str, value_choices))}"
        )
    if "value" in entry and entry["value"] not in choice_values:
        raise TemplateError(
            f"{alias}: value {entry['value']!r} of entry {entry['key']!r} is not "
            "one of its choices"
        )


def _map_property(
    alias: str,
    schema: dict[str, Any],
    hints: dict[str, Any],
) -> dict[str, Any]:
    """Return the constraints and entries of a Map input property."""
    schemas = _map_schemas(schema)
    if schemas is None:
        raise TemplateError(f"{alias}: a Map needs a dict[str, str] field")
    keys, values = schemas
    if "value" in hints or schema.get("default", {}) != {}:
        raise TemplateError(
            f"{alias}: a Map takes no value; set entry values in the entries hint"
        )
    allowed = _allowed_keys(alias, keys)
    value_choices = values.get("enum", [values["const"]] if "const" in values else [])
    if "entries" in hints:
        entries = _entries(alias, hints["entries"])
    elif allowed is not None:
        entries = [{"key": str(key)} for key in allowed]
    else:
        entries = []

    for entry in entries:
        if allowed is not None and entry["key"] not in allowed:
            raise TemplateError(
                f"{alias}: entry key {entry['key']!r} is not one of the "
                f"contract keys {', '.join(map(str, allowed))}"
            )
        if "pattern" in keys and not re.search(keys["pattern"], entry["key"]):
            raise TemplateError(
                f"{alias}: entry key {entry['key']!r} does not match "
                f"{keys['pattern']!r}"
            )
        if value_choices:
            if entry.get("type", "Dropdown") != "Dropdown":
                raise TemplateError(
                    f"{alias}: entry {entry['key']!r} must be a Dropdown "
                    "because the contract values are Literal choices"
                )
            entry["type"] = "Dropdown"
            entry.setdefault("choices", _choices(map(str, value_choices)))
        if entry.get("type") == "Dropdown":
            _check_dropdown_entry(alias, entry, value_choices)

    # Map constraints apply to every value; keyPattern to user-added keys.
    constraints: dict[str, Any] = {}
    if values.get("minLength", 0) >= 1:
        constraints["notEmpty"] = True
    if values.get("minLength", 0) > 1:
        constraints["minLength"] = values["minLength"]
    if "maxLength" in values:
        constraints["maxLength"] = values["maxLength"]
    if "pattern" in values:
        constraints["pattern"] = values["pattern"]
    prop: dict[str, Any] = {}
    additional = _flag(alias, hints, "additional_entries")
    if entries and additional:
        if allowed is not None:
            raise TemplateError(
                f"{alias}: additional_entries need free map keys, but the "
                f"contract keys are {', '.join(map(str, allowed))}"
            )
        if value_choices:
            raise TemplateError(
                f"{alias}: additional_entries need free map values, but the "
                f"contract values are {', '.join(map(str, value_choices))}"
            )
        prop["additionalEntries"] = True
        if "pattern" in keys:
            constraints["keyPattern"] = keys["pattern"]
        prop["entries"] = entries
    elif entries:
        prop["entries"] = entries
    else:
        if value_choices:
            raise TemplateError(
                f"{alias}: Literal map values need fixed keys; add an entries hint"
            )
        prop["additionalEntries"] = True
        if "pattern" in keys:
            constraints["keyPattern"] = keys["pattern"]
    if constraints:
        prop = {"constraints": constraints, **prop}
    return prop


def _pattern(alias: str, name: str, pattern: Any) -> None:
    """Check a ``pattern`` or ``keyPattern``: a string or a value/message object."""
    if isinstance(pattern, str):
        return
    if (
        not isinstance(pattern, dict)
        or not isinstance(pattern.get("value"), str)
        or not isinstance(pattern.get("message", ""), str)
        or set(pattern) - {"value", "message"}
    ):
        raise TemplateError(
            f"{alias}: constraint {name} must be a string or an object with "
            "a string value and an optional string message"
        )


def _constraints(
    alias: str, property_type: str, derived: dict[str, Any], hint: Any
) -> dict[str, Any]:
    """Merge hinted constraints over the ones derived from the contract."""
    if not isinstance(hint, Mapping):
        raise TemplateError(f"{alias}: constraints must be an object")
    allowed = CONSTRAINT_KEYS | TYPE_CONSTRAINT_KEYS.get(property_type, frozenset())
    unknown = sorted(set(hint) - allowed)
    if unknown:
        raise TemplateError(
            f"{alias}: a {property_type} cannot have constraint(s) "
            f"{', '.join(unknown)}; allowed: {', '.join(sorted(allowed))}"
        )
    for name, value in hint.items():
        if name in ("pattern", "keyPattern"):
            _pattern(alias, name, value)
        elif name == "notEmpty":
            if not isinstance(value, bool):
                raise TemplateError(f"{alias}: constraint notEmpty must be a boolean")
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TemplateError(
                f"{alias}: constraint {name} must be a non-negative integer"
            )
    merged = {**derived, **hint}
    if merged.get("notEmpty") is False:
        del merged["notEmpty"]
    return merged


def _hinted_choices(
    alias: str, choices: Any, values: Sequence[Any] | None
) -> list[dict[str, Any]]:
    """Check a ``choices`` hint: name/value objects within the contract values."""
    if (
        not isinstance(choices, list)
        or not choices
        or not all(
            isinstance(choice, dict)
            and set(choice) - {"condition"} == {"name", "value"}
            and isinstance(choice["name"], str)
            and isinstance(choice["value"], str)
            for choice in choices
        )
    ):
        raise TemplateError(
            f"{alias}: choices must be a non-empty list of string name/value objects"
        )
    chosen = [choice["value"] for choice in choices]
    if len(set(chosen)) != len(chosen):
        raise TemplateError(f"{alias}: choice values must be unique")
    outside = [value for value in chosen if values is not None and value not in values]
    if outside:
        raise TemplateError(
            f"{alias}: choices {', '.join(map(repr, outside))} are not contract "
            f"values {', '.join(map(str, values or ()))}"
        )
    for choice in choices:
        if "condition" in choice:
            _condition(alias, choice["condition"])
    return [dict(choice) for choice in choices]


def _condition(alias: str, condition: Any, own: str | None = None) -> dict[str, Any]:
    """Check a ``condition``: a property id and one of equals, oneOf, isActive.

    ``own`` is the id of the property the condition belongs to, if it has one.
    """
    checks = ("equals", "oneOf", "isActive")
    if (
        not isinstance(condition, dict)
        or not isinstance(condition.get("property"), str)
        or set(condition) - {"type", "property", *checks}
        or sum(check in condition for check in checks) != 1
        or condition.get("type", "simple") != "simple"
    ):
        raise TemplateError(
            f"{alias}: a condition needs a property and exactly one of "
            f"{', '.join(checks)}"
        )
    if "equals" in condition and not isinstance(condition["equals"], (str, int, float)):
        raise TemplateError(
            f"{alias}: condition equals must be a string, number, or boolean"
        )
    if "oneOf" in condition and not (
        isinstance(condition["oneOf"], list)
        and all(
            isinstance(value, (str, int, float)) and not isinstance(value, bool)
            for value in condition["oneOf"]
        )
    ):
        raise TemplateError(
            f"{alias}: condition oneOf must be a list of strings or numbers"
        )
    if "isActive" in condition and not isinstance(condition["isActive"], bool):
        raise TemplateError(f"{alias}: condition isActive must be a boolean")
    if condition["property"] == own:
        raise TemplateError(f"{alias}: a condition cannot depend on its own property")
    return dict(condition)


def _flag(alias: str, hints: dict[str, Any], name: str) -> bool | None:
    """Return a boolean hint, or None when it is not set."""
    if name not in hints:
        return None
    if not isinstance(hints[name], bool):
        raise TemplateError(f"{alias}: {name} must be a boolean")
    return bool(hints[name])


def _text(alias: str, hints: dict[str, Any], name: str) -> str | None:
    """Return a non-empty string hint, or None when it is not set."""
    if name not in hints:
        return None
    if not isinstance(hints[name], str) or not hints[name]:
        raise TemplateError(f"{alias}: {name} must be a non-empty string")
    return str(hints[name])


def _input_property(
    alias: str,
    schema: dict[str, Any],
    required: bool,
    group: str | None,
    group_ids: Sequence[str],
) -> dict[str, Any]:
    hints: dict[str, Any] = schema.get(TEMPLATE_KEY, {})
    unsupported = sorted(set(hints) & OUTPUT_ONLY_HINT_KEYS)
    if unsupported:
        raise TemplateError(f"{alias}: input hints cannot set {', '.join(unsupported)}")
    prop: dict[str, Any] = {"label": schema["title"]}
    if "description" in schema:
        prop["description"] = schema["description"]

    json_type = schema.get("type")
    items: dict[str, Any] = schema.get("items", {})
    string_list = json_type == "array" and items.get("type") == "string"
    if json_type == "boolean":
        prop["type"] = "Boolean"
    elif json_type == "string":
        prop["type"] = "Dropdown" if "enum" in schema else "String"
    elif string_list:
        prop["type"] = "List"
    elif _map_schemas(schema) is not None:
        prop["type"] = "Map"
    elif "type" not in hints:
        raise TemplateError(
            f"{alias}: unsupported JSON Schema {_describe(schema)}; Enum, "
            "Optional, and nested models produce $ref/anyOf schemas. Use "
            "Literal, a plain type, dict[str, str], or add a type hint"
        )
    if "type" in hints:
        prop["type"] = hints["type"]
    property_type = prop["type"]
    if property_type not in PROPERTY_TYPES:
        raise TemplateError(
            f"{alias}: template type {property_type!r} is not one of "
            f"{', '.join(PROPERTY_TYPES)}"
        )

    # Choices come from Literal values; a hint labels or narrows them.
    values: list[Any] | None = None
    if property_type in ("Dropdown", "List"):
        values = schema.get("enum") if json_type == "string" else None
        if string_list:
            values = items.get("enum")
    choices: list[dict[str, Any]] | None = None
    if "choices" in hints:
        if property_type not in ("Dropdown", "List"):
            raise TemplateError(f"{alias}: choices need a Dropdown or List property")
        choices = _hinted_choices(alias, hints["choices"], values)
    elif values is not None:
        choices = _choices(values)
    if property_type == "Dropdown" and choices is None:
        raise TemplateError(
            f"{alias}: a Dropdown needs Literal choices or a choices hint"
        )
    if choices is not None and property_type == "List":
        display = hints.get("display", "taglist" if string_list else None)
        if display is not None:
            if display not in LIST_DISPLAYS:
                raise TemplateError(
                    f"{alias}: display must be one of {', '.join(LIST_DISPLAYS)}, "
                    "or None for the modeler default"
                )
            prop["display"] = display
        if "item_type" in hints:
            raise TemplateError(f"{alias}: a List with choices takes no item_type")
    else:
        if "display" in hints:
            raise TemplateError(f"{alias}: display needs a List with choices")
        if "item_type" in hints and property_type != "List":
            raise TemplateError(f"{alias}: item_type needs a List property")
        item_type = hints.get("item_type", "String")
        if item_type not in LIST_ITEM_TYPES:
            raise TemplateError(
                f"{alias}: item_type must be one of {', '.join(LIST_ITEM_TYPES)}"
            )
        if string_list and property_type == "List" or "item_type" in hints:
            prop["itemType"] = item_type
    if choices is not None:
        prop["choices"] = choices
    if "entries" in hints and property_type != "Map":
        raise TemplateError(f"{alias}: entries need a Map property")
    if "additional_entries" in hints and property_type != "Map":
        raise TemplateError(f"{alias}: additional_entries need a Map property")

    derived: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    if property_type == "Map":
        extras = _map_property(alias, schema, hints)
        derived = extras.pop("constraints", {})
        if "script_format" in hints:
            raise TemplateError(f"{alias}: a Map cannot be a script")
    else:
        if "value" in hints:
            value = hints["value"]
        elif "default" in schema:
            value = schema["default"]
        elif property_type == "List":
            value = []
        elif hints.get("optional"):
            value = None
        else:
            value = f"${{{alias}}}"
        if hints.get("optional") and value == "":
            # An optional input is left out when empty; pre-fill nothing.
            value = None
        if value is not None:
            if not isinstance(value, VALUE_TYPES[property_type]) or (
                isinstance(value, list)
                and not all(isinstance(item, str) for item in value)
            ):
                raise TemplateError(
                    f"{alias}: value {value!r} does not fit template type "
                    f"{property_type}; add a value hint"
                )
            prop["value"] = value
            chosen = [choice["value"] for choice in hints.get("choices", ())]
            outside = [
                item
                for item in (value if isinstance(value, list) else [value])
                if "choices" in hints
                and isinstance(item, str)
                and item not in chosen
                and not item.startswith("${")
            ]
            if outside:
                raise TemplateError(
                    f"{alias}: value {', '.join(map(repr, outside))} is not one "
                    "of the hinted choices"
                )
        if (
            schema.get("minLength", 0) >= 1
            or schema.get("minItems", 0) >= 1
            or (required and property_type == "String")
        ):
            derived = {"notEmpty": True}

    placeholder = _text(alias, hints, "placeholder")
    if placeholder is not None:
        if property_type not in ("String", "Text"):
            raise TemplateError(f"{alias}: placeholder needs a String or Text property")
        prop["placeholder"] = placeholder
    constraints = (
        _constraints(alias, property_type, derived, hints["constraints"])
        if "constraints" in hints
        else derived
    )
    optional = _flag(alias, hints, "optional")
    if optional:
        if property_type not in OPTIONAL_TYPES:
            raise TemplateError(
                f"{alias}: only {', '.join(OPTIONAL_TYPES)} inputs can be optional"
            )
        if required:
            raise TemplateError(
                f"{alias}: an optional input needs a contract default, because "
                "the modeler leaves it out when it is empty"
            )
        if constraints.get("notEmpty"):
            raise TemplateError(f"{alias}: an input cannot be optional and notEmpty")
    if optional:
        prop["optional"] = True
    editable = _flag(alias, hints, "editable")
    if editable is not None:
        prop["editable"] = editable
    if constraints:
        prop["constraints"] = constraints
    if "condition" in hints:
        if required:
            raise TemplateError(
                f"{alias}: an input with a condition needs a contract default, "
                "because the modeler leaves it out while it is hidden"
            )
        prop["condition"] = _condition(alias, hints["condition"], alias)
    group = _group(alias, hints, group, group_ids)
    if group is not None:
        prop["group"] = group
    prop["binding"] = {"type": "camunda:inputParameter", "name": alias}
    script_format = _text(alias, hints, "script_format")
    if script_format is not None:
        if property_type not in ("String", "Text", "Hidden") or not isinstance(
            hints.get("value"), str
        ):
            raise TemplateError(
                f"{alias}: script_format needs a String, Text, or Hidden "
                "property with the script as its value hint"
            )
        prop["binding"]["scriptFormat"] = script_format
    prop.update(extras)
    return prop


def _describe(schema: dict[str, Any]) -> str:
    keys = [key for key in ("type", "$ref", "anyOf", "allOf") if key in schema]
    return ", ".join(f"{key}={schema[key]!r}" for key in keys) or "without a type"


def _group(
    alias: str, hints: dict[str, Any], group: str | None, group_ids: Sequence[str]
) -> str | None:
    """Return the ``group`` hint, checked against the spec's groups, or ``group``."""
    if "group" not in hints:
        return group
    if hints["group"] not in group_ids:
        raise TemplateError(f"{alias}: unknown group id {hints['group']!r}")
    return str(hints["group"])


def _output_property(
    alias: str, schema: dict[str, Any], group: str | None, group_ids: Sequence[str]
) -> dict[str, Any]:
    hints: dict[str, Any] = schema.get(TEMPLATE_KEY, {})
    unsupported = sorted(set(hints) - OUTPUT_HINT_KEYS)
    if unsupported:
        raise TemplateError(
            f"{alias}: output hints may only set {', '.join(sorted(OUTPUT_HINT_KEYS))}, "
            f"not {', '.join(unsupported)}"
        )
    value = hints.get("value", alias)
    if "value" in hints and not (
        isinstance(value, str) and (not value or OUTPUT_NAME.fullmatch(value))
    ):
        raise TemplateError(
            f"{alias}: output value {value!r} must be a process variable name "
            "(no spaces, $, {, or }) or empty"
        )
    optional = _flag(alias, hints, "optional")
    if optional is False and not value:
        raise TemplateError(
            f"{alias}: an output without a target variable is always optional"
        )
    group = _group(alias, hints, group, group_ids)
    prop: dict[str, Any] = {"label": schema["title"]}
    if "description" in schema:
        prop["description"] = schema["description"]
    prop.update({"type": "String", "value": value})
    if not value or optional:
        # An empty target variable name means the output mapping is not written.
        prop["optional"] = True
    editable = _flag(alias, hints, "editable")
    if editable is not None:
        prop["editable"] = editable
    if "condition" in hints:
        prop["condition"] = _condition(alias, hints["condition"])
    if group is not None:
        prop["group"] = group
    source = _text(alias, hints, "source")
    binding = {
        "type": "camunda:outputParameter",
        "source": f"${{{alias}}}" if source is None else source,
    }
    script_format = _text(alias, hints, "script_format")
    if script_format is not None:
        if source is None:
            raise TemplateError(
                f"{alias}: script_format needs the script as the source hint"
            )
        binding["scriptFormat"] = script_format
    prop["binding"] = binding
    return prop


def _optional_texts(where: str, /, **texts: object) -> None:
    """Require every given spec value to be a string or None."""
    for name, text in texts.items():
        if text is not None and not isinstance(text, str):
            raise TemplateError(f"{where}: {name} must be a string")


def _additional_inputs(
    spec: TaskTemplate, group: str | None, group_ids: Sequence[str]
) -> dict[str, Any]:
    """Render the Map of input parameters that modeler users add themselves."""
    additional = spec.additional_inputs
    label = f"{spec.topic}: additional_inputs"
    if not isinstance(additional, AdditionalInputs):
        raise TemplateError(f"{label} must be an AdditionalInputs")
    if not isinstance(additional.label, str) or not additional.label:
        raise TemplateError(f"{label} need a label")
    _optional_texts(label, description=additional.description, group=additional.group)
    if not isinstance(additional.mirror_outputs, bool):
        raise TemplateError(f"{label}: mirror_outputs must be a boolean")
    if additional.mirror_outputs and spec.element_type is ElementType.MESSAGE_END_EVENT:
        raise TemplateError(
            f"{label}: a message end event cannot map outputs; "
            "leave mirror_outputs off"
        )
    prop: dict[str, Any] = {"label": additional.label}
    if additional.description is not None:
        prop["description"] = additional.description
    prop["type"] = "Map"
    if additional.mirror_outputs:
        prop["mirrorOutputs"] = True
    constraints = _constraints(
        label,
        "Map",
        {},
        {} if additional.constraints is None else additional.constraints,
    )
    if constraints:
        prop["constraints"] = constraints
    group = _group(
        label, {"group": additional.group} if additional.group else {}, group, group_ids
    )
    if group is not None:
        prop["group"] = group
    prop["binding"] = {"type": "camunda:additionalInputParameters"}
    return prop


def _settings(spec: TaskTemplate, group_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Render the engine settings as properties bound to ``camunda:<name>``."""
    properties: list[dict[str, Any]] = []
    names: list[str] = []
    for setting in spec.settings:
        if not isinstance(setting, TaskSetting) or setting.name not in SETTINGS:
            raise TemplateError(
                f"{spec.topic}: settings must be TaskSetting objects named one "
                f"of {', '.join(SETTINGS)}"
            )
        label = f"{spec.topic}: setting {setting.name}"
        if setting.name in names:
            raise TemplateError(f"{label} is given twice")
        names.append(setting.name)
        _optional_texts(
            label,
            label=setting.label,
            description=setting.description,
            group=setting.group,
            placeholder=setting.placeholder,
        )
        default_label, boolean = SETTINGS[setting.name]
        value_type = bool if boolean else str
        if setting.value is not None and not isinstance(setting.value, value_type):
            raise TemplateError(f"{label}: value must be a {value_type.__name__}")
        if setting.hidden and setting.value is None:
            raise TemplateError(f"{label}: a hidden setting needs a value")
        if boolean and (setting.placeholder or setting.constraints):
            raise TemplateError(
                f"{label}: a boolean setting takes no placeholder or constraints"
            )
        prop: dict[str, Any] = {"label": setting.label or default_label}
        if setting.description is not None:
            prop["description"] = setting.description
        prop["type"] = (
            "Hidden" if setting.hidden else "Boolean" if boolean else "String"
        )
        if setting.value is not None:
            prop["value"] = setting.value
        if setting.placeholder is not None and not setting.hidden:
            prop["placeholder"] = setting.placeholder
        constraints = _constraints(
            label,
            "String",
            {},
            {} if setting.constraints is None else setting.constraints,
        )
        if constraints and not setting.hidden:
            prop["constraints"] = constraints
        group = _group(
            label, {"group": setting.group} if setting.group else {}, None, group_ids
        )
        if group is not None:
            prop["group"] = group
        prop["binding"] = {"type": "property", "name": f"camunda:{setting.name}"}
        properties.append(prop)
    return properties


def _errors(
    spec: TaskTemplate, group_ids: Sequence[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Render error definitions as properties and their ``bpmn:Error`` scopes."""
    properties: list[dict[str, Any]] = []
    scopes: list[dict[str, Any]] = []
    for error in spec.errors:
        if not isinstance(error, ErrorDefinition):
            raise TemplateError(f"{spec.topic}: errors must be ErrorDefinition objects")
        label = f"{spec.topic}: error {error.id!r}"
        texts = {
            "id": error.id,
            "expression": error.expression,
            "code": error.code,
            "name": error.name,
            "label": error.label,
        }
        for name, text in texts.items():
            if not isinstance(text, str) or not text:
                raise TemplateError(f"{label}: {name} must be a non-empty string")
        _optional_texts(
            label,
            message=error.message,
            description=error.description,
            group=error.group,
        )
        if error.id in [scope["id"] for scope in scopes]:
            raise TemplateError(f"{label} is defined twice")
        shown = "Hidden" if error.hidden else "String"
        prop: dict[str, Any] = {"label": error.label}
        if error.description is not None:
            prop["description"] = error.description
        prop.update({"type": shown, "value": error.expression})
        group = _group(
            label, {"group": error.group} if error.group else {}, None, group_ids
        )
        if group is not None:
            prop["group"] = group
        prop["binding"] = {"type": "camunda:errorEventDefinition", "errorRef": error.id}
        properties.append(prop)
        scoped = [("Error code", shown, error.code, "errorCode")]
        if error.message is not None:
            scoped.append(
                ("Error message", shown, error.message, "camunda:errorMessage")
            )
        scoped.append(("Error name", "Hidden", error.name, "name"))
        scopes.append(
            {
                "type": "bpmn:Error",
                "id": error.id,
                "properties": [
                    {
                        "label": scope_label,
                        "type": scope_type,
                        "value": value,
                        "binding": {"type": "property", "name": name},
                    }
                    for scope_label, scope_type, value, name in scoped
                ],
            }
        )
    return properties, scopes


def _link_conditions(topic: str, properties: Sequence[dict[str, Any]]) -> None:
    """Give every property a condition refers to an ``id``, and check the rest."""
    by_name = {
        prop["binding"]["name"]: prop
        for prop in properties
        if prop["binding"]["type"] == "camunda:inputParameter"
    }
    entry_ids = [
        entry["id"]
        for prop in properties
        for entry in prop.get("entries", ())
        if "id" in entry
    ]
    ids = set(entry_ids)
    if len(ids) != len(entry_ids):
        raise TemplateError(f"{topic}: entry ids must be unique in the template")
    conditions = [
        item["condition"]
        for prop in properties
        for item in (prop, *prop.get("entries", ()), *prop.get("choices", ()))
        if "condition" in item
    ]
    for condition in conditions:
        name = condition["property"]
        if name in by_name:
            target = by_name[name]
            if target["type"] in ("List", "Map") and "isActive" not in condition:
                raise TemplateError(
                    f"{topic}: a condition cannot compare the "
                    f"{target['type']} input {name!r}"
                )
            if name in ids:
                raise TemplateError(
                    f"{topic}: condition property {name!r} is both an input "
                    "alias and an entry id; rename the entry id"
                )
            target["id"] = name
        elif name not in ids:
            raise TemplateError(
                f"{topic}: condition property {name!r} is not an input alias "
                "or an entry id"
            )


def render(spec: TaskTemplate, *, icon_svg: bytes, schema_url: str) -> dict[str, Any]:
    """Render one element template from its spec and contract models."""
    if not _is_version(spec.version):
        raise TemplateError(f"{spec.topic}: version must be an integer of at least 1")
    if not isinstance(spec.element_type, ElementType):
        raise TemplateError(
            f"{spec.topic}: element_type must be an ElementType, e.g. "
            "ElementType.MESSAGE_INTERMEDIATE_THROW_EVENT"
        )
    for name in ("groups", "settings", "errors"):
        if not isinstance(getattr(spec, name), (tuple, list)):
            raise TemplateError(f"{spec.topic}: {name} must be a tuple")
    group_ids = [group.id for group in spec.groups]
    for group_id in (spec.input_group, spec.output_group) if spec.groups else ():
        if group_id not in group_ids:
            raise TemplateError(f"{spec.topic}: unknown group id {group_id!r}")
    # Without groups the properties are listed ungrouped.
    input_group = spec.input_group if spec.groups else None
    output_group = spec.output_group if spec.groups else None
    properties: list[dict[str, Any]] = [
        {
            "label": "Implementation",
            "type": "Hidden",
            "value": "external",
            "binding": {"type": "property", "name": "camunda:type"},
        },
        {
            "label": "External Task Topic",
            "type": "Hidden",
            "value": spec.topic,
            "binding": {"type": "property", "name": "camunda:topic"},
        },
    ]
    fixed = len(properties)
    properties.extend(_settings(spec, group_ids))
    properties.extend(
        _input_property(alias, schema, required, input_group, group_ids)
        for alias, schema, required in contract_properties(spec.inputs)
    )
    if spec.additional_inputs is not None:
        properties.append(_additional_inputs(spec, input_group, group_ids))
    outputs = [
        _output_property(alias, schema, output_group, group_ids)
        for alias, schema, _required in contract_properties(spec.outputs)
    ]
    if outputs and spec.element_type is ElementType.MESSAGE_END_EVENT:
        # The engine rejects camunda:outputParameter on end events.
        raise TemplateError(
            f"{spec.topic}: a message end event cannot map outputs; use an "
            "outputs contract without fields or another element_type"
        )
    targets = [output["value"] for output in outputs if output["value"]]
    repeated = sorted({target for target in targets if targets.count(target) > 1})
    if repeated:
        raise TemplateError(
            f"{spec.topic}: outputs map to the same process variable "
            f"{', '.join(map(repr, repeated))}; give each a distinct value hint"
        )
    properties.extend(outputs)
    error_properties, scopes = _errors(spec, group_ids)
    properties.extend(error_properties)
    _link_conditions(spec.topic, properties[fixed:])
    icon = base64.b64encode(icon_svg).decode("ascii")
    return {
        "$schema": schema_url,
        "name": spec.name,
        "id": spec.template_id,
        "description": spec.description,
        "version": spec.version,
        **spec.element_type.template_fields(),
        **(
            {
                "groups": [
                    {"id": group.id, "label": group.label} for group in spec.groups
                ]
            }
            if spec.groups
            else {}
        ),
        "properties": properties,
        **({"scopes": scopes} if scopes else {}),
        "icon": {"contents": f"data:image/svg+xml;base64,{icon}"},
    }


def dumps(template: dict[str, Any] | list[dict[str, Any]]) -> str:
    """Serialize a template in the committed file format."""
    return json.dumps(template, indent=2, ensure_ascii=False) + "\n"


def validate(paths: Sequence[Path], schema_url: str) -> None:
    """Validate template files against the pinned upstream schema.

    Raises ``TemplateError`` when there are no templates, ``jsonschema`` (the
    ``templates`` extra) is missing, the schema cannot be fetched, or a
    template does not conform.
    """
    if not paths:
        raise TemplateError("No element templates were found")
    try:
        from jsonschema import Draft7Validator
        from jsonschema import ValidationError
    except ImportError as error:
        raise TemplateError(
            "Schema validation needs jsonschema: install "
            "operaton-contracts[templates]"
        ) from error
    try:
        with urlopen(schema_url, timeout=30) as response:
            schema = json.load(response)
    except (OSError, ValueError) as error:
        raise TemplateError(f"Cannot load the schema {schema_url}: {error}") from error
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    for path in paths:
        try:
            validator.validate(json.loads(path.read_text(encoding="utf-8")))
        except ValidationError as error:
            location = "/".join(str(part) for part in error.absolute_path)
            raise TemplateError(
                f"{path.name}: {error.message} (at /{location})"
            ) from error
        print(f"Validated {path.name}")


def read_templates(path: Path) -> list[dict[str, Any]]:
    """Return the templates in a file: one object or a list, or none if missing."""
    if not path.exists():
        return []
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise TemplateError(f"{path.name}: invalid JSON: {error}") from error
    templates = content if isinstance(content, list) else [content]
    if not all(isinstance(template, dict) for template in templates):
        raise TemplateError(f"{path.name}: expected template objects")
    return templates


def _versions(templates: Iterable[dict[str, Any]], template_id: str) -> list[Any]:
    return [
        template.get("version")
        for template in templates
        if template.get("id") == template_id
    ]


def _is_version(value: object) -> bool:
    # bool is an int subclass, but True must not stand for version 1.
    return type(value) is int and value >= 1


def _check_keep_versions(spec: TaskTemplate) -> None:
    versions: object = spec.keep_versions
    if (
        not isinstance(versions, tuple)
        or not all(_is_version(version) for version in versions)
        or len(set(versions)) != len(versions)
        or any(version >= spec.version for version in versions)
    ):
        raise TemplateError(
            f"{spec.topic}: keep_versions must be a tuple of unique versions "
            f"from 1 to {spec.version - 1}, e.g. (1,), not {versions!r}"
        )


def _find_template(template_dir: Path, template_id: str) -> str | None:
    """Return the name of another file holding ``template_id``, if any."""
    for path in sorted(template_dir.glob("*.json")):
        try:
            templates = read_templates(path)
        except TemplateError:
            continue
        if _versions(templates, template_id):
            return path.name
    return None


def _kept_templates(spec: TaskTemplate, template_dir: Path) -> list[dict[str, Any]]:
    """Return the spec's kept versions, newest first, from the existing file."""
    path = template_dir / spec.filename
    if not path.exists():
        other = _find_template(template_dir, spec.template_id)
        hint = (
            f"rename {other} to {spec.filename} if filename changed"
            if other
            else "restore the file from version control"
        )
        raise TemplateError(
            f"{spec.filename}: kept versions of {spec.template_id} need the "
            f"existing file; {hint}"
        )
    existing = read_templates(path)
    kept = []
    for version in sorted(spec.keep_versions, reverse=True):
        matches = [
            template
            for template in existing
            if template.get("id") == spec.template_id
            and template.get("version") == version
        ]
        if len(matches) != 1:
            problem = "is missing" if not matches else "appears more than once"
            raise TemplateError(
                f"{spec.filename}: kept version {version} of {spec.template_id} "
                f"{problem}; restore the file from version control"
            )
        kept.append(matches[0])
    return kept


def render_all(
    specs: Sequence[TaskTemplate],
    *,
    icon_svg: bytes,
    schema_url: str,
    icons: Mapping[str, bytes] | None = None,
    template_dir: Path | None = None,
) -> dict[str, str]:
    """Render every spec, keyed by template filename.

    ``icons`` maps a spec's ``icon`` path to its SVG and replaces
    ``icon_svg`` for the specs that set one. Specs with ``keep_versions``
    copy those versions from their existing file in ``template_dir`` and
    render a list, newest first; other specs render a single template.
    """
    icons = icons or {}
    rendered: dict[str, str] = {}
    for spec in specs:
        svg = icon_svg
        if spec.icon is not None:
            if spec.icon not in icons:
                raise TemplateError(f"{spec.topic}: icon {spec.icon!r} is not loaded")
            svg = icons[spec.icon]
        template = render(spec, icon_svg=svg, schema_url=schema_url)
        _check_keep_versions(spec)
        if not spec.keep_versions:
            rendered[spec.filename] = dumps(template)
            continue
        if template_dir is None:
            raise TemplateError(
                f"{spec.topic}: keep_versions needs the template directory"
            )
        kept = _kept_templates(spec, template_dir)
        rendered[spec.filename] = dumps([template, *kept])
    return rendered


def write_templates(template_dir: Path, rendered: dict[str, str]) -> list[str]:
    """Write rendered templates, remove stale ones, and describe the changes."""
    template_dir.mkdir(parents=True, exist_ok=True)
    messages: list[str] = []
    for path in sorted(template_dir.glob("*.json")):
        if path.name not in rendered:
            path.unlink()
            messages.append(f"Removed stale {path.name}")
    for filename, text in rendered.items():
        (template_dir / filename).write_text(text, encoding="utf-8")
        messages.append(f"Wrote {filename}")
    return messages


def drift(template_dir: Path, rendered: dict[str, str]) -> list[str]:
    """Return differences between committed and rendered templates."""
    errors = [
        f"Stray element template: {path.name}"
        for path in sorted(template_dir.glob("*.json"))
        if path.name not in rendered
    ]
    for filename, text in rendered.items():
        path = template_dir / filename
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        errors.extend(_version_drift(path, json.loads(text)))
        errors.append(f"Out of date: {filename}; run generate")
    return errors


def _version_drift(path: Path, rendered: Any) -> list[str]:
    """Explain version changes between a committed and a rendered file."""
    try:
        committed = read_templates(path)
    except TemplateError as error:
        return [str(error)]
    templates = rendered if isinstance(rendered, list) else [rendered]
    current = templates[0]
    template_id, version = current["id"], current["version"]
    versions = _versions(templates, template_id)
    errors = [
        f"{path.name}: template {other.get('id')!r} would be dropped; it "
        "belongs in its own file"
        for other in committed
        if "id" in other and other["id"] != template_id
    ]
    for old in _versions(committed, template_id):
        if old in versions:
            continue
        if _is_version(old) and old > version:
            errors.append(
                f"{path.name}: committed version {old} of {template_id} is "
                f"newer than version {version}; set version above {old}"
            )
        else:
            errors.append(
                f"{path.name}: version {old} of {template_id} would be dropped; "
                "add it to keep_versions, or run generate to drop it"
            )
    same = [
        template
        for template in committed
        if template.get("id") == template_id and template.get("version") == version
    ]
    if same and same[0] != current:
        errors.append(
            f"{path.name}: version {version} of {template_id} changed; if it "
            f"is published, bump version and add {version} to keep_versions"
        )
    return errors
