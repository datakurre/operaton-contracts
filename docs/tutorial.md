# Tutorial: purjo end to end

This tutorial builds one external task from an empty directory to a running
process: a **Greet** task that takes a name and returns a greeting. Along the
way it shows where each tool fits:

- [purjo](https://github.com/datakurre/purjo) (`pur`) scaffolds the robot
  package, deploys BPMN, and serves the package as an external task worker;
- `operaton-contracts` describes what the task accepts and returns, validates
  it at runtime, and generates the element template the modeler uses;
- [Operaton](https://operaton.org/) runs the process.

```
OperatonTasks.py ──generate──▶ .operaton/element-templates/greet.json ──▶ modeler ──▶ greet.bpmn
       │                                                                                 │
       └──Validate Task Input──▶ greet.robot ◀──pur serve── Operaton ◀──pur run──────────┘
```

Every command below was run against Operaton 2.1.5, purjo 1.0rc1, and
Robot Framework 7.5. Catching invalid input with an error boundary event
([When input is invalid](#when-input-is-invalid)) needs purjo 1.0rc2.

## 1. Start Operaton

With a container runtime:

```console
podman run --rm -ti -p 8080:8080 operaton/operaton:latest
```

Without one, download the "run" distribution (`operaton-bpm-<version>.tar.gz`)
from the [Operaton releases](https://github.com/operaton/operaton/releases),
unpack it, and start it with Java 17 or newer:

```console
./internal/run.sh start --webapps --rest
```

Either way the REST API answers on <http://localhost:8080/engine-rest> and
Cockpit and Tasklist on <http://localhost:8080/operaton/> (user `demo`,
password `demo`). `curl localhost:8080/engine-rest/version` confirms the engine
is up.

## 2. Create the robot package

`pur init` creates a working purjo example. Start from its task flavour:

```console
mkdir greeter && cd greeter
uv run --with=purjo -- pur init --task
```

`pur init` is made for getting started: its example passes the whole process
scope to the task and sets results on the process, so a newcomer can run a
task without thinking about inputs and outputs. Contracts make those inputs
and outputs explicit, so tidy the example up before adding one:

| `pur init` creates | Change it to | Why |
|---|---|---|
| `hello.robot`, `Hello.py`, `test_hello.robot`, `hello.bpmn` | delete them (or keep them until step 6 as a reference) | `check` requires a template for every topic in `pyproject.toml` |
| `[tool.purjo.topics."My Topic in BPMN"]` with `process-variables = true` | remove it; step 5 adds the real topic with `process-variables = false` | the task should only see the variables the template maps |
| `src/<package>/`, `[project.scripts]`, `[build-system]` | delete them | a robot package is not an installable Python package; without them uv does not build and reinstall it on every `uv run` and in every worker run |
| empty `.wrapignore` | fill it in (see [step 9](#9-package-the-robot)) | keeps tooling out of `robot.zip` |

Then add the dependencies:

```console
uv add "operaton-contracts[robot]"
uv add --group dev purjo "operaton-contracts[templates]"
```

`operaton-contracts[robot]` is a runtime dependency: the deployed suites
import its `OperatonContracts` library. purjo and the `templates` extra
(schema validation) are only needed on the developer machine.

!!! tip "Let your coding agent do this"
    `uv run operaton-contracts install-skill` installs an
    [agent skill](skill.md) that knows these conventions and has bootstrap
    assets for a complete package, including tests and a Makefile.

## 3. Describe the task with a contract

The contract is the single source of truth for the task's process
variables. Create `OperatonTasks.py` next to the suites:

```python title="OperatonTasks.py"
from pydantic import Field
from OperatonContracts import TaskContract
from OperatonContracts.templates import TaskTemplate


class GreetInput(TaskContract):
    name: str = Field(alias="name", title="Name", min_length=1)
    dry_run: bool = Field(alias="dryRun", title="Dry run", default=False)


class GreetOutput(TaskContract):
    greeting: str = Field(alias="greeting", title="Greeting")


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

Each `alias` is a process variable name, and each `title` becomes a label in
the modeler. `TEMPLATES` lists one `TaskTemplate` per topic. See
[Task contracts](contracts.md) for the field rules.

## 4. Write the Robot task

```robotframework title="greet.robot"
*** Settings ***
Library     OperatonContracts    OperatonTasks

*** Variables ***
${BPMN:TASK}    local
${name}         ${EMPTY}
${dryRun}       ${False}

*** Tasks ***
Greet
    VAR    ${greeting}=    ${None}    scope=${BPMN:TASK}
    ${input}=    Validate Task Input    GreetInput
    VAR    ${greeting}=    Hello ${input}[name]    scope=${BPMN:TASK}
```

Four conventions make the suite fit the contract:

- **A typed default for every input.** With `process-variables = false` an
  unmapped input is simply absent, so the suite default applies. Contracts
  are strict: `${False}` is a boolean, while `false` would be a string.
- **`Validate Task Input` first.** It reads `${name}` and `${dryRun}`,
  validates and normalizes them (here: trims the name), and returns them
  keyed by alias. Use `${input}[name]` from then on.
- **Outputs with task scope.** `scope=${BPMN:TASK}` hands `greeting` back to
  the engine, where the template's output mapping picks it up. Declaring
  `${BPMN:TASK}    local` lets the suite run outside purjo too.
- **Outputs set before anything can fail.** The first line sets `greeting`
  to `${None}`. The engine evaluates the output mappings even when the task
  ends with a BPMN error, so every output must exist by then; see
  [When input is invalid](#when-input-is-invalid).

## 5. Register the topic

The topic connects the BPMN service task to the Robot task. Add both tables
to `pyproject.toml`:

```toml title="pyproject.toml"
[tool.purjo.topics."example.greet"]
name = "Greet"                # the Robot task to run
on-fail = "FAIL"              # see "When input is invalid"
process-variables = false     # only the template-mapped variables

[tool.operaton-contracts]
specs = "OperatonTasks:TEMPLATES"
```

## 6. Generate and check

```console
$ uv run operaton-contracts generate
Wrote example-greet.json
$ uv run operaton-contracts check
Element templates are up to date and the package is consistent
```

`generate` writes `.operaton/element-templates/example-greet.json`. `check`
confirms that every topic has a template, the suite defining `Greet` has
typed defaults, calls `Validate Task Input    GreetInput`, and sets
`greeting` with task scope, and that the templates on disk are current. It
explains what to fix otherwise, for example:

```text
Topic has no template spec: My Topic in BPMN (add a TaskTemplate for it, or serve it from another package)
```

Run it in CI after `generate`, so contracts, suites, and templates cannot
drift apart.

## 7. Try the task locally

Robot runs the task without an engine. Pass typed values with `-v`:

```console
$ uv run robot --output NONE --log NONE --report NONE -v name:Ada greet.robot
Greet                                                                 | PASS |
$ uv run robot --output NONE --log NONE --report NONE greet.robot
Greet                                                                 | FAIL |
InvalidTaskInput
GreetInput:
name: String should have at least 1 character (got '')
```

`-v dryRun:true` fails the same way, because `true` is a string. Use
`-v "dryRun: bool:true"` to pass a boolean. For repeatable tests, see
[Testing tasks](robot.md#testing-tasks).

## 8. Model, deploy, and serve

### Apply the template

Open the project in a modeler that reads `.operaton/element-templates/`:

- the [Operaton BPMN modeler for VS Code](https://marketplace.visualstudio.com/items?itemName=datakurre.vscode-operaton-bpmn-js-modeler)
  loads `**/.operaton/element-templates/**/*.json` and
  `**/.camunda/element-templates/**/*.json` from the workspace (use version
  0.8.3 or newer);
- Camunda Modeler 5 reads `.camunda/element-templates/` instead: link or copy
  the generated files there.

Draw a start event, a service task, and an end event, then choose
**Example: Greet** from the service task's template menu. The modeler fills
in everything the contract describes:

```xml title="examples/greet.bpmn (service task)"
<bpmn:serviceTask id="Greet" name="Greet"
    camunda:modelerTemplate="org.example.greet" camunda:modelerTemplateVersion="1"
    camunda:type="external" camunda:topic="example.greet">
  <bpmn:extensionElements>
    <camunda:inputOutput>
      <camunda:inputParameter name="name">${name}</camunda:inputParameter>
      <camunda:inputParameter name="dryRun">${false}</camunda:inputParameter>
      <camunda:outputParameter name="greeting">${greeting}</camunda:outputParameter>
    </camunda:inputOutput>
  </bpmn:extensionElements>
</bpmn:serviceTask>
```

`${name}` reads a process variable, so give the start event a `name` form
field, or pass it when starting the process as below. Save the diagram as
`examples/greet.bpmn`. `examples/` is skipped by `check` and stays out of
`robot.zip`.

### Run it

```console
$ uv run pur run examples/greet.bpmn --variables '{"name": "  Ada "}'
Started: http://localhost:8080/operaton/app/cockpit/default/#/process-instance/…/runtime
$ uv run pur serve .
… | INFO | … | Topic | example.greet | {'name': 'Greet', 'on-fail': 'FAIL', 'process-variables': False}
Greet                                                                 | PASS |
… | INFO | … | Completing example.greet:….
```

`pur run` deploys the diagram and starts an instance; `pur serve .` polls the
topics in `pyproject.toml`, runs each task in a fresh uv environment built
from `uv.lock`, and completes the external task. Cockpit (follow the
`Started:` link) now shows `greeting = "Hello Ada"`: the name arrived with
spaces and the contract trimmed it. Stop the worker with Ctrl+C.

## 9. Package the robot

`pur wrap` zips the directory into `robot.zip`, which `pur serve robot.zip`
serves anywhere. Only the runtime files belong in it: the suites,
`OperatonTasks.py`, `pyproject.toml`, and `uv.lock`. Exclude the rest in
`.wrapignore`:

```gitignore title=".wrapignore"
.operaton/
examples/
tests/
test_*.robot
.agents/
.claude/
AGENTS.md
Makefile
README.md
```

The generated templates do not have to be committed either: add
`.operaton/` to `.gitignore` and run `generate` when the modeler needs them.
Commit them only when a spec uses `keep_versions`; see
[Versions](templates.md#versions).

## When input is invalid

`Validate Task Input` fails the task with a message whose first line is the
stable code `InvalidTaskInput`, followed by one line per invalid variable:

```text
InvalidTaskInput
GreetInput:
name: String should have at least 1 character (got '   ')
```

What happens next depends on the topic's `on-fail`:

| `on-fail` | Invalid input becomes | Notes |
|---|---|---|
| `FAIL` (default) | an incident with the full message | Fix the input in Cockpit and retry the external task. |
| `ERROR` | a BPMN error, `errorCode = InvalidTaskInput` | purjo uses the first line of a failure as `errorCode` and the rest as `errorMessage`. An error boundary event with error code `InvalidTaskInput` catches it once the outputs are set; see below. |
| `COMPLETE` | a completed task with `errorCode` and `errorMessage` local variables | The process continues. The variables are local to the task, so add output mappings for them in the modeler to use them in a gateway. |

### Outputs and BPMN errors

An error boundary event is reached only after the task's output mappings
have been evaluated. The template maps `greeting` from `${greeting}`, so a
task that fails before setting it cannot propagate its error: Operaton
reports `ENGINE-13033 Propagation of bpmn error InvalidTaskInput failed`
(cause: `Cannot resolve identifier 'greeting'`), and the task gets an
incident instead.

That is why the suite sets every output to `${None}` before it validates
anything:

```robotframework
Greet
    VAR    ${greeting}=    ${None}    scope=${BPMN:TASK}
    ${input}=    Validate Task Input    GreetInput
    …
```

purjo 1.0rc2 stores the task-scope variables a failed task has set as local
variables of the task execution, so the mapping resolves and the process
continues from the boundary event with `greeting` set to `null` (or to
whatever value the task set before a later step failed). purjo
1.0rc1 sends only process-scope variables with a BPMN error; with it, use
`on-fail = "FAIL"` and handle invalid input as incidents.

Outputs with `template_hints(value="")` have no mapping unless a modeler
user names a variable, but set them first anyway: a user may map them later.

## Values from the engine

The process variables a task receives depend on how the BPMN produces them,
not only on the contract:

| BPMN input parameter | Robot receives |
|---|---|
| `${name}` (String variable) | `str` |
| `${true}`, `${false}` | `bool` |
| `${5}` | `int` |
| `5` (literal text) | `str` `"5"` (fails a strict `int` field) |
| `<camunda:list>` | `list` |
| `<camunda:map>` | `dict` |
| `${when}` (Date variable) | `str` like `"2024-05-01 00:00:00.000"` |

Integer inputs need a `template_hints(type="String")` to render, and the
modeler then writes literal text; give such fields `Field(strict=False)` so
`"5"` validates as `5`.

## Where to go next

- [Task contracts](contracts.md): lists, choices, maps, and validators.
- [Robot tasks](robot.md): defaults, outputs, and testing tasks.
- [Element templates](templates.md): groups, icons, versions, and element
  types.
- [purjo documentation](https://datakurre.github.io/purjo/): secrets,
  files, and serving options.
