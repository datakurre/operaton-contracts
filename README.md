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
uv add operaton-contracts                   # runtime: pydantic + robotframework
uv add --group dev "operaton-contracts[templates]"   # adds jsonschema for validate
```

## Contracts

```python
# OperatonTasks.py
from datetime import date
from typing import Any, Literal

from pydantic import Field
from OperatonContracts import TaskContract, template_hints


class RescindStudyRightsInput(TaskContract):
    study_right_ids: list[str] = Field(
        alias="studyRightIds",
        title="Study right IDs",
        min_length=1,
        json_schema_extra=template_hints(value=["${studyRightId}"]),
    )
    cancellation_date: date = Field(
        alias="cancellationDate", title="Cancellation date", strict=False
    )
    dry_run: bool = Field(alias="dryRun", title="Dry run", default=False)


class RescindStudyRightsOutput(TaskContract):
    result: dict[str, Any] = Field(alias="result", title="Result variable")
```

`TaskContract` is strict, forbids extra fields, and strips strings. Every
field needs an `alias` (the process variable name) and a `title` (the
template label). Use `Literal[...]` for choices; `Enum`, `Optional`, and nested
models are not supported in template inputs. `template_hints(value=...,
type=...)` sets template-only defaults and property types.

## Robot tasks

```robotframework
*** Settings ***
Library     OperatonContracts    OperatonTasks

*** Variables ***
${BPMN:TASK}    local
@{studyRightIds}    @{EMPTY}
${cancellationDate}    ${EMPTY}
${dryRun}    ${False}

*** Tasks ***
Rescind Study Rights
    ${input}=    Validate Task Input    RescindStudyRightsInput
    Log    ${input}[studyRightIds]
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
specs = "scripts.element_templates:TEMPLATES"   # module:attribute
icon = "scripts/logo.svg"                       # optional SVG icon
reserved-topics = ["legacy.topic"]              # optional
# schema-url = "…"                              # optional; pinned default
```

```python
# scripts/element_templates.py
from OperatonContracts.templates import TaskTemplate, TemplateGroup
from OperatonTasks import RescindStudyRightsInput, RescindStudyRightsOutput

TEMPLATES = (
    TaskTemplate(
        topic="study_rights.rescind",
        template_id="org.example.study-rights-rescind",
        name="Rescind Study Rights",
        description="Rescind active study rights.",
        filename="study-rights-rescind.json",
        inputs=RescindStudyRightsInput,
        outputs=RescindStudyRightsOutput,
        groups=(TemplateGroup("main", "Rescission"),),
        input_group="main",
        output_group="main",
    ),
)
```

```console
operaton-contracts generate   # write .operaton/element-templates/*.json
operaton-contracts check      # offline: drift and package consistency
operaton-contracts validate   # against the pinned upstream schema (network)
```

`check` fails when committed templates differ from the generated ones, when
specs and `[tool.purjo.topics]` differ, when a topic is reserved or lacks
`process-variables = false`, or when the suite defining a topic's task lacks a
typed default for an input, the `Validate Task Input` call, or a
`VAR … scope=${BPMN:TASK}` for an output. Names are matched the way Robot
matches them, suites are collected recursively (skipping hidden directories,
`tests/`, `lib/`, `examples/`, and `test_*.robot`), and a task name defined in
more than one suite is an error.

## Development

```console
uv run --group dev --group docs make test check docs   # with uv
devenv shell -- make test check docs                   # or with devenv
make build
```

`make docs-serve` previews the documentation site, which is published to
GitHub Pages from `main` by `.github/workflows/docs.yml`.

## License

Apache License 2.0; see [LICENSE](LICENSE).

Releases are published to PyPI by `.github/workflows/release.yml` with
trusted publishing when a `v*` tag matching the project version is pushed.
