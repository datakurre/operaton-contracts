# Agent skill

`operaton-contracts` ships an agent skill, `purjo-operaton-task-package`, that
teaches coding agents the conventions of a robot package served as Operaton
external tasks by purjo:

- topics in `pyproject.toml` and task contracts in `OperatonTasks.py`;
- Robot suites that start with `Validate Task Input` and set outputs with
  task scope;
- generated element templates, example BPMN with start forms, and the checks
  that keep them in sync;
- `pyproject.toml`, `Makefile`, `.wrapignore`, and tests, with uv or an
  optional devenv environment;
- bootstrap assets for a new robot package.

## Install

Run in the robot package's root:

```console
uv run operaton-contracts install-skill
```

The skill is written to `.agents/skills/purjo-operaton-task-package/`, the
agent-neutral skills directory.

Claude Code reads skills only from `.claude/skills/`. When the project has a
`.claude/` directory, `install-skill` also creates the relative symbolic link
`.claude/skills/purjo-operaton-task-package` →
`../../.agents/skills/purjo-operaton-task-package`. Use `--claude` to create
the link even without `.claude/`, or `--no-claude` to skip it. An existing
entry that is not that link (an older copy, or a link elsewhere) is replaced
only with `--force`. Link the directory similarly for other agents that read
skills from elsewhere.

The installed copy belongs to the package version that wrote it, so treat it
and the `.claude/skills/` link as generated: list `.agents/` and the link in
`.gitignore`, list `.agents/` and `.claude/` in `.wrapignore`, and run
`install-skill` after cloning. (If you commit them instead, commit both, or
the link dangles in fresh clones.)

## Update

After upgrading `operaton-contracts`, refresh the copy:

```console
uv run operaton-contracts install-skill --force
```

Without `--force` the command leaves a copy with local changes untouched and
exits with status 1. To change the skill itself, edit
`src/OperatonContracts/skills/` in the `operaton-contracts` repository.

`--skills-dir` installs into another directory, relative to `--root`.
