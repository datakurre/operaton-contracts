# Changelog

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
