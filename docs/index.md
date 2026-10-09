# operaton-contracts

Pydantic task contracts for [Robot Framework](https://robotframework.org/)
packages served as [Operaton](https://operaton.org/) (Camunda 7) external
tasks, for example by [purjo](https://github.com/datakurre/purjo).

One pair of models per external task topic is the source of truth for what
the task accepts and returns:

```
OperatonTasks.py          task contracts: one Input/Output model per topic
      │ generates                          │ validates at runtime
element template (modeler)        Robot task: Validate Task Input → keywords
```

- **At runtime** every Robot task starts with
  `${input}=    Validate Task Input    <Contract>`, which reads the task's
  process variables, validates them strictly, and returns them normalized.
- **At build time** `operaton-contracts generate` renders one
  [bpmn.io element template](templates.md) per topic from the same models, and
  `operaton-contracts check` verifies that the templates, the purjo topics in
  `pyproject.toml`, and the Robot suites agree.

## Install

```console
uv add operaton-contracts
uv add --group dev "operaton-contracts[templates]"
```

The runtime needs only `pydantic` and `robotframework`. The `templates` extra
adds `jsonschema` for `operaton-contracts validate`.

## A complete topic

```python title="OperatonTasks.py"
from typing import Any

from pydantic import Field
from OperatonContracts import TaskContract


class GreetInput(TaskContract):
    name: str = Field(alias="name", title="Name", min_length=1)
    dry_run: bool = Field(alias="dryRun", title="Dry run", default=False)


class GreetOutput(TaskContract):
    greeting: str = Field(alias="greeting", title="Greeting")
```

```robotframework title="greet.robot"
*** Settings ***
Library     OperatonContracts    OperatonTasks

*** Variables ***
${BPMN:TASK}    local
${name}         ${EMPTY}
${dryRun}       ${False}

*** Tasks ***
Greet
    ${input}=    Validate Task Input    GreetInput
    VAR    ${greeting}=    Hello ${input}[name]    scope=${BPMN:TASK}
```

```toml title="pyproject.toml"
[tool.purjo.topics."example.greet"]
name = "Greet"
on-fail = "ERROR"
process-variables = false

[tool.operaton-contracts]
specs = "scripts.element_templates:TEMPLATES"
```

```python title="scripts/element_templates.py"
from OperatonContracts.templates import TaskTemplate
from OperatonTasks import GreetInput, GreetOutput

TEMPLATES = (
    TaskTemplate(
        topic="example.greet",
        template_id="org.example.greet",
        name="Example: Greet",
        description="Greets someone.",
        filename="example-greet.json",
        inputs=GreetInput,
        outputs=GreetOutput,
    ),
)
```

```console
operaton-contracts generate   # writes .operaton/element-templates/example-greet.json
operaton-contracts check      # offline consistency check, e.g. in CI
```

## License

Apache License 2.0.
