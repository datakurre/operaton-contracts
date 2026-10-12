# Robot tasks

## The library

```robotframework
*** Settings ***
Library     OperatonContracts    OperatonTasks
```

The argument names the module holding the contracts (default:
`OperatonTasks`). The library imports it from `sys.path`. purjo and
`python -m robot` run with the robot package on `sys.path`; for a plain
`robot` run from another directory, the library falls back to the directory of
the running suite.

## Validate Task Input

```robotframework
*** Tasks ***
Process Records
    ${input}=    Validate Task Input    ProcessRecordsInput
    Log    ${input}[recordIds]
```

The keyword reads `${alias}` for every field of the named contract, validates
the values, and returns a dictionary keyed by alias. The values are
JSON-compatible: dates become `YYYY-MM-DD` strings. Variables that are not set
are left out, so the contract defaults apply.

Invalid input fails the task with a message whose first line is
`InvalidTaskInput`, followed by the contract name and one line per invalid
variable:

```text
InvalidTaskInput
GreetInput:
name: String should have at least 1 character (got '   ')
```

purjo uses the first line of a failure as the BPMN `errorCode`, so with
`on-fail = "ERROR"` an error boundary event with code `InvalidTaskInput`
catches invalid input, provided the task has set its outputs first (see
[Outputs](#outputs)). [When input is invalid](tutorial.md#when-input-is-invalid)
describes the other `on-fail` modes.

Use `${input}[alias]` after validation, never the raw variable. Type checks,
trimming, deduplication, and non-empty checks belong in the contract instead
of `Should Be True    isinstance(...)` steps.

## Defaults

With purjo's `process-variables = false`, only variables mapped by the
element template reach the task, so every input needs a suite default.
Because contracts are strict, defaults must have the right type:

| Contract type | Suite default |
|---|---|
| `str` | `${name}    ${EMPTY}` |
| `bool` | `${dryRun}    ${False}` |
| `int` | `${count}    ${0}` or `${count: int}    0` |
| `list` | `@{ids}    @{EMPTY}` |
| `dict` | `&{options}    &{EMPTY}` |

A plain `${count}    0` or `${dryRun}    false` is a string and fails
validation. `operaton-contracts check` rejects untyped defaults for non-string
inputs. Keep suite defaults equal to the contract defaults: the suite default
is what the task sees when the engine omits a variable, while the contract
default only pre-fills the template.

For manual runs, pass typed variables: `robot -v "dryRun: bool:true" …`.

## Outputs

Set every contract output with task scope, first to `${None}` before
anything can fail, then to its value:

```robotframework
Process Records
    VAR    ${result}=    ${None}    scope=${BPMN:TASK}
    ${input}=    Validate Task Input    ProcessRecordsInput
    …
    VAR    ${result}=    ${apiResult}    scope=${BPMN:TASK}
```

and declare `${BPMN:TASK}    local` so the suite also runs outside purjo.

The engine evaluates a task's output mappings before a BPMN error reaches its
boundary event. A template maps each output from `${alias}`, so an output the
failed task never set makes the error propagation fail with an incident
(`ENGINE-13033`). With the outputs set first, purjo (1.0rc2 or newer) stores
them as local variables of the failed task, the mappings resolve (to `null`,
or to the value set before a later step failed),
and the boundary event is reached.

## Testing tasks

Run the real task with
[RobotLibrary](https://pypi.org/project/robotframework-robotlibrary/):

```robotframework
*** Settings ***
Library     RobotLibrary

*** Tasks ***
Greet validates its input
    Run Robot Task    ${CURDIR}/../greet.robot    Greet
    ...    BPMN:TASK=global
    ...    name=${SPACE}Ada${SPACE}
    Should Be Equal    ${greeting}    Hello Ada
```

- `Run Robot Task` injects the target suite's variable defaults before your
  overrides, so a caller variable with the same name as a task input is
  overwritten: name caller variables differently.
- `Secret` arguments fail inside `TRY` around `Run Robot Task`. Negative cases
  that fail input validation need no credentials, so leave them out.
