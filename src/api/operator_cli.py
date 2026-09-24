"""Bootstrap-safe parser and output contract for ``backend.exe operator``.

This module intentionally imports only the Python standard library. H4-1A
registers the frozen public grammar but implements no operational commands.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType
from typing import Any, Mapping, Sequence, TextIO


JSON_SCHEMA_VERSION = 1


class OperatorExitCode(IntEnum):
    """Frozen H4 operator exit categories."""

    SUCCESS = 0
    USAGE = 2
    VALIDATION = 3
    STATE = 4
    NOT_FOUND = 5
    INTEGRITY = 6
    PARTIAL_MUTATION = 7
    SUBSYSTEM = 8
    INTERNAL = 9


OPERATOR_USAGE_REQUIRED = "OPERATOR_USAGE_REQUIRED"
OPERATOR_UNKNOWN_NAMESPACE = "OPERATOR_UNKNOWN_NAMESPACE"
OPERATOR_COMMAND_REQUIRED = "OPERATOR_COMMAND_REQUIRED"
OPERATOR_UNKNOWN_COMMAND = "OPERATOR_UNKNOWN_COMMAND"
OPERATOR_INVALID_ARGUMENT = "OPERATOR_INVALID_ARGUMENT"
OPERATOR_COMMAND_NOT_IMPLEMENTED = "OPERATOR_COMMAND_NOT_IMPLEMENTED"


@dataclass(frozen=True)
class OperatorResult:
    """One bounded result suitable for human or JSON rendering."""

    command: str
    status: str
    error_code: str | None
    data: Mapping[str, Any]
    message: str
    exit_code: OperatorExitCode

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        if self.exit_code is OperatorExitCode.SUCCESS and self.error_code is not None:
            raise ValueError("successful operator result cannot have an error code")
        if self.exit_code is not OperatorExitCode.SUCCESS and not self.error_code:
            raise ValueError("failed operator result requires an error code")

    def json_payload(self) -> dict[str, Any]:
        return {
            "schema_version": JSON_SCHEMA_VERSION,
            "command": self.command,
            "status": self.status,
            "error_code": self.error_code,
            "data": dict(self.data),
        }


@dataclass(frozen=True)
class OptionSpec:
    flag: str
    value_name: str
    required: bool = True
    choices: tuple[str, ...] = ()
    ascii_integer: bool = False


@dataclass(frozen=True)
class CommandSpec:
    path: tuple[str, ...]
    usage: str
    options: tuple[OptionSpec, ...] = ()


_COMMAND_SPECS = (
    CommandSpec(("config", "status"), "config status"),
    CommandSpec(
        ("tenant", "provision"),
        "tenant provision --tenant ID --approval-ref REF",
        (
            OptionSpec("--tenant", "ID"),
            OptionSpec("--approval-ref", "REF"),
        ),
    ),
    CommandSpec(
        ("seed", "status"),
        "seed status --tenant ID",
        (OptionSpec("--tenant", "ID"),),
    ),
    CommandSpec(
        ("seed", "apply-safe-off"),
        (
            "seed apply-safe-off --tenant ID --generation G --approval-ref REF "
            "[--lease-profile 180-45|300-60]"
        ),
        (
            OptionSpec("--tenant", "ID"),
            OptionSpec("--generation", "G"),
            OptionSpec("--approval-ref", "REF"),
            OptionSpec(
                "--lease-profile",
                "180-45|300-60",
                required=False,
                choices=("180-45", "300-60"),
            ),
        ),
    ),
    CommandSpec(
        ("seed", "prearm-p3w"),
        (
            "seed prearm-p3w --tenant ID --generation G --backup-bundle PATH "
            "--approval-ref REF"
        ),
        (
            OptionSpec("--tenant", "ID"),
            OptionSpec("--generation", "G"),
            OptionSpec("--backup-bundle", "PATH"),
            OptionSpec("--approval-ref", "REF"),
        ),
    ),
    CommandSpec(
        ("seed", "activate"),
        (
            "seed activate --tenant ID --generation G --backup-bundle PATH "
            "--approval-ref REF"
        ),
        (
            OptionSpec("--tenant", "ID"),
            OptionSpec("--generation", "G"),
            OptionSpec("--backup-bundle", "PATH"),
            OptionSpec("--approval-ref", "REF"),
        ),
    ),
    CommandSpec(
        ("seed", "kill"),
        "seed kill --tenant ID --generation G --reason-code CODE",
        (
            OptionSpec("--tenant", "ID"),
            OptionSpec("--generation", "G"),
            OptionSpec("--reason-code", "CODE"),
        ),
    ),
    CommandSpec(
        ("seed", "set-balanced-bps"),
        (
            "seed set-balanced-bps --tenant ID --generation G --bps N "
            "--backup-bundle PATH --approval-ref REF"
        ),
        (
            OptionSpec("--tenant", "ID"),
            OptionSpec("--generation", "G"),
            OptionSpec("--bps", "N", ascii_integer=True),
            OptionSpec("--backup-bundle", "PATH"),
            OptionSpec("--approval-ref", "REF"),
        ),
    ),
    CommandSpec(
        ("seed", "transition-p3a"),
        (
            "seed transition-p3a --tenant ID --generation G "
            "--rollback-window 7d|24h --backup-bundle PATH --approval-ref REF"
        ),
        (
            OptionSpec("--tenant", "ID"),
            OptionSpec("--generation", "G"),
            OptionSpec(
                "--rollback-window",
                "7d|24h",
                choices=("7d", "24h"),
            ),
            OptionSpec("--backup-bundle", "PATH"),
            OptionSpec("--approval-ref", "REF"),
        ),
    ),
    CommandSpec(("secret", "assignment", "status"), "secret assignment status"),
    CommandSpec(
        ("secret", "assignment", "rotate"),
        (
            "secret assignment rotate --tenant ID --expected-generation G "
            "--new-generation G2 --backup-bundle PATH --approval-ref REF"
        ),
        (
            OptionSpec("--tenant", "ID"),
            OptionSpec("--expected-generation", "G"),
            OptionSpec("--new-generation", "G2"),
            OptionSpec("--backup-bundle", "PATH"),
            OptionSpec("--approval-ref", "REF"),
        ),
    ),
    CommandSpec(
        ("backup", "create"),
        "backup create --tenant ID --destination ABSOLUTE_NEW_DIRECTORY",
        (
            OptionSpec("--tenant", "ID"),
            OptionSpec("--destination", "ABSOLUTE_NEW_DIRECTORY"),
        ),
    ),
    CommandSpec(
        ("backup", "verify"),
        "backup verify --bundle ABSOLUTE_BUNDLE_DIRECTORY",
        (OptionSpec("--bundle", "ABSOLUTE_BUNDLE_DIRECTORY"),),
    ),
)

_COMMAND_BY_PATH = MappingProxyType({spec.path: spec for spec in _COMMAND_SPECS})
_NAMESPACES = tuple(sorted({spec.path[0] for spec in _COMMAND_SPECS}))
_ASCII_INTEGER = re.compile(r"^[0-9]+$")


def operator_success(
    *,
    command: str,
    status: str,
    message: str,
    data: Mapping[str, Any] | None = None,
) -> OperatorResult:
    return OperatorResult(
        command=command,
        status=status,
        error_code=None,
        data={} if data is None else data,
        message=message,
        exit_code=OperatorExitCode.SUCCESS,
    )


def operator_failure(
    *,
    command: str,
    error_code: str,
    message: str,
    exit_code: OperatorExitCode,
    data: Mapping[str, Any] | None = None,
) -> OperatorResult:
    if exit_code is OperatorExitCode.SUCCESS:
        raise ValueError("operator failure cannot use success exit code")
    return OperatorResult(
        command=command,
        status="ERROR",
        error_code=error_code,
        data={} if data is None else data,
        message=message,
        exit_code=exit_code,
    )


def emit_operator_result(
    result: OperatorResult,
    *,
    json_mode: bool,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Emit exactly one bounded result and return its frozen exit category."""
    output = sys.stdout if stdout is None else stdout
    error = sys.stderr if stderr is None else stderr
    if json_mode:
        serialized = json.dumps(
            result.json_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        output.write(serialized + "\n")
    elif result.exit_code is OperatorExitCode.SUCCESS:
        output.write(result.message.rstrip("\n") + "\n")
    else:
        error.write(f"{result.error_code}: {result.message.rstrip()}\n")
    return int(result.exit_code)


def _top_level_help() -> OperatorResult:
    commands = tuple(" ".join(spec.path) for spec in _COMMAND_SPECS)
    message = "\n".join(
        (
            "Usage: backend.exe operator [--json] <namespace> <command> [arguments]",
            "Commands:",
            *(f"  {command}" for command in commands),
        )
    )
    return operator_success(
        command="operator",
        status="HELP",
        message=message,
        data={
            "usage": "backend.exe operator [--json] <namespace> <command> [arguments]",
            "commands": commands,
        },
    )


def _namespace_help(namespace: str, *, group: str | None = None) -> OperatorResult:
    prefix = (namespace,) if group is None else (namespace, group)
    commands = tuple(
        " ".join(spec.path)
        for spec in _COMMAND_SPECS
        if spec.path[: len(prefix)] == prefix
    )
    command_name = " ".join(prefix)
    message = "\n".join(
        (
            f"Usage: backend.exe operator [--json] {command_name} <command> [arguments]",
            "Commands:",
            *(f"  {command}" for command in commands),
        )
    )
    return operator_success(
        command=command_name,
        status="HELP",
        message=message,
        data={"namespace": command_name, "commands": commands},
    )


def _command_help(spec: CommandSpec) -> OperatorResult:
    command = " ".join(spec.path)
    usage = f"backend.exe operator [--json] {spec.usage}"
    return operator_success(
        command=command,
        status="HELP",
        message=f"Usage: {usage}",
        data={"usage": usage},
    )


def _usage_failure(error_code: str, message: str, *, command: str = "operator") -> OperatorResult:
    return operator_failure(
        command=command,
        error_code=error_code,
        message=message,
        exit_code=OperatorExitCode.USAGE,
    )


def _match_command(arguments: tuple[str, ...]) -> tuple[CommandSpec | None, int]:
    for path in sorted(_COMMAND_BY_PATH, key=len, reverse=True):
        if arguments[: len(path)] == path:
            return _COMMAND_BY_PATH[path], len(path)
    return None, 0


def _validate_options(spec: CommandSpec, arguments: tuple[str, ...]) -> str | None:
    option_by_flag = {option.flag: option for option in spec.options}
    provided: set[str] = set()
    index = 0
    while index < len(arguments):
        flag = arguments[index]
        option = option_by_flag.get(flag)
        if option is None:
            return f"unsupported argument for {' '.join(spec.path)}: {flag}"
        if flag in provided:
            return f"duplicate argument for {' '.join(spec.path)}: {flag}"
        if index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
            return f"missing value for {flag}"
        value = arguments[index + 1]
        if option.choices and value not in option.choices:
            return f"invalid value for {flag}"
        if option.ascii_integer and _ASCII_INTEGER.fullmatch(value) is None:
            return f"invalid integer for {flag}"
        provided.add(flag)
        index += 2

    missing = tuple(option.flag for option in spec.options if option.required and option.flag not in provided)
    if missing:
        return "missing required argument(s): " + ", ".join(missing)
    return None


def parse_operator_arguments(argv: Sequence[str]) -> tuple[OperatorResult, bool]:
    """Parse the frozen grammar without resolving paths or touching runtime state."""
    arguments = tuple(argv)
    json_mode = bool(arguments and arguments[0] == "--json")
    if json_mode:
        arguments = arguments[1:]

    if "--json" in arguments:
        return (
            _usage_failure(
                OPERATOR_INVALID_ARGUMENT,
                "--json must appear immediately after operator",
            ),
            True,
        )

    if arguments == ("--help",):
        return _top_level_help(), json_mode
    if not arguments:
        return (
            _usage_failure(
                OPERATOR_USAGE_REQUIRED,
                "a namespace and command are required; use operator --help",
            ),
            json_mode,
        )

    namespace = arguments[0]
    if namespace not in _NAMESPACES:
        return (
            _usage_failure(
                OPERATOR_UNKNOWN_NAMESPACE,
                f"unknown namespace: {namespace}",
            ),
            json_mode,
        )

    if arguments == (namespace, "--help"):
        return _namespace_help(namespace), json_mode
    if arguments == ("secret", "assignment", "--help"):
        return _namespace_help("secret", group="assignment"), json_mode
    if len(arguments) == 1 or arguments == ("secret", "assignment"):
        return (
            _usage_failure(
                OPERATOR_COMMAND_REQUIRED,
                f"a command is required for namespace: {' '.join(arguments)}",
                command=" ".join(arguments),
            ),
            json_mode,
        )

    spec, consumed = _match_command(arguments)
    if spec is None:
        return (
            _usage_failure(
                OPERATOR_UNKNOWN_COMMAND,
                f"unknown command in namespace {namespace}",
                command=namespace,
            ),
            json_mode,
        )

    remaining = arguments[consumed:]
    if remaining == ("--help",):
        return _command_help(spec), json_mode
    if "--help" in remaining:
        return (
            _usage_failure(
                OPERATOR_INVALID_ARGUMENT,
                "--help must be the only argument after a valid command",
                command=" ".join(spec.path),
            ),
            json_mode,
        )

    invalid = _validate_options(spec, remaining)
    if invalid is not None:
        return (
            _usage_failure(
                OPERATOR_INVALID_ARGUMENT,
                invalid,
                command=" ".join(spec.path),
            ),
            json_mode,
        )

    command = " ".join(spec.path)
    values = {
        remaining[index]: remaining[index + 1]
        for index in range(0, len(remaining), 2)
    }
    if spec.path in {
        ("config", "status"),
        ("seed", "status"),
        ("secret", "assignment", "status"),
    }:
        from .operator_status import observe_operator_status

        outcome = observe_operator_status(
            spec.path,
            tenant_id=values.get("--tenant"),
        )
        if outcome.error_code is None:
            return (
                operator_success(
                    command=command,
                    status=outcome.status,
                    message=outcome.message,
                    data=outcome.data,
                ),
                json_mode,
            )
        return (
            operator_failure(
                command=command,
                error_code=outcome.error_code,
                message=outcome.message,
                exit_code=OperatorExitCode(outcome.exit_code),
                data=outcome.data,
            ),
            json_mode,
        )
    if spec.path == ("tenant", "provision"):
        from .operator_tenant_provision import provision_tenant

        outcome = provision_tenant(
            values["--tenant"],
            values["--approval-ref"],
        )
        if outcome.error_code is None:
            return (
                operator_success(
                    command=command,
                    status=outcome.status,
                    message=outcome.message,
                    data=outcome.data,
                ),
                json_mode,
            )
        return (
            operator_failure(
                command=command,
                error_code=outcome.error_code,
                message=outcome.message,
                exit_code=OperatorExitCode(outcome.exit_code),
                data=outcome.data,
            ),
            json_mode,
        )
    if spec.path == ("secret", "assignment", "rotate"):
        from .operator_secret import rotate_assignment_secret

        outcome = rotate_assignment_secret(
            values["--tenant"],
            values["--expected-generation"],
            values["--new-generation"],
            values["--backup-bundle"],
            values["--approval-ref"],
        )
        if outcome.error_code is None:
            return (
                operator_success(
                    command=command,
                    status=outcome.status,
                    message=outcome.message,
                    data=outcome.data,
                ),
                json_mode,
            )
        return (
            operator_failure(
                command=command,
                error_code=outcome.error_code,
                message=outcome.message,
                exit_code=OperatorExitCode(outcome.exit_code),
                data=outcome.data,
            ),
            json_mode,
        )
    if spec.path in {("backup", "create"), ("backup", "verify")}:
        from .operator_backup import create_operator_backup, verify_operator_backup

        if spec.path == ("backup", "create"):
            outcome = create_operator_backup(
                values["--tenant"],
                values["--destination"],
            )
        else:
            outcome = verify_operator_backup(values["--bundle"])
        if outcome.error_code is None:
            return (
                operator_success(
                    command=command,
                    status=outcome.status,
                    message=outcome.message,
                    data=outcome.data,
                ),
                json_mode,
            )
        return (
            operator_failure(
                command=command,
                error_code=outcome.error_code,
                message=outcome.message,
                exit_code=OperatorExitCode(outcome.exit_code),
                data=outcome.data,
            ),
            json_mode,
        )
    if spec.path in {
        ("seed", "apply-safe-off"),
        ("seed", "prearm-p3w"),
        ("seed", "activate"),
        ("seed", "kill"),
        ("seed", "set-balanced-bps"),
        ("seed", "transition-p3a"),
    }:
        from .operator_seed import execute_seed_transition

        outcome = execute_seed_transition(
            spec.path[1],
            values["--tenant"],
            values["--generation"],
            approval_ref=values.get("--approval-ref"),
            reason_code=values.get("--reason-code"),
            lease_profile=values.get("--lease-profile"),
            balanced_basis_points=(
                int(values["--bps"]) if "--bps" in values else None
            ),
            rollback_window=values.get("--rollback-window"),
            backup_bundle=values.get("--backup-bundle"),
        )
        if outcome.error_code is None:
            return (
                operator_success(
                    command=command,
                    status=outcome.status,
                    message=outcome.message,
                    data=outcome.data,
                ),
                json_mode,
            )
        return (
            operator_failure(
                command=command,
                error_code=outcome.error_code,
                message=outcome.message,
                exit_code=OperatorExitCode(outcome.exit_code),
                data=outcome.data,
            ),
            json_mode,
        )
    return (
        operator_failure(
            command=command,
            error_code=OPERATOR_COMMAND_NOT_IMPLEMENTED,
            message=f"{command} is registered but not implemented in H4-1A",
            exit_code=OperatorExitCode.STATE,
        ),
        json_mode,
    )


def run_operator_cli(
    argv: Sequence[str],
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse, emit one result, and return its stable process exit code."""
    result, json_mode = parse_operator_arguments(argv)
    return emit_operator_result(
        result,
        json_mode=json_mode,
        stdout=stdout,
        stderr=stderr,
    )
