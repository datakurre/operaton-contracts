# Changelog

## 0.5.0

Breaking: existing projects may need changes before `check` passes again or
error handling keeps working.

- `Validate Task Input` fails with `InvalidTaskInput` instead of a pydantic
  `ValidationError`. The message starts with the line `InvalidTaskInput`,
  which purjo uses as the BPMN `errorCode`, followed by the contract name and
  one `alias: problem (got value)` line per invalid variable. Error boundary
  events that matched the old `ValidationError: …` code need the new one.
- `check` no longer counts a `VAR ${x}=    ${None}    scope=${BPMN:TASK}`
  placeholder as setting output `x`: a task must also set its real value.

Changes:

- The agent skill and docs set every output to `${None}` with task scope
  before `Validate Task Input`: Operaton evaluates output mappings before a
  BPMN error reaches its boundary event, so outputs must exist even when the
  task fails. This needs purjo 1.0rc2 or newer, which stores them for tasks
  that end with a BPMN error.
- Input properties take every feature the element-template schema offers
  external tasks, through new `template_hints` keys: `value=None`,
  `placeholder`, `optional`, `editable`, `constraints` (`notEmpty`,
  `minLength`, `maxLength`, `pattern`, `minItems`, `maxItems`, `keyPattern`,
  with messages), `choices` (labels, or choices for plain `str` and
  `list[str]` fields), `display`, `item_type="Date"`, `condition` (the
  referenced input gets an `id`), `script_format`, and `additional_entries`
  for a Map with fixed entries.
- Output properties accept the `optional`, `source`, `script_format`,
  `condition`, and `editable` hints.
- `TaskTemplate.additional_inputs` takes an `AdditionalInputs` and renders a
  Map bound to `camunda:additionalInputParameters`, with `mirrorOutputs`,
  for inputs that modeler users name themselves.
- `TaskTemplate.settings` takes `TaskSetting` objects and renders the engine
  settings `asyncBefore`, `asyncAfter`, `exclusive`, `jobPriority`, and
  `taskPriority` as properties that modeler users may adjust, or as fixed
  hidden values.
- `TaskTemplate.errors` takes `ErrorDefinition` objects and renders
  `camunda:errorEventDefinition` properties with their `bpmn:Error` scopes,
  so the engine throws a BPMN error when an expression over the worker's
  result holds.
- `TaskTemplate(groups=())` renders a template without groups.
- Templates that use none of the new hints render exactly as before, with
  these exceptions, which rendered templates the schema rejects:
  a `type` hint of `String`, `Text`, or `Hidden` on a `Literal` field no
  longer keeps `choices`, and on a list field no longer keeps `display`,
  `choices`, or `itemType`.
- A `condition` in a Map entry is now checked like any other: it needs a
  `property` and one of `equals`, `oneOf`, or `isActive`, and its `property`
  must be an input alias (which then gets an `id`) or an entry `id`.
- `check` does not ask a task to set an output that has a `source` hint.
- `check` messages for a topic without a template spec, or a spec without a
  topic, say how to fix them.
- New tutorial page: a Greet task from `pur init` to a running Operaton
  process, with the values the engine sends and how invalid input surfaces,
  verified against Operaton 2.1.5 and purjo 1.0rc2.

## 0.4.0

- `TaskTemplate.element_type` selects the BPMN element a template applies
  to: every element C7/Operaton can run as an external task with a topic
  (`ElementType.SERVICE_TASK`, the default, `SEND_TASK`,
  `BUSINESS_RULE_TASK`, `MESSAGE_INTERMEDIATE_THROW_EVENT`, and
  `MESSAGE_END_EVENT`). Message events also render `elementType` with a
  `bpmn:MessageEventDefinition` (applied by the forked modeler).
  `MESSAGE_END_EVENT` rejects contracts with outputs, which Operaton does not
  allow on end events. Service-task templates are unchanged.

## 0.3.0

Breaking: existing projects may need changes before `generate` or `check`
passes again.

- `TaskTemplate.version` must be an integer of at least 1.
- Template hints on output fields were ignored before; now `value` and
  `group` take effect and any other hint is rejected.
- `check` rejects scalar suite defaults for array and object inputs; use
  `@{EMPTY}` or `&{EMPTY}`.

Changes:

- `dict[str, str]` inputs render as `Map` element-template properties. The
  new `entries` hint fixes their keys (with labels, entry types, and
  defaults) and is checked against the schema's entry rules; otherwise
  `Literal` or string `Enum` keys become the entries, or modeler users may
  add keys. Value length and pattern constraints become Map `constraints`,
  key patterns become `keyPattern`, and `Literal` values become Dropdown
  entries. A Dropdown entry's default must be one of its choices, and its
  choices must be contract values. Map keys must be strings.
- The new `group` hint places an input in another of the spec's groups.
- `TaskTemplate.icon` embeds a per-template SVG instead of the configured
  `icon`; `Config.icons` holds the loaded files and `render_all` accepts them
  as `icons=`. Icons outside the project root are rejected.
- `TaskTemplate.keep_versions` keeps earlier published template versions:
  `generate` copies them unchanged from the existing file and writes a list,
  newest first, so the modeler can upgrade diagrams. `check` explains
  versions that would be dropped and changed versions that need a bump.
  `render_all` takes `template_dir=` to read them. `version` must be an
  integer of at least 1.
- Output fields accept the `value` and `group` hints; `value=""` renders an
  optional, empty output mapping that is not written unless a modeler user
  names a variable. Other hints on outputs are rejected, as are hinted
  names with whitespace, `$`, `{`, or `}` and outputs mapped to the same
  variable.
- `check` requires list (`@`) defaults for array inputs and dictionary (`&`)
  defaults for object inputs, and suggests `&{EMPTY}`.

## 0.2.0

- Bundle the `purjo-operaton-task-package` agent skill and add
  `operaton-contracts install-skill [--force] [--skills-dir DIR]`, which
  installs it into `.agents/skills/` and links it into `.claude/skills/`
  for Claude Code (`--claude`/`--no-claude`; automatic when the project has
  `.claude/`). Linked or replaced entries are never followed into the
  installed skill, and symbolic links fall back to a copy where unavailable.
- `operaton-contracts` reports configuration, specs, icon, and schema
  validation problems as messages (exit status 2 or 1) instead of
  tracebacks; it rejects empty specs and a non-list `reserved-topics`, and
  no longer reuses a specs module imported from another project root.
- `check` treats `${EMPTY}` and `${None}` suite defaults of non-string inputs
  as untyped, and skips virtual environments when collecting suites.
- `import_contracts` tries every fallback directory in turn.

## 0.1.0

- Initial release: `TaskContract`, `template_hints`, the `OperatonContracts`
  Robot library with `Validate Task Input`, element-template generation,
  package consistency checks, and the `operaton-contracts` command.
