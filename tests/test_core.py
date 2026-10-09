"""Tests for the core API, which must work without Robot Framework.

This module never imports Robot Framework itself, so CI can also run it in an
environment without the ``robot`` extra.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic import Field
from pydantic import ValidationError

import OperatonContracts
from OperatonContracts import TaskContract
from OperatonContracts import load_contract
from OperatonContracts import validate_input
from OperatonContracts import validate_output
from OperatonContracts.checks import MISSING_ROBOT
from OperatonContracts.checks import check_package
from OperatonContracts.contracts import aliases
from OperatonContracts.contracts import import_contracts
from OperatonContracts.templates import TaskTemplate


class OrderInput(TaskContract):
    order_id: str = Field(alias="orderId", title="Order", min_length=1)
    due: date = Field(alias="due", title="Due", strict=False)
    dry_run: bool = Field(alias="dryRun", title="Dry run", default=False)


class OrderOutput(TaskContract):
    status: str = Field(alias="status", title="Status")
    details: dict[str, Any] = Field(alias="details", title="Details")


ORDER = TaskTemplate(
    topic="orders.ship",
    template_id="org.example.orders-ship",
    name="Ship order",
    description="Ships an order.",
    filename="orders-ship.json",
    inputs=OrderInput,
    outputs=OrderOutput,
)


@contextmanager
def without_robot() -> Iterator[None]:
    """Make Robot Framework and the integration module unimportable."""
    with patch.dict(sys.modules):
        sys.modules.pop("OperatonContracts.robotframework", None)
        for name in [name for name in sys.modules if name.split(".")[0] == "robot"]:
            sys.modules[name] = None  # type: ignore[assignment]
        sys.modules["robot"] = None  # type: ignore[assignment]
        yield


class ValidationTests(unittest.TestCase):
    def test_validate_input_reads_only_aliases_and_normalizes(self) -> None:
        self.assertEqual(aliases(OrderInput), ["orderId", "due", "dryRun"])
        self.assertEqual(
            validate_input(
                OrderInput,
                {"orderId": " o-1 ", "due": "2026-01-02", "unrelated": object()},
            ),
            {"orderId": "o-1", "due": "2026-01-02", "dryRun": False},
        )
        with self.assertRaisesRegex(ValidationError, "dryRun"):
            validate_input(
                OrderInput, {"orderId": "o-1", "due": "2026-01-02", "dryRun": "no"}
            )

    def test_validate_output_rejects_unknown_and_missing_values(self) -> None:
        self.assertEqual(
            validate_output(OrderOutput, {"status": "ok", "details": {"n": 1}}),
            {"status": "ok", "details": {"n": 1}},
        )
        for values in ({"status": "ok"}, {"status": "ok", "details": {}, "x": 1}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                validate_output(OrderOutput, values)

    def test_load_contract_requires_a_task_contract(self) -> None:
        module = sys.modules[__name__]
        self.assertIs(load_contract(module, "OrderInput"), OrderInput)
        for name in ("Missing", "ORDER"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "not a TaskContract"):
                    load_contract(module, name)


class ImportContractsTests(unittest.TestCase):
    def test_falls_back_to_given_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "core_fallback_contracts.py").write_text("X = 1\n")
            with patch.object(sys, "path", list(sys.path)):
                module = import_contracts("core_fallback_contracts", [directory])
                self.assertEqual(sys.path[0], directory)
            self.assertEqual(module.X, 1)
            sys.modules.pop("core_fallback_contracts")

    def test_reraises_when_no_fallback_applies(self) -> None:
        with self.assertRaises(ModuleNotFoundError):
            import_contracts("core_missing_contracts")
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "core_broken_contracts.py").write_text(
                "import core_missing_dependency\n"
            )
            with patch.object(sys, "path", [directory, *sys.path]):
                # The fallback directory is already on sys.path.
                with self.assertRaises(ModuleNotFoundError):
                    import_contracts("core_still_missing", [directory])
                # A missing dependency of the contracts module is re-raised.
                with self.assertRaisesRegex(ModuleNotFoundError, "dependency"):
                    import_contracts("core_broken_contracts", [directory])


class WithoutRobotTests(unittest.TestCase):
    def test_core_imports_never_load_robot(self) -> None:
        code = (
            "import sys\n"
            "import OperatonContracts\n"
            "from OperatonContracts import checks, cli, contracts, templates\n"
            "assert not any(m.split('.')[0] == 'robot' for m in sys.modules), "
            "sorted(m for m in sys.modules if m.startswith('robot'))\n"
        )
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_library_export_explains_the_missing_extra(self) -> None:
        with without_robot():
            with self.assertRaisesRegex(ImportError, r"operaton-contracts\[robot\]"):
                OperatonContracts.__getattr__("OperatonContracts")

    def test_library_export_reraises_unrelated_import_errors(self) -> None:
        with patch.dict(sys.modules):
            sys.modules.pop("OperatonContracts.robotframework", None)
            sys.modules["OperatonContracts.robotframework"] = None  # type: ignore[assignment]
            with self.assertRaises(ModuleNotFoundError):
                OperatonContracts.__getattr__("OperatonContracts")

    def test_unknown_attributes_raise_attribute_error(self) -> None:
        with self.assertRaisesRegex(AttributeError, "Nope"):
            OperatonContracts.__getattr__("Nope")

    def test_check_reports_unchecked_suites_without_robot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[tool.purjo.topics."orders.ship"]\n'
                'name = "Ship Order"\n'
                "process-variables = false\n"
            )
            with without_robot():
                self.assertEqual(check_package(root, [ORDER]), [MISSING_ROBOT])
                (root / "pyproject.toml").write_text("")
                self.assertEqual(
                    check_package(root, [ORDER]),
                    ["Topic missing from [tool.purjo.topics]: orders.ship"],
                )


if __name__ == "__main__":
    unittest.main()
