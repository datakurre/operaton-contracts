"""Tests for the core API, which must work without Robot Framework.

This module never imports Robot Framework itself, so CI can also run it in an
environment without the ``robot`` extra.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from contextlib import redirect_stderr
from contextlib import redirect_stdout
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
from OperatonContracts import cli
from OperatonContracts import skills
from OperatonContracts.contracts import aliases
from OperatonContracts.skills import SKILL_NAME
from OperatonContracts.skills import packaged_skill
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

    def test_tries_each_fallback_directory_in_turn(self) -> None:
        with (
            tempfile.TemporaryDirectory() as empty,
            tempfile.TemporaryDirectory() as found,
        ):
            (Path(found) / "core_second_contracts.py").write_text("X = 2\n")
            with patch.object(sys, "path", list(sys.path)):
                module = import_contracts("core_second_contracts", [empty, found])
                self.assertNotIn(empty, sys.path)
                self.assertEqual(sys.path[0], found)
            self.assertEqual(module.X, 2)
            sys.modules.pop("core_second_contracts")
            (Path(empty) / "core_third_contracts.py").write_text(
                "import core_third_missing_dependency\n"
            )
            with patch.object(sys, "path", list(sys.path)):
                with self.assertRaisesRegex(ModuleNotFoundError, "dependency"):
                    import_contracts("core_third_contracts", [found, empty])

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


class SkillInstallTests(unittest.TestCase):
    def test_packaged_skill_has_its_entry_point_and_references(self) -> None:
        skill = packaged_skill()
        self.assertIn(f"name: {SKILL_NAME}", skill["SKILL.md"].decode())
        self.assertIn("reference/testing.md", skill)
        self.assertIn("assets/OperatonTasks.py.tmpl", skill)
        self.assertFalse(any("__pycache__" in path for path in skill))

    def test_install_update_and_refuse_local_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / ".agents" / "skills" / SKILL_NAME

            def run(*arguments: str) -> tuple[int, str, str]:
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    status = cli.main(
                        ["install-skill", "--root", directory, *arguments]
                    )
                return status, stdout.getvalue(), stderr.getvalue()

            self.assertEqual(run()[:2], (0, f"Installed {installed}\n"))
            self.assertEqual(
                (installed / "SKILL.md").read_bytes(), packaged_skill()["SKILL.md"]
            )
            self.assertEqual(run()[:2], (0, f"{installed} is up to date\n"))

            (installed / "SKILL.md").write_text("edited\n")
            (installed / "stray.md").write_text("stray\n")
            status, _stdout, stderr = run()
            self.assertEqual(status, 1)
            self.assertIn("--force", stderr)
            self.assertEqual((installed / "SKILL.md").read_text(), "edited\n")

            self.assertEqual(run("--force")[:2], (0, f"Updated {installed}\n"))
            self.assertFalse((installed / "stray.md").exists())
            self.assertEqual(
                (installed / "SKILL.md").read_bytes(), packaged_skill()["SKILL.md"]
            )

    def test_claude_link_follows_flags_and_auto_detection(self) -> None:
        cases: tuple[tuple[list[str], bool, bool], ...] = (
            ([], False, False),
            ([], True, True),
            (["--claude"], False, True),
            (["--no-claude"], True, False),
        )
        for arguments, has_claude, linked in cases:
            with self.subTest(arguments=arguments, has_claude=has_claude):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    if has_claude:
                        (root / ".claude").mkdir()
                    with redirect_stdout(io.StringIO()):
                        status = cli.main(
                            ["install-skill", "--root", directory, *arguments]
                        )
                    self.assertEqual(status, 0)
                    link = root / ".claude" / "skills" / SKILL_NAME
                    self.assertEqual(link.is_symlink(), linked)
                    if linked:
                        self.assertEqual(
                            os.readlink(link),
                            os.path.join("..", "..", ".agents", "skills", SKILL_NAME),
                        )
                        self.assertTrue((link / "SKILL.md").exists())

    def test_claude_link_is_idempotent_and_replaced_only_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            link = root / ".claude" / "skills" / SKILL_NAME

            def run(*arguments: str) -> tuple[int, str, str]:
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    status = cli.main(
                        ["install-skill", "--root", directory, "--claude", *arguments]
                    )
                return status, stdout.getvalue(), stderr.getvalue()

            status, stdout, _stderr = run()
            self.assertEqual(status, 0)
            self.assertIn(f"Linked {link} -> ", stdout)
            self.assertIn(f"{link} is up to date", run()[1])

            for replace in ("symlink", "directory"):
                with self.subTest(replace=replace):
                    link.unlink() if link.is_symlink() else shutil.rmtree(link)
                    if replace == "symlink":
                        link.symlink_to(root, target_is_directory=True)
                    else:
                        link.mkdir()
                        (link / "SKILL.md").write_text("old copy\n")
                    status, _stdout, stderr = run()
                    self.assertEqual(status, 1)
                    self.assertIn("--force", stderr)
                    self.assertEqual(run("--force")[0], 0)
                    self.assertTrue(link.is_symlink())
                    self.assertEqual(
                        (link / "SKILL.md").read_bytes(), packaged_skill()["SKILL.md"]
                    )

    def test_linked_skills_directory_is_never_destroyed(self) -> None:
        # .claude/skills is itself a link to .agents/skills: the skill is
        # already visible there, and --force must not delete it.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".agents" / "skills").mkdir(parents=True)
            (root / ".claude").mkdir()
            (root / ".claude" / "skills").symlink_to(
                Path("..") / ".agents" / "skills", target_is_directory=True
            )
            for arguments in ([], ["--force"]):
                with redirect_stdout(io.StringIO()) as stdout:
                    status = cli.main(
                        ["install-skill", "--root", directory, *arguments]
                    )
                self.assertEqual(status, 0)
                self.assertIn("is up to date", stdout.getvalue().splitlines()[-1])
            installed = root / ".agents" / "skills" / SKILL_NAME
            self.assertFalse(installed.is_symlink())
            self.assertTrue((installed / "SKILL.md").is_file())

    def test_destination_link_or_file_is_replaced_only_with_force(self) -> None:
        for kind in ("symlink", "file"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                skills_dir = Path(directory) / "skills"
                skills_dir.mkdir()
                destination = skills_dir / SKILL_NAME
                elsewhere = Path(directory) / "elsewhere"
                elsewhere.mkdir()
                (elsewhere / "keep.md").write_text("keep")
                if kind == "symlink":
                    destination.symlink_to(elsewhere, target_is_directory=True)
                else:
                    destination.write_text("not a directory")
                with self.assertRaisesRegex(skills.SkillError, "--force"):
                    skills.install_skill(skills_dir)
                self.assertEqual(
                    skills.install_skill(skills_dir, force=True),
                    f"Updated {destination}",
                )
                self.assertFalse(destination.is_symlink())
                self.assertTrue((destination / "SKILL.md").is_file())
                # A replaced link's target is left untouched.
                self.assertEqual((elsewhere / "keep.md").read_text(), "keep")

    def test_filesystem_errors_become_skill_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "blocker"
            blocker.write_text("a file where a directory should be")
            with self.assertRaisesRegex(skills.SkillError, "Cannot install"):
                skills.install_skill(blocker)
            installed_root = Path(directory) / "agents"
            skills.install_skill(installed_root)
            with self.assertRaisesRegex(skills.SkillError, "Cannot link"):
                skills.link_skill(blocker / "skills", installed_root)

    def test_link_falls_back_to_copying_without_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skills.install_skill(root / "agents")
            with patch.object(Path, "symlink_to", side_effect=OSError("no symlinks")):
                message = skills.link_skill(root / "claude", root / "agents")
            self.assertIn("symbolic links are unavailable", message)
            copied = root / "claude" / SKILL_NAME
            self.assertFalse(copied.is_symlink())
            self.assertEqual(skills._read(copied), packaged_skill())

    def test_reading_skips_bytecode_caches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "x.pyc").write_bytes(b"")
            (root / "sub").mkdir()
            (root / "sub" / "a.md").write_text("a")
            self.assertEqual(skills._read(root), {"sub/a.md": b"a"})

    def test_custom_skills_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            status = cli.main(
                ["install-skill", "--root", directory, "--skills-dir", "skills"]
            )
            self.assertEqual(status, 0)
            self.assertTrue(
                (Path(directory) / "skills" / SKILL_NAME / "SKILL.md").exists()
            )


if __name__ == "__main__":
    unittest.main()
