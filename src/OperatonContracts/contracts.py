"""Task contracts and their runtime validation, independent of any task runner."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable
from collections.abc import Mapping
from types import ModuleType
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import JsonValue

TEMPLATE_KEY = "x-element-template"
HINT_KEYS = frozenset({"entries", "group", "type", "value"})


class TaskContract(BaseModel):
    """Base for engine-facing task input and output contracts.

    Every field needs an ``alias`` (the process variable name) and a
    ``title`` (the template label). Field order is template property order.
    Validation is strict: use ``Field(strict=False)`` for values the engine
    sends as text, such as dates.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        strict=True,
        str_strip_whitespace=True,
    )


def template_hints(**hints: JsonValue) -> dict[str, JsonValue]:
    """Return ``json_schema_extra`` with template-only property hints.

    ``value`` overrides the template default value; ``type`` overrides the
    template property type inferred from the JSON Schema; ``group`` places the
    property in another of the template's groups; ``entries`` lists the fixed
    keys of a ``Map`` property as element-template entry objects (``key``
    plus optional ``label``, ``type``, ``value``, …). Required strings and
    non-empty strings or lists get ``notEmpty``; a Map's constraints come from
    its value schema. Outputs accept only ``value`` (the target variable;
    ``""`` writes no mapping unless a modeler user names one) and ``group``.
    """
    unknown = sorted(set(hints) - HINT_KEYS)
    if unknown:
        raise ValueError(f"Unknown template hint(s): {', '.join(unknown)}")
    return {TEMPLATE_KEY: hints}


def aliases(contract: type[TaskContract]) -> list[str]:
    """Return the contract's process variable names in field order."""
    return [info.alias or name for name, info in contract.model_fields.items()]


def validate_input(
    contract: type[TaskContract], variables: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate process variables against an input contract.

    Only the contract's aliases are read from ``variables``, so a task's full
    variable map can be passed; missing ones fall back to contract defaults.
    Returns the values normalized and JSON-compatible (dates become
    ``YYYY-MM-DD`` strings), keyed by alias.
    """
    data = {
        alias: variables[alias] for alias in aliases(contract) if alias in variables
    }
    return contract.model_validate(data).model_dump(mode="json", by_alias=True)


def validate_output(
    contract: type[TaskContract], values: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate a task's results against an output contract.

    Unlike inputs, every value is checked: unknown keys are rejected. Returns
    JSON-compatible values keyed by alias, ready to hand back to the engine.
    """
    return contract.model_validate(dict(values)).model_dump(mode="json", by_alias=True)


def load_contract(module: ModuleType, name: str) -> type[TaskContract]:
    """Return the ``TaskContract`` subclass called ``name`` from ``module``."""
    contract = getattr(module, name, None)
    if not (isinstance(contract, type) and issubclass(contract, TaskContract)):
        raise ValueError(f"{name} is not a TaskContract in {module.__name__}")
    return contract


def import_contracts(name: str, fallback_dirs: Iterable[str] = ()) -> ModuleType:
    """Import the contracts module, retrying from ``fallback_dirs``.

    Each directory not yet on ``sys.path`` is tried in turn while the module
    itself (not one of its dependencies) is missing; a directory is kept on
    ``sys.path`` only if the module was found there.
    """
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        for directory in fallback_dirs:
            if directory in sys.path:
                continue
            sys.path.insert(0, directory)
            try:
                return importlib.import_module(name)
            except ModuleNotFoundError as retry:
                if retry.name != name:
                    raise
                sys.path.remove(directory)
        raise
