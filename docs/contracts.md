# Task contracts

A task contract describes the **engine-facing** variables of one external task
topic: what the process may pass in and what the task sets for the process.
Keep contracts in a module of their own (conventionally `OperatonTasks.py`)
next to the Robot suites, so both the runtime library and the template
generator can import them.

```python
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
from OperatonContracts import TaskContract, template_hints

Id = Annotated[str, Field(min_length=1)]
RecordStatus = Literal["PENDING", "ACTIVE", "COMPLETE"]


class ProcessRecordsInput(TaskContract):
    record_ids: list[Id] = Field(
        alias="recordIds",
        title="Record IDs",
        min_length=1,
        json_schema_extra=template_hints(value=["${recordId}"]),
    )
    excluded_statuses: list[RecordStatus] = Field(
        alias="excludedStatuses",
        title="Excluded statuses",
        default_factory=list,
        json_schema_extra=template_hints(value=["COMPLETE"]),
    )
    effective_date: date = Field(
        alias="effectiveDate", title="Effective date", strict=False
    )
    dry_run: bool = Field(
        alias="dryRun",
        title="Dry run",
        description="Return the request without sending it.",
        default=False,
    )

    @field_validator("record_ids", mode="before")
    @classmethod
    def trim_record_ids(cls, value: object) -> object:
        if isinstance(value, list):
            return [item.strip() for item in value if isinstance(item, str)]
        return value


class ProcessRecordsOutput(TaskContract):
    result: dict[str, Any] = Field(alias="result", title="Result variable")
```

## Rules

- **`alias` and `title` are required.** The alias is the process variable
  name and must be a plain identifier (`[A-Za-z_][A-Za-z0-9_]*`); the title is
  the template label. `description` becomes the template's help text. Field
  order is the order of the template properties.
- **Validation is strict.** `TaskContract` sets `strict=True`,
  `extra="forbid"`, `populate_by_name=True`, and `str_strip_whitespace=True`.
  `"false"` is not a boolean and `"0"` is not an integer. Use
  `Field(strict=False)` for values the engine sends as text, such as dates.
- **Model what the engine may send.** Accept alternative encodings (a CSV
  string for a list, say) with `field_validator(..., mode="before")` and keep
  the declared type the canonical one, so the template keeps the right
  property type.
- **Choices come from `Literal[...]`.** A `Literal` string becomes a
  `Dropdown`; a list of `Literal` strings becomes a taglist `List`. `Enum`,
  `Optional`, and nested models produce `$ref`/`anyOf` JSON Schemas, which
  cannot be rendered as template inputs.
- **Keep contracts separate from API models.** Contracts describe the
  external task; models for the APIs a task calls belong elsewhere. Share field
  types such as `Literal` choices and `Annotated` ID types instead of
  inheriting between the two.

## Template hints

`template_hints(**hints)` returns a `json_schema_extra` value with
template-only information. Unknown keys raise `ValueError`.

| Hint | Effect |
|---|---|
| `value` | The template's pre-filled value, e.g. `["${recordId}"]` or a default selection |
| `type` | Override the template property type: `String`, `Text`, `Hidden`, `Dropdown`, `Boolean`, `List`, or `Map` |
| `group` | Show the property in another of the spec's `groups` instead of `input_group` |
| `entries` | Fixed keys of a `Map` (`dict[str, str]`) input as element-template entries, e.g. `[{"key": "fi", "label": "Suomeksi", "type": "Text"}]` |

Without a `value` hint the template uses the schema `default`, then `[]` for
lists, then `"${alias}"`. Note that `default_factory` does not appear in the
JSON Schema, so lists with `default_factory=list` need a `value` hint to
pre-fill anything.

A `dict[str, str]` input renders as a `Map`. Without an `entries` hint, the
keys of `dict[Literal["fi", "en"], str]` (or of a string `Enum`) become its
entries; any other string map lets modeler users add their own keys
(`additionalEntries`). A Map takes no value: use `default_factory=dict` or
`= {}`. See [Map inputs](templates.md#map-inputs) for constraints.

Output fields accept only the `value` and `group` hints: `value` names the
default target process variable, and `value=""` maps nothing unless a
modeler user names one. Two outputs may not map to the same variable.

## Values from Operaton

When purjo runs a task, process variables arrive as:

- strings, booleans, and JSON values as `str`, `bool`, `list`, and `dict`;
- numbers as `int` or `float`, depending on the variable type;
- `Date` variables as local-time strings like `"2024-05-01 00:00:00.000"`.
  A `date` field with `strict=False` accepts these only at midnight; prefer
  string form fields with `YYYY-MM-DD` values for dates;
- `null` variables as `None`, which replaces the suite default and fails
  non-optional fields.

Literal (non-expression) input parameters in the BPMN always arrive as
strings: `5` is the string `"5"`, while `${5}` is an integer. See
[Values from the engine](tutorial.md#values-from-the-engine).
