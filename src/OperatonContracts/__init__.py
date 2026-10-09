"""Engine-facing Operaton external task contracts.

A worker declares one ``TaskContract`` input and output model per external
task topic. Element templates are generated from those models (see
``OperatonContracts.templates`` and the ``operaton-contracts`` command), and
tasks validate their variables against them at runtime with
``validate_input`` and ``validate_output``.

With the ``robot`` extra, the package is also a Robot Framework library:

    *** Settings ***
    Library     OperatonContracts    OperatonTasks

    *** Tasks ***
    Process Records
        ${input}=    Validate Task Input    ProcessRecordsInput

The library class is imported lazily, so ``import OperatonContracts`` never
loads Robot Framework.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from OperatonContracts.contracts import TEMPLATE_KEY
from OperatonContracts.contracts import TaskContract
from OperatonContracts.contracts import load_contract
from OperatonContracts.contracts import template_hints
from OperatonContracts.contracts import validate_input
from OperatonContracts.contracts import validate_output

if TYPE_CHECKING:
    from OperatonContracts.robotframework import OperatonContracts

__all__ = [
    "TEMPLATE_KEY",
    "OperatonContracts",
    "TaskContract",
    "load_contract",
    "template_hints",
    "validate_input",
    "validate_output",
]


def __getattr__(name: str) -> Any:
    # Robot Framework finds the library class with getattr(module, name).
    if name == "OperatonContracts":
        try:
            from OperatonContracts.robotframework import OperatonContracts
        except ModuleNotFoundError as error:
            if error.name is None or not error.name.startswith("robot"):
                raise
            raise ImportError(
                "The OperatonContracts Robot Framework library needs Robot "
                "Framework: install operaton-contracts[robot]"
            ) from error
        return OperatonContracts
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
