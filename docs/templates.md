# Element templates

`operaton-contracts` renders one Camunda 7 element template per external task
topic into `.operaton/element-templates/`, for the Operaton modeler and
compatible bpmn.io modelers.

## Configuration

```toml title="pyproject.toml"
[tool.operaton-contracts]
specs = "OperatonTasks:TEMPLATES"                # module:attribute, required
icon = "logo.svg"                               # SVG for specs without their own
reserved-topics = ["legacy.topic"]              # topics owned by other workers
schema-url = "https://…?job=release"            # pinned schema; has a default
```

The specs module and icon path are resolved from the project root. When the
robot package already uses `OperatonContracts` at runtime for task contracts
and Robot validation, put the template specs in `OperatonTasks.py` alongside
the contract models. This adds no package dependency. The `templates` extra is needed only for
`validate`, which checks templates against the upstream schema. With devenv, provide `jsonschema` through
`devenv.nix` and keep it out of uv's `dev` group.

```python title="OperatonTasks.py"
from OperatonContracts.templates import ElementType, TaskTemplate, TemplateGroup

TEMPLATES = (
    TaskTemplate(
        topic="records.process",
        template_id="org.example.records-process",  # stable; never reuse
        name="Process Records",
        description="Process selected records.",
        filename="records-process.json",
        inputs=ProcessRecordsInput,
        outputs=ProcessRecordsOutput,
        groups=(TemplateGroup("main", "Processing"),),
        input_group="main",
        output_group="main",
        version=1,  # bump when a published template changes
        keep_versions=(),  # earlier published versions; see Versions
        element_type=ElementType.SERVICE_TASK,  # see Element types
    ),
)
```

Alternatively, keep the specs out of the runtime task module in a root-level
`OperatonTemplates.py` and set `specs = "OperatonTemplates:TEMPLATES"`. If
using `pur wrap`, list that module and the root-level icon in `.wrapignore`
so they stay out of the robot package.

A spec may set `icon="other.svg"` (relative to the project root) to embed its
own SVG instead of the configured `icon`. Icons must be files inside the
project root; list per-spec icons in `.wrapignore` as well.

The default groups are `inputs` ("Inputs") and `outputs` ("Results").
`input_group` and `output_group` must be ids from `groups`; use one id for
both to show every property in a single group.

## Commands

```console
operaton-contracts generate   # write templates, remove stale ones
operaton-contracts check      # offline; the default command
operaton-contracts validate   # against the pinned upstream schema (network)
```

All commands accept `--root <dir>` (default: the current directory) and are
also available as `python -m OperatonContracts`. They exit with status 0 on
success, 1 when checks or schema validation fail, and 2 for usage or
configuration errors (a missing or invalid `[tool.operaton-contracts]`
table, specs module, or icon), always with a message instead of a traceback.

The generated `.operaton/` directory is optional source control state. A robot
package may add `.operaton/` to `.gitignore`; run `operaton-contracts generate`
to recreate the templates when the modeler needs them. If CI runs `check` with
the directory ignored, generate the files first: `check` verifies the on-disk
templates against the contracts and reports missing or stale files. Packages
that use `keep_versions` must commit `.operaton/`, because earlier versions
exist only there.

## Versions

The worker always serves the latest contract, but diagrams keep the template
version they were modeled with. To let the modeler resolve those diagrams and
offer "Update template", keep earlier published versions in the file:

```python
TaskTemplate(..., version=4, keep_versions=(2, 3))
```

- Bump `version` whenever a published template changes; until then, keep
  regenerating the same version. When the change breaks diagrams that use
  the earlier version, also move the task to a new topic; see
  [Versioning tasks](#versioning-tasks).
- `generate` renders the current version from the contracts and copies each
  kept version unchanged from the existing file (matched by `id` and
  `version`), writing a JSON list, newest first. Without `keep_versions` the
  file holds a single template.
- `version` and kept versions are integers of at least 1; `keep_versions` is
  a tuple (write `(1,)`, not `(1)`) of unique versions lower than `version`.
- Each kept version must appear exactly once in the file; a missing or
  duplicated one is an error (restore the file from version control) rather
  than silently resolved. If the file is gone but another file holds the
  template id, the error suggests renaming it, e.g. after a `filename`
  change.
- `check` explains drift: a committed version absent from `keep_versions`
  "would be dropped", a committed version newer than `version` asks for a
  higher version, a changed current version should get a bump if it is
  already published, and templates with another id in the file would be
  dropped.
- Kept versions are the committed file's content, so `check` cannot detect a
  hand edit to them; review such diffs like any other change.
- Remove a version by dropping it from `keep_versions` and running
  `generate`.
- Kept versions are copied as they were, so they may differ in anything,
  including `appliesTo`.

## Versioning tasks

A template version and the task behind it change together. The engine,
though, keeps running diagrams that were modeled with an earlier version:
they still send the old inputs and expect the old outputs. Two kinds of
change follow from that.

**A compatible change** keeps every deployed diagram working: a new input
with a contract default, another output, or a new label, description, choice
label, or constraint. Bump `version` and keep the topic. One Robot task
serves all versions.

**A breaking change** would fail diagrams that use the old version: a new
required input, a removed or renamed input or output, or a changed type.
Give the new version its own topic, and keep serving the old one:

1. Keep the old contract and Robot task under versioned names.
2. Change the current contract and task.
3. Move the spec to a new topic, bump `version`, and list the old version in
   `keep_versions`.
4. Serve both topics.

No new mechanism is needed, only a naming convention. The first version
keeps its plain topic, because it is already published; later breaking
versions append `.v<N>`:

| | Current version | Earlier version |
|---|---|---|
| Topic | `example.greet.v2` | `example.greet` |
| Robot task | `Greet` | `Greet V1` |
| Input contract | `GreetInput` | `GreetInputV1` |

```python title="OperatonTasks.py"
class GreetInputV1(TaskContract):
    name: str = Field(alias="name", title="Name", min_length=1)


class GreetInput(TaskContract):
    name: str = Field(alias="name", title="Name", min_length=1)
    language: Literal["en", "fi"] = Field(alias="language", title="Language")


TEMPLATES = (
    TaskTemplate(
        topic="example.greet.v2",          # was "example.greet"
        template_id="org.example.greet",   # unchanged
        ...,
        inputs=GreetInput,
        outputs=GreetOutput,
        version=2,
        keep_versions=(1,),
    ),
)
```

```toml title="pyproject.toml"
[tool.purjo.topics."example.greet"]       # diagrams on version 1
name = "Greet V1"
process-variables = false

[tool.purjo.topics."example.greet.v2"]    # diagrams on version 2
name = "Greet"
process-variables = false
```

```robotframework title="greet.robot"
*** Tasks ***
Greet V1
    VAR    ${greeting}=    ${None}    scope=${BPMN:TASK}
    ${input}=    Validate Task Input    GreetInputV1
    VAR    ${greeting}=    Hello ${input}[name]    scope=${BPMN:TASK}

Greet
    VAR    ${greeting}=    ${None}    scope=${BPMN:TASK}
    ${input}=    Validate Task Input    GreetInput
    VAR    ${greeting}=    Hello ${input}[name] (${input}[language])    scope=${BPMN:TASK}
```

`generate` then writes both versions into the one template file: version 2
with the new topic and inputs, and version 1 copied unchanged with the old
topic. Deployed diagrams keep running `Greet V1`. The modeler resolves both
versions from the file, and updating a diagram's template to version 2
applies the new topic together with the new inputs.

`check` reads the topic of every kept version from the template file. Such
a topic needs no spec of its own, but it must still be in
`[tool.purjo.topics]` with `process-variables = false`, and a suite must
define its task; otherwise old diagrams would wait for a worker that no
longer exists. `check` cannot compare the old task with the old contract,
because a kept version is only the committed JSON: keep a test for the old
task while you serve it.

To retire a version, first make sure nothing uses its topic: no deployed
process definition refers to it, and the engine lists no external tasks for
it (`GET /engine-rest/external-task?topicName=example.greet`). Then remove
it from `keep_versions`, delete its topic, task, and contract, and run
`generate`.

## Element types

C7/Operaton implements these BPMN elements as external tasks with a topic,
and `element_type` (from `OperatonContracts.templates`) picks one per
template:

| `ElementType` | `appliesTo` | `elementType` |
|---|---|---|
| `SERVICE_TASK` (default) | `bpmn:ServiceTask` | — |
| `SEND_TASK` | `bpmn:SendTask` | — |
| `BUSINESS_RULE_TASK` | `bpmn:BusinessRuleTask` | — |
| `MESSAGE_INTERMEDIATE_THROW_EVENT` | `bpmn:IntermediateThrowEvent` | `eventDefinition: bpmn:MessageEventDefinition` |
| `MESSAGE_END_EVENT` | `bpmn:EndEvent` | `eventDefinition: bpmn:MessageEventDefinition` |

For message events, `camunda:type` and `camunda:topic` live on the
`messageEventDefinition`, and `elementType` makes the modeler add that
definition when the template is applied. This needs the vasara-bpm forked
modeler; upstream C7 element templates ignore `eventDefinition`. Operaton
rejects output mappings on end events, so `MESSAGE_END_EVENT` needs an
outputs contract without fields. Changing `element_type` changes the
template's bindings, so bump `version` once the template is published.

## Generated structure

Each template has `$schema`, `name`, `id`, `description`, `version`,
`appliesTo` (and `elementType` for message events), `groups`, `properties`,
and the icon. Properties start with Hidden `camunda:type = external` and
`camunda:topic = <topic>`.

### Inputs

| JSON Schema | Template property |
|---|---|
| `boolean` | `Boolean` |
| `string` (any `format`, e.g. `date`) | `String` |
| `string` with `enum` (`Literal`) | `Dropdown` with `choices` |
| `array` of `string` | `List` with `itemType: "String"` |
| `array` of `string` with `items.enum` | `List` with `choices` and `display: "taglist"` |
| `object` of `string` (`dict[str, str]`) | `Map`; see below |
| anything else | error, unless a `type` hint is given |

- `value`: the `value` hint, the schema `default`, `[]` for `List`, or
  `"${alias}"`. The value must fit the property type. `value=None` leaves the
  value out, so the modeler pre-fills nothing.
- `constraints.notEmpty`: `minLength ≥ 1`, `minItems ≥ 1`, or a required
  `String`.
- `group`: the spec's `input_group`, or the `group` hint. A spec with
  `groups=()` renders no groups, and its properties are listed ungrouped.
- `choices`: the `Literal` values, each named by its value. A `choices` hint
  names them (`[{"name": "E-mail", "value": "email"}]`), may leave some out,
  and may give a choice its own `condition`. A pre-filled value must be one
  of the hinted choices, or an expression. On a plain `str` (with
  `type="Dropdown"`) or `list[str]` the hint alone defines the choices.
- `display`: `"taglist"` for a `List` with choices; set the hint to
  `"checklist"`, or to `None` for the modeler's default.
- `itemType`: `"String"` for a `List` without choices; `item_type="Date"`
  makes each item a date.
- `placeholder`, `editable`: from the hints of the same name. A placeholder
  needs a `String` or `Text` property.
- `optional`: with `optional=True` the modeler does not write the input
  parameter while it is empty. Only `String`, `Text`, and `Dropdown` inputs
  can be optional, the contract field needs a default (the task sees it when
  the input is left out), and the input cannot also be `notEmpty`. An
  optional input is not pre-filled unless it has a `value` hint or a
  non-empty default.
- `binding.scriptFormat`: `script_format="groovy"` with the script as the
  `value` hint, on a `String`, `Text`, or `Hidden` property. The engine
  evaluates the script and passes its result, so the contract type is the
  result's type; add a `type` hint (`"Text"` suits scripts) when the field
  is not a string.

### Constraints

The `constraints` hint is merged over the derived `notEmpty`; its keys
override it, and `"notEmpty": False` removes it.

| Constraint | Applies to | Value |
|---|---|---|
| `notEmpty` | any input | boolean |
| `minLength`, `maxLength` | text, each `List` item, each `Map` value | integer |
| `pattern` | text, each `List` item, each `Map` value | a regular expression, or `{"value": "…", "message": "…"}` |
| `minItems`, `maxItems` | `List` | integer |
| `keyPattern` | `Map` keys that modeler users add | like `pattern` |

Contract constraints such as `Field(pattern=…)` are **not** copied to scalar
and list inputs, because modeler users often enter an expression like
`${guestId}`, which the contract checks only after the engine has resolved
it. Write the modeler-side rule as a hint, and let it accept expressions:

```python
guest_id: str = Field(
    alias="id",
    title="Guest ID",
    pattern=r"^guest-[0-9a-f-]{36}$",                 # checked at runtime
    json_schema_extra=template_hints(
        value="${guestId}",
        constraints={
            "pattern": {
                "value": r"^(guest-[0-9a-f-]{36}|\$\{.+\})$",   # checked in the modeler
                "message": "Use guest-<uuid> or an expression.",
            }
        },
    ),
)
```

### Conditions

A `condition` hint shows a property, and writes its value, only while
another property has a given value:

```python
channel: Literal["email", "sms"] = Field(alias="channel", title="Channel", default="email")
phone_number: str = Field(
    alias="phoneNumber",
    title="Phone number",
    default="",
    json_schema_extra=template_hints(
        condition={"property": "channel", "equals": "sms"}
    ),
)
```

- `property` is the alias of another input; that property gets an `id` equal
  to its alias. It may also be the `id` of a `Map` entry.
- Give exactly one of `equals` (a value), `oneOf` (a list of values), or
  `isActive` (whether the other property is itself shown).
- A `List` or `Map` input cannot be compared with `equals` or `oneOf`;
  `isActive` may refer to one. Conditions also work on outputs, `Map`
  entries, and single `choices`, and are checked the same way.
- A hidden input is not written to the XML, so a contract field with a
  condition needs a default.
- An entry `id` may not equal the alias of an input that a condition
  refers to, and entry ids are unique in the template.

### Map inputs

A `dict[str, str]` input renders as a `Map`, bound as a
`camunda:inputParameter` holding a `camunda:map`.

- Fixed keys (`entries`): the `entries` hint, else the keys of
  `dict[Literal[...], str]` (one or more) or of `dict[StrEnum, str]`.
  Hinted keys must be among the contract's `Literal`/`Enum` keys and match a
  key pattern. Without fixed keys the Map gets `additionalEntries: true`, so
  modeler users add their own keys.
- Map `constraints` apply to *every value*: value `min_length ≥ 1` gives
  `notEmpty`, and value `min_length`, `max_length`, and `pattern` carry over.
  A key pattern (`dict[Annotated[str, StringConstraints(pattern=...)], str]`)
  becomes `keyPattern` for user-added keys. Other key constraints are
  rejected. Being required does not add `notEmpty`; to require an entry's
  value, put `"constraints": {"notEmpty": true}` in that entry.
- `Literal` value choices (`dict[Literal["a"], Literal["x", "y"]]`) make each
  entry a `Dropdown`; they need fixed keys. Hinted `choices` must be among
  those values, and a Dropdown entry's `value` must be one of its choices.
- Keys must be strings: integer `Enum` keys are rejected.
- A Map takes no value: use `default_factory=dict` or `= {}`, and pre-fill
  entries with `value` in the `entries` hint.
- `additional_entries=True` adds `additionalEntries` to a Map with fixed
  `entries`, so modeler users can add keys next to them. The contract keys
  and values must then be free (`dict[str, str]` or a key pattern, not
  `Literal` keys or values).
- The `constraints` hint is merged over the derived Map constraints; see
  [Constraints](#constraints).
- Entries are checked against the element-template schema's entry rules:
  non-empty unique keys, string values (boolean for `Boolean`), `choices`
  only and always on `Dropdown`, `placeholder` only on `String`/`Text`, and
  `constraints`/`optional` only on `String`/`Text`/`Dropdown`, never
  `optional` with `notEmpty`.
- `binding`: `camunda:inputParameter` named by the alias.

### User-added inputs

`TaskTemplate(additional_inputs=AdditionalInputs(...))` adds one more `Map`,
bound to `camunda:additionalInputParameters`: every key a modeler user adds
becomes an input parameter of that name.

```python
from OperatonContracts.templates import AdditionalInputs, TaskTemplate

TaskTemplate(
    ...,
    additional_inputs=AdditionalInputs(
        label="Fields to load",
        description="Each row names a variable and the field to load into it.",
        group="fields",                 # default: input_group
        mirror_outputs=True,
        constraints={"notEmpty": True, "keyPattern": "^[a-z_][a-z0-9_]*$"},
    ),
)
```

- The property follows the contract inputs. Its `constraints` take
  `notEmpty`, `minLength`, `maxLength`, and `pattern` for the values and
  `keyPattern` for the names.
- `mirror_outputs=True` keeps an output mapping `<name> = ${<name>}` for
  every user-added input, so a result the task sets under the same name
  reaches the process. A message end event cannot map outputs.
- The contract does not describe these inputs, and `Validate Task Input`
  does not return them. The task reads them as ordinary variables, and
  `check` does not ask for suite defaults or outputs for them.

### Outputs

Outputs accept the `value`, `group`, `optional`, `source`, `script_format`,
`condition`, and `editable` hints.

Each output is a `String` property bound as a `camunda:outputParameter`
with `source = "${alias}"`. Its value, the target process variable, is the
alias; modeler users may rename it. `value="other"` changes
the default target variable. `value=""` leaves the target empty and adds
`"optional": true`, so the output mapping is not written unless a modeler
user names a variable; the worker's value is then not mapped to any process
variable. A hinted name may not contain whitespace, `$`, `{`, or `}`, and
two outputs may not map to the same variable.

- `optional=True` keeps the pre-filled target variable but lets a modeler
  user clear it; the mapping is then not written.
- `source="${ result.id }"` maps from another expression than `${alias}`.
  With `script_format="groovy"` the source is a script. `check` then does
  not ask the task to set `${alias}`; the task must set whatever the source
  reads.
- `condition` and `editable` work as on inputs.

### Task settings

`TaskTemplate(settings=...)` lets modeler users adjust engine settings of the
task. Each `TaskSetting` is a property bound to `camunda:<name>`, listed
after the topic and before the inputs:

```python
from OperatonContracts.templates import DEFAULT_GROUPS, TaskSetting
from OperatonContracts.templates import TaskTemplate, TemplateGroup

TaskTemplate(
    ...,
    groups=(*DEFAULT_GROUPS, TemplateGroup("jobs", "Job execution")),
    settings=(
        TaskSetting("asyncBefore", value=True, group="jobs"),
        TaskSetting("asyncAfter", value=False, group="jobs"),
        TaskSetting("exclusive", value=True, hidden=True),
        TaskSetting("jobPriority", placeholder="e.g. 10", group="jobs"),
        TaskSetting(
            "taskPriority",
            placeholder="e.g. 50 or ${priority}",
            constraints={
                "pattern": {
                    "value": r"^(\d+|\$\{.+\})?$",
                    "message": "Must be a number or an expression.",
                }
            },
        ),
    ),
)
```

| `name` | Property | Value |
|---|---|---|
| `asyncBefore`, `asyncAfter`, `exclusive` | `Boolean` | `True` or `False` |
| `jobPriority`, `taskPriority` | `String` | text: a number or an expression |

- `value` pre-fills the setting; `hidden=True` fixes that value without
  showing it, and needs one.
- `label` defaults to the setting's usual name, e.g. "Asynchronous before".
  `description` and `group` are optional; without a `group` the setting is
  listed outside the groups.
- `placeholder` and `constraints` apply to the two text settings.
- Each setting may be given once. On message events the modeler decides
  which element the property is written to; check the result in your
  modeler before publishing such a template.

### Errors

`TaskTemplate(errors=...)` defines BPMN errors that the engine throws from
the worker's result. Each `ErrorDefinition` renders a property bound to
`camunda:errorEventDefinition`, listed after the outputs, and a `bpmn:Error`
scope with the error's code, message, and name:

```python
from OperatonContracts.templates import ErrorDefinition, TaskTemplate

TaskTemplate(
    ...,
    errors=(
        ErrorDefinition(
            id="payment-failed",                       # unique in the template
            expression='${ status == "DECLINED" }',
            code="PAYMENT_DECLINED",                   # what boundary events catch
            name="Payment failed",
            message="Payment was declined",            # optional
            description="Evaluated on the worker's result.",
        ),
    ),
)
```

- The engine evaluates `expression` when the worker completes the task. It
  can read the variables the task returned, such as the contract outputs.
  When it holds, the engine throws the error instead of completing the
  task, so an error boundary event with the same code catches it. (Operaton
  also evaluates it when a worker reports a failure, with `externalTask`
  available to the expression.)
- This works for a task that **succeeds**: the Robot task sets its outputs
  as usual, the topic keeps `on-fail = "FAIL"`, and the template decides
  which results are business errors. Output mappings are evaluated first,
  as for any BPMN error; see [Outputs](robot.md#outputs).
- Modeler users may edit the expression, code, and message. `hidden=True`
  fixes all three. The error name is always fixed.
- `label` (default "Throw error when"), `description`, and `group` describe
  the expression field.

## What `check` verifies

- On-disk templates equal the rendered ones (2-space JSON and a final
  newline), and there are no stray `*.json` files.
- Spec topics equal the keys of `[tool.purjo.topics]`; no topic is reserved;
  ids, filenames, and topics are unique; every topic sets
  `process-variables = false`.
- A topic that only a kept template version uses is also a key of
  `[tool.purjo.topics]`, with `process-variables = false` and a task that
  exactly one suite defines; see [Versioning tasks](#versioning-tasks).
- Exactly one suite defines each topic's task. Suites are collected
  recursively, skipping hidden directories, `tests/`, `lib/`, `examples/`, and
  `test_*.robot`. Task, keyword, and variable names are matched the way Robot
  matches them: case, spaces, and underscores are ignored, and
  `${name: type}`, `scope=BPMN:TASK`, and `Library.Keyword` forms are
  accepted.
- That suite declares a default for every input, typed for non-string inputs;
  the task calls `Validate Task Input    <InputContract>`; and it sets every
  output with `VAR … scope=${BPMN:TASK}`, except outputs with a `source`
  hint.

## Schema

The pinned default is the Operaton element-templates schema v0.8.3:

```
https://gitlab.com/vasara-bpm/vscode-operaton-bpmn-js-modeler/-/jobs/artifacts/v0.8.3/raw/operaton-element-templates-schema-v0.8.3.json?job=release
```

The `?job=release` query is required. The same URL is written as `$schema` in
every template. Validation uses `jsonschema`'s Draft 7 validator and needs the
`templates` extra.
