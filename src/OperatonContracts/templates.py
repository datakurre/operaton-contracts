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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
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
class TaskTemplate:
    """Template-level metadata for one external task topic.

    ``input_group`` and ``output_group`` are group ids from ``groups``; use
    the same id for both to show every property in one group.
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
    return [
        (alias, prop, alias in required)
        for alias, prop in schema.get("properties", {}).items()
    ]


def _choices(values: Iterable[Any]) -> list[dict[str, Any]]:
    return [{"name": str(value), "value": value} for value in values]


def _input_property(
    alias: str, schema: dict[str, Any], required: bool, group: str
) -> dict[str, Any]:
    hints: dict[str, Any] = schema.get(TEMPLATE_KEY, {})
    prop: dict[str, Any] = {"label": schema["title"]}
    if "description" in schema:
        prop["description"] = schema["description"]

    json_type = schema.get("type")
    items: dict[str, Any] = schema.get("items", {})
    if json_type == "boolean":
        prop["type"] = "Boolean"
    elif json_type == "string" and "enum" in schema:
        prop["type"] = "Dropdown"
        prop["choices"] = _choices(schema["enum"])
    elif json_type == "string":
        prop["type"] = "String"
    elif json_type == "array" and items.get("type") == "string":
        prop["type"] = "List"
        if "enum" in items:
            prop["display"] = "taglist"
            prop["choices"] = _choices(items["enum"])
        else:
            prop["itemType"] = "String"
    elif "type" not in hints:
        raise TemplateError(
            f"{alias}: unsupported JSON Schema {_describe(schema)}; Enum, "
            "Optional, and nested models produce $ref/anyOf schemas. Use "
            "Literal, a plain type, or add a type hint"
        )
    if "type" in hints:
        prop["type"] = hints["type"]
    if prop["type"] not in VALUE_TYPES:
        raise TemplateError(
            f"{alias}: template type {prop['type']!r} is not one of "
            f"{', '.join(VALUE_TYPES)}"
        )
    if prop["type"] == "Dropdown" and "choices" not in prop:
        raise TemplateError(f"{alias}: a Dropdown needs Literal choices")

    if "value" in hints:
        prop["value"] = hints["value"]
    elif "default" in schema:
        prop["value"] = schema["default"]
    elif prop["type"] == "List":
        prop["value"] = []
    else:
        prop["value"] = f"${{{alias}}}"
    if not isinstance(prop["value"], VALUE_TYPES[prop["type"]]):
        raise TemplateError(
            f"{alias}: value {prop['value']!r} does not fit template type "
            f"{prop['type']}; add a value hint"
        )
    if (
        schema.get("minLength", 0) >= 1
        or schema.get("minItems", 0) >= 1
        or (required and prop["type"] == "String")
    ):
        prop["constraints"] = {"notEmpty": True}
    prop["group"] = group
    prop["binding"] = {"type": "camunda:inputParameter", "name": alias}
    return prop


def _describe(schema: dict[str, Any]) -> str:
    keys = [key for key in ("type", "$ref", "anyOf", "allOf") if key in schema]
    return ", ".join(f"{key}={schema[key]!r}" for key in keys) or "without a type"


def _output_property(alias: str, schema: dict[str, Any], group: str) -> dict[str, Any]:
    prop: dict[str, Any] = {"label": schema["title"]}
    if "description" in schema:
        prop["description"] = schema["description"]
    prop.update(
        {
            "type": "String",
            "value": alias,
            "group": group,
            "binding": {"type": "camunda:outputParameter", "source": f"${{{alias}}}"},
        }
    )
    return prop


def render(spec: TaskTemplate, *, icon_svg: bytes, schema_url: str) -> dict[str, Any]:
    """Render one element template from its spec and contract models."""
    group_ids = [group.id for group in spec.groups]
    for group_id in (spec.input_group, spec.output_group):
        if group_id not in group_ids:
            raise TemplateError(f"{spec.topic}: unknown group id {group_id!r}")
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
    properties.extend(
        _input_property(alias, schema, required, spec.input_group)
        for alias, schema, required in contract_properties(spec.inputs)
    )
    properties.extend(
        _output_property(alias, schema, spec.output_group)
        for alias, schema, _required in contract_properties(spec.outputs)
    )
    icon = base64.b64encode(icon_svg).decode("ascii")
    return {
        "$schema": schema_url,
        "name": spec.name,
        "id": spec.template_id,
        "description": spec.description,
        "version": spec.version,
        "appliesTo": ["bpmn:ServiceTask"],
        "groups": [{"id": group.id, "label": group.label} for group in spec.groups],
        "properties": properties,
        "icon": {"contents": f"data:image/svg+xml;base64,{icon}"},
    }


def dumps(template: dict[str, Any]) -> str:
    """Serialize a template in the committed file format."""
    return json.dumps(template, indent=2, ensure_ascii=False) + "\n"


def validate(paths: Sequence[Path], schema_url: str) -> None:
    """Validate template files against the pinned upstream schema."""
    if not paths:
        raise TemplateError("No element templates were found")
    from jsonschema import Draft7Validator  # the "templates" extra

    with urlopen(schema_url, timeout=30) as response:
        schema = json.load(response)
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    for path in paths:
        validator.validate(json.loads(path.read_text(encoding="utf-8")))
        print(f"Validated {path.name}")


def render_all(
    specs: Sequence[TaskTemplate], *, icon_svg: bytes, schema_url: str
) -> dict[str, str]:
    """Render every spec, keyed by template filename."""
    return {
        spec.filename: dumps(render(spec, icon_svg=icon_svg, schema_url=schema_url))
        for spec in specs
    }


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
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            errors.append(f"Out of date: {filename}; run generate")
    return errors
