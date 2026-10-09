# operaton-contracts

Pydantic task contracts for Robot Framework packages served as
[Operaton](https://operaton.org/) (Camunda 7) external tasks, for example by
[purjo](https://github.com/datakurre/purjo).

Documentation: <https://datakurre.github.io/operaton-contracts/>

One model per external task topic is the source of truth for what the task
accepts and returns:

- **At runtime** each Robot task validates and normalizes its process
  variables with `Validate Task Input`.
- **At build time** `operaton-contracts generate` renders one bpmn.io element
  template per topic from the same models, and `operaton-contracts check`
  verifies that the templates, `[tool.purjo.topics]`, and the Robot suites
  agree.

```console
uv add "operaton-contracts[robot]"   # runtime: pydantic + robotframework
uv add --group dev "operaton-contracts[templates]"   # uv-only: jsonschema for validate
```

When using devenv, provide `jsonschema` and development tools through
`devenv.nix` instead of duplicating them in uv's `dev` group.

## Contracts

```python
# OperatonTasks.py
from datetime import date
from typing import Any

from pydantic import Field
from OperatonContracts import TaskContract, template_hints


class ProcessRecordsInput(TaskContract):
    record_ids: list[str] = Field(
        alias="recordIds",
        title="Record IDs",
        min_length=1,
        json_schema_extra=template_hints(value=["${recordId}"]),
    )
    effective_date: date = Field(
        alias="effectiveDate", title="Effective date", strict=False
    )
    dry_run: bool = Field(alias="dryRun", title="Dry run", default=False)


class ProcessRecordsOutput(TaskContract):
    result: dict[str, Any] = Field(alias="result", title="Result variable")
```

`TaskContract` is strict, forbids extra fields, and strips strings. Every
field needs an `alias` (the process variable name) and a `title` (the
template label). Use `Literal[...]` for choices; `Enum`, `Optional`, and nested
models are not supported in template inputs; `dict[str, str]` renders as a
`Map`. `template_hints(value=..., type=..., group=..., entries=...)` sets
template-only defaults, property types, groups, and `Map` entries.

## Robot tasks

```robotframework
*** Settings ***
Library     OperatonContracts    OperatonTasks

*** Variables ***
${BPMN:TASK}    local
@{recordIds}    @{EMPTY}
${effectiveDate}    ${EMPTY}
${dryRun}    ${False}

*** Tasks ***
Process Records
    ${input}=    Validate Task Input    ProcessRecordsInput
    Log    ${input}[recordIds]
    VAR    ${result}=    ${{{}}}    scope=${BPMN:TASK}
```

`Validate Task Input` reads `${alias}` for every field, validates, and returns
the values JSON-compatible (dates as `YYYY-MM-DD`), keyed by alias. Declare
typed suite defaults (`${False}`, `${0}`, `@{EMPTY}`): strict contracts reject
the string `"0"` or `"false"`. The library imports the contracts module from
`sys.path`, falling back to the running suite's directory.

## Element templates

```toml
# pyproject.toml of the robot package
[tool.operaton-contracts]
specs = "OperatonTasks:TEMPLATES"               # module:attribute
icon = "logo.svg"                               # optional SVG icon
reserved-topics = ["legacy.topic"]              # optional
# schema-url = "…"                              # optional; pinned default
```

```python
# Append to OperatonTasks.py, after the task contracts.
from OperatonContracts.templates import TaskTemplate, TemplateGroup

TEMPLATES = (
    TaskTemplate(
        topic="records.process",
        template_id="org.example.records-process",
        name="Process Records",
        description="Process selected records.",
        filename="records-process.json",
        inputs=ProcessRecordsInput,
        outputs=ProcessRecordsOutput,
        groups=(TemplateGroup("main", "Processing"),),
        input_group="main",
        output_group="main",
    ),
)
```

Co-locating the specs adds no package dependency when tasks already use
`OperatonContracts` for `TaskContract` and `Validate Task Input`. Alternatively,
put the declarations in a root-level `OperatonTemplates.py` and set
`specs = "OperatonTemplates:TEMPLATES"`; list that file in `.wrapignore` so
`pur wrap` leaves it out of the robot package.

```console
operaton-contracts generate   # write .operaton/element-templates/*.json
operaton-contracts check      # offline: drift and package consistency
operaton-contracts validate   # against the pinned upstream schema (network)
```

The generated `.operaton/` templates do not have to be committed. Robot
packages may add `.operaton/` to `.gitignore` and run the
`operaton-contracts generate` command when the modeler needs the templates. If
using `check` in CI, generate the files first because `check` verifies that the
on-disk templates match the contracts. Packages that keep earlier template
versions with `keep_versions` must commit `.operaton/`, because those versions
exist only in the committed files.

`check` fails when on-disk templates differ from the generated ones, when
specs and `[tool.purjo.topics]` differ, when a topic is reserved or lacks
`process-variables = false`, or when the suite defining a topic's task lacks a
typed default for an input, the `Validate Task Input` call, or a
`VAR … scope=${BPMN:TASK}` for an output. Names are matched the way Robot
matches them, suites are collected recursively (skipping hidden directories,
`tests/`, `lib/`, `examples/`, and `test_*.robot`), and a task name defined in
more than one suite is an error.

## Agent skill

The package bundles an agent skill for building robot packages with these
conventions. Install it into `.agents/skills/` of your project, and refresh it
after upgrades with `--force`:

```console
uv run operaton-contracts install-skill
```

See the [Agent skill](https://datakurre.github.io/operaton-contracts/skill/) page.

## Development

```console
uv run --group dev --group docs make test check docs   # with uv
devenv shell -- make test check docs                   # or with devenv
make build
```

`make docs-serve` previews the documentation site, which is published to
GitHub Pages from `main` by `.github/workflows/docs.yml`.
The uv dependency groups provide test and documentation tools for uv-only
development. When using devenv, those tools come from `devenv.nix`; project
dependencies still come from uv.

## License

Apache License 2.0; see [LICENSE](LICENSE).

Releases are published to PyPI by `.github/workflows/release.yml` with
trusted publishing when a `v*` tag matching the project version is pushed.
