from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.api.bootstrap import is_operator_invocation, prepare_bootstrap
from src.api.operator_cli import (
    JSON_SCHEMA_VERSION,
    OPERATOR_COMMAND_NOT_IMPLEMENTED,
    OPERATOR_INVALID_ARGUMENT,
    OPERATOR_UNKNOWN_COMMAND,
    OPERATOR_UNKNOWN_NAMESPACE,
    OPERATOR_USAGE_REQUIRED,
    OperatorExitCode,
    emit_operator_result,
    operator_failure,
    operator_success,
    run_operator_cli,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = REPOSITORY_ROOT / "main.py"


def _safe_subprocess_environment(temp_root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not (
            key.startswith("RESERVATION_")
            or key.endswith("_SECRET")
            or key.endswith("_TOKEN")
            or key.endswith("_API_KEY")
        )
    }
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    environment["LOCALAPPDATA"] = str(temp_root / "local-app-data")
    environment["APPDATA"] = str(temp_root / "roaming-app-data")
    return environment


def _run_main_operator(arguments: tuple[str, ...], temp_root: Path) -> subprocess.CompletedProcess[str]:
    runtime_root = temp_root / "operator-must-not-create"
    code = textwrap.dedent(
        f"""
        import appdirs
        import json
        import runpy
        import sys
        from pathlib import Path
        from unittest.mock import patch

        target = Path({str(runtime_root)!r})
        appdirs.user_data_dir = lambda *args, **kwargs: str(target)
        sys.frozen = True
        sys.argv = [{str(MAIN_PATH)!r}, 'operator', *{arguments!r}]
        exit_code = None
        with patch(
            'src.api.bootstrap.initialize_runtime_paths',
            side_effect=AssertionError('operator path reached RuntimePaths initialization'),
        ):
            try:
                runpy.run_path({str(MAIN_PATH)!r}, run_name='__main__')
            except SystemExit as exc:
                exit_code = exc.code
        print('H4_1A_PROBE=' + json.dumps({{
            'exit_code': exit_code,
            'runtime_root_exists': target.exists(),
            'fastapi_imported': 'fastapi' in sys.modules,
            'database_imported': 'src.api.database' in sys.modules,
            'routes_imported': 'src.api.routes_dsl' in sys.modules,
            'uvicorn_imported': 'uvicorn' in sys.modules,
        }}, sort_keys=True))
        """
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPOSITORY_ROOT,
        env=_safe_subprocess_environment(temp_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def _probe_payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    marker = "H4_1A_PROBE="
    line = next(line for line in result.stdout.splitlines() if line.startswith(marker))
    return json.loads(line[len(marker) :])


class EarlyOperatorDispatchTests(unittest.TestCase):
    def test_operator_recognition_is_pure_and_normal_mode_is_preserved(self):
        self.assertTrue(is_operator_invocation(["backend.exe", "operator", "--help"]))
        self.assertFalse(is_operator_invocation(["backend.exe"]))
        self.assertFalse(is_operator_invocation(["backend.exe", "Operator"]))

        paths = SimpleNamespace(mode="test")
        with patch("src.api.bootstrap.initialize_runtime_paths", return_value=paths) as initialize:
            decision = prepare_bootstrap(["backend.exe"])
        initialize.assert_called_once_with()
        self.assertIs(decision.runtime_paths, paths)
        self.assertFalse(decision.operator_requested)

    def test_main_operator_help_precedes_runtime_paths_and_application_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _run_main_operator(("--help",), Path(directory))
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = _probe_payload(result)
        self.assertEqual(observed["exit_code"], 0)
        self.assertFalse(observed["runtime_root_exists"])
        self.assertFalse(observed["fastapi_imported"])
        self.assertFalse(observed["database_imported"])
        self.assertFalse(observed["routes_imported"])
        self.assertFalse(observed["uvicorn_imported"])
        self.assertEqual(result.stderr, "")
        self.assertIn("Usage: backend.exe operator", result.stdout)

    def test_help_usage_and_invalid_entrypoint_paths_leave_runtime_root_absent(self):
        cases = (
            (("--help",), 0),
            ((), 2),
            (("unknown", "command"), 2),
            (("--json", "unknown", "command"), 2),
            (("config", "unknown"), 2),
            (("config", "status", "extra"), 2),
            (("--json", "config", "status", "extra"), 2),
        )
        for arguments, expected_exit in cases:
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / "operator-must-not-create"
                self.assertFalse(target.exists())
                result = _run_main_operator(arguments, root)
                observed = _probe_payload(result)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(observed["exit_code"], expected_exit)
                self.assertFalse(observed["runtime_root_exists"])
                self.assertFalse(target.exists())
                self.assertEqual(list(root.rglob("*.db")), [])


class OperatorParserTests(unittest.TestCase):
    _COMMANDS = (
        ("config", "status"),
        ("tenant", "provision"),
        ("seed", "status"),
        ("seed", "apply-safe-off"),
        ("seed", "prearm-p3w"),
        ("seed", "activate"),
        ("seed", "kill"),
        ("seed", "set-balanced-bps"),
        ("seed", "transition-p3a"),
        ("secret", "assignment", "status"),
        ("secret", "assignment", "rotate"),
        ("backup", "create"),
        ("backup", "verify"),
    )

    def _invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = run_operator_cli(arguments, stdout=stdout, stderr=stderr)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_bare_operator_is_human_usage_failure_on_stderr_only(self):
        exit_code, stdout, stderr = self._invoke()
        self.assertEqual(exit_code, OperatorExitCode.USAGE)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr,
            f"{OPERATOR_USAGE_REQUIRED}: a namespace and command are required; use operator --help\n",
        )

    def test_all_frozen_help_forms_are_successful_and_deterministic(self):
        forms = [("--help",)]
        forms.extend((namespace, "--help") for namespace in ("backup", "config", "secret", "seed", "tenant"))
        forms.append(("secret", "assignment", "--help"))
        forms.extend((*command, "--help") for command in self._COMMANDS)
        for arguments in forms:
            with self.subTest(arguments=arguments):
                first = self._invoke(*arguments)
                second = self._invoke(*arguments)
                self.assertEqual(first, second)
                self.assertEqual(first[0], OperatorExitCode.SUCCESS)
                self.assertTrue(first[1].startswith("Usage:"))
                self.assertEqual(first[2], "")

    def test_global_json_help_is_exactly_one_object_on_stdout(self):
        exit_code, stdout, stderr = self._invoke("--json", "--help")
        self.assertEqual(exit_code, OperatorExitCode.SUCCESS)
        self.assertEqual(stderr, "")
        self.assertEqual(len(stdout.splitlines()), 1)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["command"], "operator")
        self.assertEqual(payload["status"], "HELP")
        self.assertIsNone(payload["error_code"])

    def test_misplaced_json_is_rejected_but_rendered_as_one_json_failure(self):
        exit_code, stdout, stderr = self._invoke("config", "--json", "status")
        self.assertEqual(exit_code, OperatorExitCode.USAGE)
        self.assertEqual(stderr, "")
        self.assertEqual(len(stdout.splitlines()), 1)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], JSON_SCHEMA_VERSION)
        self.assertEqual(payload["error_code"], OPERATOR_INVALID_ARGUMENT)

    def test_unknown_namespace_human_and_json_contracts(self):
        exit_code, stdout, stderr = self._invoke("unknown", "command")
        self.assertEqual(exit_code, OperatorExitCode.USAGE)
        self.assertEqual(stdout, "")
        self.assertTrue(stderr.startswith(f"{OPERATOR_UNKNOWN_NAMESPACE}:"))

        exit_code, stdout, stderr = self._invoke("--json", "unknown", "command")
        self.assertEqual(exit_code, OperatorExitCode.USAGE)
        self.assertEqual(stderr, "")
        self.assertEqual(len(stdout.splitlines()), 1)
        self.assertEqual(json.loads(stdout)["error_code"], OPERATOR_UNKNOWN_NAMESPACE)

    def test_unknown_command_and_invalid_arguments_are_stable_usage_failures(self):
        exit_code, stdout, stderr = self._invoke("config", "unknown")
        self.assertEqual(exit_code, OperatorExitCode.USAGE)
        self.assertEqual(stdout, "")
        self.assertTrue(stderr.startswith(f"{OPERATOR_UNKNOWN_COMMAND}:"))

        exit_code, stdout, stderr = self._invoke("--json", "config", "unknown")
        self.assertEqual(exit_code, OperatorExitCode.USAGE)
        self.assertEqual(stderr, "")
        self.assertEqual(len(stdout.splitlines()), 1)
        self.assertEqual(json.loads(stdout)["error_code"], OPERATOR_UNKNOWN_COMMAND)

        invalid_cases = (
            ("config", "status", "extra"),
            ("tenant", "provision", "--tenant", "ph-elv-0001"),
            ("seed", "set-balanced-bps", "--bps", "not-an-integer"),
            ("seed", "apply-safe-off", "--lease-profile", "180/45"),
            ("backup", "verify", "--bundle"),
            ("tenant", "provision", "--tenant-code", "elv0001"),
            ("seed", "activate", "--verified-backup", "yes"),
            ("config", "status", "--force", "true"),
        )
        for arguments in invalid_cases:
            with self.subTest(arguments=arguments):
                code, out, err = self._invoke(*arguments)
                self.assertEqual(code, OperatorExitCode.USAGE)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith(f"{OPERATOR_INVALID_ARGUMENT}:"))

    def test_every_later_command_grammar_reaches_only_the_placeholder(self):
        commands = (
            ("tenant", "provision", "--tenant", "ph-elv-0001", "--approval-ref", "A-1"),
            (
                "seed", "apply-safe-off", "--tenant", "ph-elv-0001",
                "--generation", "phseed-elv0001-bal-20260921-r1",
                "--approval-ref", "A-1", "--lease-profile", "180-45",
            ),
            (
                "seed", "prearm-p3w", "--tenant", "ph-elv-0001",
                "--generation", "phseed-elv0001-bal-20260921-r1",
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
            (
                "seed", "activate", "--tenant", "ph-elv-0001",
                "--generation", "phseed-elv0001-bal-20260921-r1",
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
            (
                "seed", "kill", "--tenant", "ph-elv-0001",
                "--generation", "phseed-elv0001-bal-20260921-r1",
                "--reason-code", "INCIDENT",
            ),
            (
                "seed", "set-balanced-bps", "--tenant", "ph-elv-0001",
                "--generation", "phseed-elv0001-bal-20260921-r1", "--bps", "3000",
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
            (
                "seed", "transition-p3a", "--tenant", "ph-elv-0001",
                "--generation", "phseed-elv0001-bal-20260921-r1",
                "--rollback-window", "7d", "--backup-bundle", "X:/backup",
                "--approval-ref", "A-1",
            ),
            (
                "secret", "assignment", "rotate", "--tenant", "ph-elv-0001",
                "--expected-generation", "phseed-elv0001-bal-20260921-r1",
                "--new-generation", "phseed-elv0001-bal-20260921-r2",
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
            (
                "backup", "create", "--tenant", "ph-elv-0001",
                "--destination", "X:/new-backup",
            ),
            ("backup", "verify", "--bundle", "X:/backup"),
        )
        for arguments in commands:
            with self.subTest(arguments=arguments):
                code, stdout, stderr = self._invoke(*arguments)
                self.assertEqual(code, OperatorExitCode.STATE)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith(f"{OPERATOR_COMMAND_NOT_IMPLEMENTED}:"))

    def test_registered_future_command_reaches_only_h4_1a_placeholder(self):
        exit_code, stdout, stderr = self._invoke("backup", "verify", "--bundle", "X:/backup")
        self.assertEqual(exit_code, OperatorExitCode.STATE)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr,
            f"{OPERATOR_COMMAND_NOT_IMPLEMENTED}: backup verify is registered but not implemented in H4-1A\n",
        )


class OperatorOutputContractTests(unittest.TestCase):
    def test_human_success_and_failure_use_exactly_one_stream(self):
        success = operator_success(
            command="operator-test",
            status="OK",
            message="completed",
            data={"safe": True},
        )
        failure = operator_failure(
            command="operator-test",
            error_code="OPERATOR_TEST_FAILURE",
            message="failed safely",
            exit_code=OperatorExitCode.VALIDATION,
        )

        stdout = io.StringIO()
        stderr = io.StringIO()
        self.assertEqual(
            emit_operator_result(success, json_mode=False, stdout=stdout, stderr=stderr),
            OperatorExitCode.SUCCESS,
        )
        self.assertEqual(stdout.getvalue(), "completed\n")
        self.assertEqual(stderr.getvalue(), "")

        stdout = io.StringIO()
        stderr = io.StringIO()
        self.assertEqual(
            emit_operator_result(failure, json_mode=False, stdout=stdout, stderr=stderr),
            OperatorExitCode.VALIDATION,
        )
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "OPERATOR_TEST_FAILURE: failed safely\n")

    def test_json_success_and_failure_are_one_object_on_stdout(self):
        results = (
            operator_success(
                command="operator-test",
                status="OK",
                message="completed",
                data={"safe": True},
            ),
            operator_failure(
                command="operator-test",
                error_code="OPERATOR_TEST_FAILURE",
                message="failed safely",
                exit_code=OperatorExitCode.SUBSYSTEM,
            ),
        )
        for result in results:
            with self.subTest(status=result.status):
                stdout = io.StringIO()
                stderr = io.StringIO()
                exit_code = emit_operator_result(
                    result,
                    json_mode=True,
                    stdout=stdout,
                    stderr=stderr,
                )
                self.assertEqual(exit_code, result.exit_code)
                self.assertEqual(stderr.getvalue(), "")
                self.assertEqual(len(stdout.getvalue().splitlines()), 1)
                self.assertEqual(
                    set(json.loads(stdout.getvalue())),
                    {"schema_version", "command", "status", "error_code", "data"},
                )

    def test_frozen_exit_categories_are_exact(self):
        self.assertEqual(
            {member.name: int(member) for member in OperatorExitCode},
            {
                "SUCCESS": 0,
                "USAGE": 2,
                "VALIDATION": 3,
                "STATE": 4,
                "NOT_FOUND": 5,
                "INTEGRITY": 6,
                "PARTIAL_MUTATION": 7,
                "SUBSYSTEM": 8,
                "INTERNAL": 9,
            },
        )


if __name__ == "__main__":
    unittest.main()
