# Changelog

## Unreleased

- `dict[str, str]` inputs render as `Map` element-template properties. The
  new `entries` hint fixes their keys (with labels, entry types, and
  defaults) and is checked against the schema's entry rules; otherwise
  `Literal` or string `Enum` keys become the entries, or modeler users may
  add keys. Value length and pattern constraints become Map `constraints`,
  key patterns become `keyPattern`, and `Literal` values become Dropdown
  entries.
- The new `group` hint places an input in another of the spec's groups.
- `TaskTemplate.icon` embeds a per-template SVG instead of the configured
  `icon`; `Config.icons` holds the loaded files and `render_all` accepts them
  as `icons=`. Icons outside the project root are rejected.
- Template hints on output fields are rejected.
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
