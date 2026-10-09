# Changelog

## Unreleased

- `Validate Task Input` fails with `InvalidTaskInput` instead of a pydantic
  `ValidationError`. The message starts with the line `InvalidTaskInput`,
  which purjo uses as the BPMN `errorCode`, followed by the contract name and
  one `alias: problem (got value)` line per invalid variable.
- `check` messages for a topic without a template spec, or a spec without a
  topic, say how to fix them.
- `check` no longer counts a `VAR ${x}=    ${None}    scope=${BPMN:TASK}`
  placeholder as setting output `x`: a task must also set its real value.
- The agent skill and docs set every output to `${None}` with task scope
  before `Validate Task Input`: Operaton evaluates output mappings before a
  BPMN error reaches its boundary event, so outputs must exist even when the
  task fails (needs purjo 1.0rc2 or newer to store them for failed tasks).
- New tutorial page: a Greet task from `pur init` to a running Operaton
  process, with the values the engine sends and how invalid input surfaces.

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
