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
  regenerating the same version.
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
  `"${alias}"`. The value must fit the property type.
- `constraints.notEmpty`: `minLength ≥ 1`, `minItems ≥ 1`, or a required
  `String`.
- `group`: the spec's `input_group`, or the `group` hint.

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
- Entries are checked against the element-template schema's entry rules:
  non-empty unique keys, string values (boolean for `Boolean`), `choices`
  only and always on `Dropdown`, `placeholder` only on `String`/`Text`, and
  `constraints`/`optional` only on `String`/`Text`/`Dropdown`, never
  `optional` with `notEmpty`.
- `binding`: `camunda:inputParameter` named by the alias.

### Outputs

Each output is a `String` property bound as a `camunda:outputParameter`
with `source = "${alias}"`. Its value, the target process variable, is the
alias; modeler users may rename it.

Outputs accept only the `value` and `group` hints. `value="other"` changes
the default target variable. `value=""` leaves the target empty and adds
`"optional": true`, so the output mapping is not written unless a modeler
user names a variable; the worker's value is then not mapped to any process
variable. A hinted name may not contain whitespace, `$`, `{`, or `}`, and
two outputs may not map to the same variable.

## What `check` verifies

- On-disk templates equal the rendered ones (2-space JSON and a final
  newline), and there are no stray `*.json` files.
- Spec topics equal the keys of `[tool.purjo.topics]`; no topic is reserved;
  ids, filenames, and topics are unique; every topic sets
  `process-variables = false`.
- Exactly one suite defines each topic's task. Suites are collected
  recursively, skipping hidden directories, `tests/`, `lib/`, `examples/`, and
  `test_*.robot`. Task, keyword, and variable names are matched the way Robot
  matches them: case, spaces, and underscores are ignored, and
  `${name: type}`, `scope=BPMN:TASK`, and `Library.Keyword` forms are
  accepted.
- That suite declares a default for every input, typed for non-string inputs;
  the task calls `Validate Task Input    <InputContract>`; and it sets every
  output with `VAR … scope=${BPMN:TASK}`.

## Schema

The pinned default is the Operaton element-templates schema v0.8.3:

```
https://gitlab.com/vasara-bpm/vscode-operaton-bpmn-js-modeler/-/jobs/artifacts/v0.8.3/raw/operaton-element-templates-schema-v0.8.3.json?job=release
```

The `?job=release` query is required. The same URL is written as `$schema` in
every template. Validation uses `jsonschema`'s Draft 7 validator and needs the
`templates` extra.
