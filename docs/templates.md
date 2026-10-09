# Element templates

`operaton-contracts` renders one Camunda 7 element template per external task
topic into `.operaton/element-templates/`, for the Operaton modeler and
compatible bpmn.io modelers.

## Configuration

```toml title="pyproject.toml"
[tool.operaton-contracts]
specs = "OperatonTasks:TEMPLATES"                # module:attribute, required
icon = "logo.svg"                               # SVG embedded in every template
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
from OperatonContracts.templates import TaskTemplate, TemplateGroup

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
        version=1,  # bump when bindings change incompatibly
    ),
)
```

Alternatively, keep the specs out of the runtime task module in a root-level
`OperatonTemplates.py` and set `specs = "OperatonTemplates:TEMPLATES"`. If
using `pur wrap`, list that module and the root-level icon in `.wrapignore`
so they stay out of the robot package.

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
templates against the contracts and reports missing or stale files.

## Generated structure

Each template has `$schema`, `name`, `id`, `description`, `version`,
`appliesTo: ["bpmn:ServiceTask"]`, `groups`, `properties`, and the icon.
Properties start with Hidden `camunda:type = external` and
`camunda:topic = <topic>`.

### Inputs

| JSON Schema | Template property |
|---|---|
| `boolean` | `Boolean` |
| `string` (any `format`, e.g. `date`) | `String` |
| `string` with `enum` (`Literal`) | `Dropdown` with `choices` |
| `array` of `string` | `List` with `itemType: "String"` |
| `array` of `string` with `items.enum` | `List` with `choices` and `display: "taglist"` |
| anything else | error, unless a `type` hint is given |

- `value`: the `value` hint, the schema `default`, `[]` for `List`, or
  `"${alias}"`. The value must fit the property type.
- `constraints.notEmpty`: `minLength ≥ 1`, `minItems ≥ 1`, or a required
  `String`.
- `binding`: `camunda:inputParameter` named by the alias.

### Outputs

A `String` property whose value is the alias, bound as a
`camunda:outputParameter` with `source = "${alias}"`. Modeler users may rename
the target process variable.

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
