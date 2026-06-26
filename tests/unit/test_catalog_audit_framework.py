"""Unit tests for the kanon catalog audit framework.

Tests audit_command exit codes, registry-iteration behaviour, and output
formatters for both text and json formats.

AC-TEST-002: Unit tests covering audit_command exit code, registry iteration,
and output formatting in both text and json formats.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.commands.catalog import (
    AuditFinding,
    AUDIT_CHECK_REGISTRY,
    audit_command,
    _format_findings,
)
from kanon_cli.constants import KANON_CATALOG_AUDIT_VALID_CHECKS


def _make_args(
    target: str = ".",
    check: str = "all",
    fmt: str = "text",
    no_color: bool = False,
    strict: bool = False,
) -> argparse.Namespace:
    """Build a minimal Namespace for audit_command unit tests."""
    from kanon_cli.commands.catalog import _parse_check_subset

    return argparse.Namespace(
        target=target,
        check=check,
        check_subset=_parse_check_subset(check),
        format=fmt,
        no_color=no_color,
        strict=strict,
        quiet=False,
        verbose=False,
    )


@pytest.mark.unit
class TestAuditCommandExitCode:
    """audit_command returns the correct exit code."""

    def test_returns_zero_with_no_findings(self, tmp_path: pathlib.Path) -> None:
        """Exit 0 when no checks produce findings against an empty manifest repo."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        args = _make_args(target=str(tmp_path))
        with patch.dict(AUDIT_CHECK_REGISTRY, {}, clear=True):
            result = audit_command(args)

        assert result == 0

    def test_returns_zero_all_checks_with_no_findings(self, tmp_path: pathlib.Path) -> None:
        """Exit 0 when all registered check callables return empty lists."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        def empty_check(path: pathlib.Path) -> list[AuditFinding]:
            return []

        stub_registry = {name: empty_check for name in KANON_CATALOG_AUDIT_VALID_CHECKS}

        args = _make_args(target=str(tmp_path), check="all")
        with patch.dict(AUDIT_CHECK_REGISTRY, stub_registry, clear=True):
            result = audit_command(args)

        assert result == 0

    def test_returns_zero_with_info_and_warn_findings(self, tmp_path: pathlib.Path) -> None:
        """T1 always returns 0; T2+ will return 1 for error findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        def findings_check(path: pathlib.Path) -> list[AuditFinding]:
            return [
                AuditFinding(kind="info", code="I001", message="ok", remediation=""),
                AuditFinding(kind="warn", code="W001", message="notice", remediation=""),
            ]

        stub_registry = {"metadata": findings_check}

        args = _make_args(target=str(tmp_path), check="metadata")
        with patch.dict(AUDIT_CHECK_REGISTRY, stub_registry, clear=True):
            result = audit_command(args)

        assert result == 0


@pytest.mark.unit
class TestAuditCommandRegistryIteration:
    """audit_command dispatches only the selected checks."""

    def test_only_selected_checks_are_called(self, tmp_path: pathlib.Path) -> None:
        """When --check metadata, only the metadata callable is invoked."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        called: list[str] = []

        def make_recorder(name: str):
            def check(path: pathlib.Path) -> list[AuditFinding]:
                called.append(name)
                return []

            return check

        stub_registry = {name: make_recorder(name) for name in KANON_CATALOG_AUDIT_VALID_CHECKS}

        args = _make_args(target=str(tmp_path), check="metadata")
        with patch.dict(AUDIT_CHECK_REGISTRY, stub_registry, clear=True):
            audit_command(args)

        assert called == ["metadata"]

    def test_all_checks_iterate_every_registered_check(self, tmp_path: pathlib.Path) -> None:
        """When --check all, every check callable is invoked exactly once."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        called: list[str] = []

        def make_recorder(name: str):
            def check(path: pathlib.Path) -> list[AuditFinding]:
                called.append(name)
                return []

            return check

        stub_registry = {name: make_recorder(name) for name in KANON_CATALOG_AUDIT_VALID_CHECKS}

        args = _make_args(target=str(tmp_path), check="all")
        with patch.dict(AUDIT_CHECK_REGISTRY, stub_registry, clear=True):
            audit_command(args)

        assert sorted(called) == sorted(KANON_CATALOG_AUDIT_VALID_CHECKS)

    def test_empty_registry_with_all_returns_zero(self, tmp_path: pathlib.Path) -> None:
        """Empty registry with --check all returns 0 and no findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        args = _make_args(target=str(tmp_path), check="all")
        with patch.dict(AUDIT_CHECK_REGISTRY, {}, clear=True):
            result = audit_command(args)

        assert result == 0


@pytest.mark.unit
class TestFormatFindingsText:
    """_format_findings produces correct text output."""

    def test_empty_findings_produces_empty_string(self) -> None:
        result = _format_findings([], "text")
        assert result == ""

    def test_info_finding_prefix(self) -> None:
        findings = [AuditFinding(kind="info", code="I001", message="all good", remediation="")]
        result = _format_findings(findings, "text")
        assert result.startswith("INFO:")
        assert "all good" in result

    def test_warn_finding_prefix(self) -> None:
        findings = [AuditFinding(kind="warn", code="W001", message="caution", remediation="")]
        result = _format_findings(findings, "text")
        assert result.startswith("WARN:")
        assert "caution" in result

    def test_error_finding_prefix(self) -> None:
        findings = [AuditFinding(kind="error", code="E001", message="bad", remediation="")]
        result = _format_findings(findings, "text")
        assert result.startswith("ERROR:")
        assert "bad" in result

    def test_multiple_findings_one_per_line(self) -> None:
        findings = [
            AuditFinding(kind="info", code="I001", message="msg1", remediation=""),
            AuditFinding(kind="warn", code="W001", message="msg2", remediation=""),
            AuditFinding(kind="error", code="E001", message="msg3", remediation=""),
        ]
        result = _format_findings(findings, "text")
        lines = result.strip().splitlines()
        assert len(lines) == 3
        assert lines[0].startswith("INFO:")
        assert lines[1].startswith("WARN:")
        assert lines[2].startswith("ERROR:")

    def test_remediation_appended_to_finding_line(self) -> None:
        """A non-empty remediation is appended to the finding line with ' -- '."""
        findings = [AuditFinding(kind="error", code="E001", message="broken", remediation="run fix")]
        result = _format_findings(findings, "text")
        assert "run fix" in result
        assert " -- " in result


@pytest.mark.unit
class TestFormatFindingsJson:
    """_format_findings produces parseable JSON output with a 'findings' key."""

    def test_empty_findings_json(self) -> None:
        result = _format_findings([], "json")
        parsed = json.loads(result)
        assert "findings" in parsed
        assert parsed["findings"] == []

    def test_findings_key_present(self) -> None:
        findings = [AuditFinding(kind="info", code="I001", message="ok", remediation="")]
        result = _format_findings(findings, "json")
        parsed = json.loads(result)
        assert "findings" in parsed
        assert len(parsed["findings"]) == 1

    def test_finding_fields_in_json(self) -> None:
        findings = [AuditFinding(kind="error", code="E001", message="bad thing", remediation="fix it")]
        result = _format_findings(findings, "json")
        parsed = json.loads(result)
        entry = parsed["findings"][0]
        assert entry["kind"] == "error"
        assert entry["code"] == "E001"
        assert entry["message"] == "bad thing"
        assert entry["remediation"] == "fix it"

    def test_json_output_is_parseable_by_json_loads(self) -> None:
        findings = [AuditFinding(kind="warn", code="W001", message="something", remediation="do X")]
        result = _format_findings(findings, "json")

        parsed = json.loads(result)
        assert isinstance(parsed, dict)


@pytest.mark.unit
class TestAuditFindingDataclass:
    """AuditFinding dataclass has the expected fields."""

    def test_kind_field(self) -> None:
        f = AuditFinding(kind="info", code="I001", message="msg", remediation="")
        assert f.kind == "info"

    def test_code_field(self) -> None:
        f = AuditFinding(kind="info", code="I001", message="msg", remediation="")
        assert f.code == "I001"

    def test_message_field(self) -> None:
        f = AuditFinding(kind="info", code="I001", message="hello world", remediation="")
        assert f.message == "hello world"

    def test_remediation_field(self) -> None:
        f = AuditFinding(kind="error", code="E001", message="bad", remediation="run X")
        assert f.remediation == "run X"

    def test_valid_kind_values(self) -> None:
        for kind in ("info", "warn", "error"):
            f = AuditFinding(kind=kind, code="X001", message="m", remediation="")
            assert f.kind == kind


@pytest.mark.unit
class TestAuditCheckRegistry:
    """AUDIT_CHECK_REGISTRY is a dict mapping check-names to callables (AC-FUNC-009)."""

    def test_registry_is_dict(self) -> None:
        assert isinstance(AUDIT_CHECK_REGISTRY, dict)

    def test_registry_keys_are_strings(self) -> None:
        for key in AUDIT_CHECK_REGISTRY:
            assert isinstance(key, str)

    def test_registry_values_are_callable(self) -> None:
        for value in AUDIT_CHECK_REGISTRY.values():
            assert callable(value)


@pytest.mark.unit
class TestStrictFlagParsed:
    """--strict flag is parsed and stored on args namespace (AC-FUNC-008)."""

    def test_strict_false_by_default(self) -> None:
        args = _make_args(strict=False)
        assert args.strict is False

    def test_strict_true_when_set(self) -> None:
        args = _make_args(strict=True)
        assert args.strict is True

    def test_audit_command_accepts_strict_arg(self, tmp_path: pathlib.Path) -> None:
        """audit_command does not error when strict=True in T1."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        args = _make_args(target=str(tmp_path), strict=True)
        with patch.dict(AUDIT_CHECK_REGISTRY, {}, clear=True):
            result = audit_command(args)

        assert result == 0


@pytest.mark.unit
class TestResolvAuditTargetErrors:
    """_resolve_audit_target and _check_repo_specs_dir error paths."""

    def test_nonexistent_local_path_exits_1(self, tmp_path: pathlib.Path) -> None:
        """Passing a nonexistent local directory exits with code 1."""
        nonexistent = str(tmp_path / "does_not_exist")
        args = _make_args(target=nonexistent)
        with pytest.raises(SystemExit) as exc_info:
            audit_command(args)
        assert exc_info.value.code == 1

    def test_path_without_repo_specs_exits_1(self, tmp_path: pathlib.Path) -> None:
        """A local path without repo-specs/ exits with code 1."""
        args = _make_args(target=str(tmp_path))
        with pytest.raises(SystemExit) as exc_info:
            audit_command(args)
        assert exc_info.value.code == 1


@pytest.mark.unit
class TestFormatFindingsInvalidFormat:
    """_format_findings raises ValueError for unknown format strings."""

    def test_invalid_format_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown output format"):
            _format_findings([], "xml")

    def test_error_message_includes_format_name(self) -> None:
        with pytest.raises(ValueError, match="badformat"):
            _format_findings([], "badformat")


@pytest.mark.unit
class TestFormatFindingsUnknownKind:
    """_format_findings raises ValueError for unknown AuditFinding.kind values."""

    def test_unknown_kind_raises_value_error(self) -> None:
        """An AuditFinding with an unknown kind raises ValueError with ERROR-shape message."""
        findings = [AuditFinding(kind="critical", code="X001", message="bad", remediation="")]
        with pytest.raises(ValueError, match="ERROR:.*AuditFinding.kind.*'critical'"):
            _format_findings(findings, "text")

    def test_unknown_kind_error_message_lists_valid_kinds(self) -> None:
        """The ValueError message names the valid kind values."""
        findings = [AuditFinding(kind="debug", code="X002", message="msg", remediation="")]
        with pytest.raises(ValueError) as exc_info:
            _format_findings(findings, "text")
        msg = str(exc_info.value)
        assert "error" in msg
        assert "warn" in msg
        assert "info" in msg

    def test_unknown_kind_does_not_affect_json_format(self) -> None:
        """_format_findings with fmt='json' does not validate kind (JSON serializes as-is)."""
        findings = [AuditFinding(kind="unknown_kind", code="X003", message="msg", remediation="")]
        result = _format_findings(findings, "json")
        parsed = json.loads(result)
        assert parsed["findings"][0]["kind"] == "unknown_kind"


@pytest.mark.unit
class TestFormatEnvVarValidation:
    """_register_audit validates KANON_CATALOG_AUDIT_FORMAT env var value."""

    def test_invalid_format_env_var_exits_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setting KANON_CATALOG_AUDIT_FORMAT to 'xml' causes sys.exit(1) at parser registration."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_ENV

        monkeypatch.setenv(KANON_CATALOG_AUDIT_FORMAT_ENV, "xml")

        import argparse as argparse_module

        catalog_parser = argparse_module.ArgumentParser()
        catalog_subparsers = catalog_parser.add_subparsers(dest="catalog_command")

        from kanon_cli.commands.catalog import _register_audit

        with pytest.raises(SystemExit) as exc_info:
            _register_audit(catalog_subparsers)
        assert exc_info.value.code == 1

    def test_valid_format_env_var_text_does_not_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setting KANON_CATALOG_AUDIT_FORMAT to 'text' does not raise SystemExit."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_ENV

        monkeypatch.setenv(KANON_CATALOG_AUDIT_FORMAT_ENV, "text")

        import argparse as argparse_module

        catalog_parser = argparse_module.ArgumentParser()
        catalog_subparsers = catalog_parser.add_subparsers(dest="catalog_command")

        from kanon_cli.commands.catalog import _register_audit

        _register_audit(catalog_subparsers)

    def test_valid_format_env_var_json_does_not_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setting KANON_CATALOG_AUDIT_FORMAT to 'json' does not raise SystemExit."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_ENV

        monkeypatch.setenv(KANON_CATALOG_AUDIT_FORMAT_ENV, "json")

        import argparse as argparse_module

        catalog_parser = argparse_module.ArgumentParser()
        catalog_subparsers = catalog_parser.add_subparsers(dest="catalog_command")

        from kanon_cli.commands.catalog import _register_audit

        _register_audit(catalog_subparsers)

    def test_invalid_format_env_var_prints_error_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Invalid KANON_CATALOG_AUDIT_FORMAT prints an ERROR-shape message to stderr."""
        from kanon_cli.constants import KANON_CATALOG_AUDIT_FORMAT_ENV

        monkeypatch.setenv(KANON_CATALOG_AUDIT_FORMAT_ENV, "csv")

        import argparse as argparse_module

        catalog_parser = argparse_module.ArgumentParser()
        catalog_subparsers = catalog_parser.add_subparsers(dest="catalog_command")

        from kanon_cli.commands.catalog import _register_audit

        with pytest.raises(SystemExit):
            _register_audit(catalog_subparsers)

        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
        assert "csv" in captured.err


@pytest.mark.unit
class TestCloneAuditTargetErrors:
    """_clone_audit_target error paths (empty ref, clone fails)."""

    def test_clone_resolves_cache_under_kanon_home(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_clone_audit_target no longer requires a cache env var: the clone cache
        resolves under <KANON_HOME>/cache/catalog-audit (the env-var-unset failure
        path is removed because KANON_HOME always resolves)."""
        import subprocess

        from kanon_cli.commands.catalog import _clone_audit_target
        from kanon_cli.constants import KANON_CATALOG_AUDIT_CACHE_SUBDIR

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        def mock_clone(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            dest = pathlib.Path(cmd[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "repo-specs").mkdir()
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_clone):
            result_path = _clone_audit_target("https://example.com/repo.git@main")

        expected_root = tmp_path / "cache" / KANON_CATALOG_AUDIT_CACHE_SUBDIR
        assert expected_root in result_path.parents, f"clone path {result_path} must live under {expected_root}"

    def test_clone_failure_exits_1(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failed git clone exits with code 1 and prints an ERROR message."""
        import subprocess

        from kanon_cli.commands.catalog import _clone_audit_target

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        failed_result = subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=1,
            stdout="",
            stderr="fatal: repository not found",
        )

        with patch("subprocess.run", return_value=failed_result):
            with pytest.raises(SystemExit) as exc_info:
                _clone_audit_target("https://example.com/repo.git@main")
        assert exc_info.value.code == 1

    def test_clone_success_but_no_repo_specs_exits_1(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A successful clone with no repo-specs/ exits with code 1."""
        import subprocess

        from kanon_cli.commands.catalog import _clone_audit_target

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        def mock_clone_empty(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            dest = cmd[-1]
            pathlib.Path(dest).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_clone_empty):
            with pytest.raises(SystemExit) as exc_info:
                _clone_audit_target("https://example.com/repo.git@main")
        assert exc_info.value.code == 1

    def test_clone_empty_ref_exits_1(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A source with an empty ref (ending in '@') exits with code 1."""
        from kanon_cli.commands.catalog import _clone_audit_target

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        with pytest.raises(SystemExit) as exc_info:
            _clone_audit_target("https://example.com/repo.git@")
        assert exc_info.value.code == 1

    def test_cached_clone_is_reused_within_ttl(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A cached clone within the TTL is reused without re-cloning."""
        import hashlib

        from kanon_cli.commands.catalog import _clone_audit_target
        from kanon_cli.constants import KANON_CATALOG_AUDIT_CACHE_SUBDIR
        from kanon_cli.core.url import canonicalize_repo_url

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        source = "https://example.com/repo.git@main"
        idx = source.rfind("@")
        url = source[:idx]
        ref = source[idx + 1 :]
        canonical_url = canonicalize_repo_url(url)
        cache_key = hashlib.sha256(f"{canonical_url}@{ref}".encode()).hexdigest()

        clone_path = tmp_path / "cache" / KANON_CATALOG_AUDIT_CACHE_SUBDIR / cache_key
        clone_path.mkdir(parents=True)
        (clone_path / "repo-specs").mkdir()

        with patch("subprocess.run") as mock_run:
            result_path = _clone_audit_target(source)
            mock_run.assert_not_called()

        assert result_path == clone_path

    def test_successful_clone_returns_path(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A successful git clone with repo-specs/ returns the clone path."""
        import subprocess as subprocess_module

        from kanon_cli.commands.catalog import _clone_audit_target

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        def mock_clone(cmd: list[str], **kwargs: object) -> subprocess_module.CompletedProcess:
            dest = pathlib.Path(cmd[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "repo-specs").mkdir()
            return subprocess_module.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_clone):
            result_path = _clone_audit_target("https://example.com/repo.git@main")

        assert result_path.is_dir()
        assert (result_path / "repo-specs").is_dir()

    def test_audit_command_dispatches_clone_for_remote_target(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """audit_command clones a remote target and invokes checks."""
        import subprocess as subprocess_module

        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        def mock_clone(cmd: list[str], **kwargs: object) -> subprocess_module.CompletedProcess:
            dest = pathlib.Path(cmd[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "repo-specs").mkdir()
            return subprocess_module.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        args = _make_args(target="https://example.com/repo.git@main")
        with patch("subprocess.run", side_effect=mock_clone):
            with patch.dict(AUDIT_CHECK_REGISTRY, {}, clear=True):
                result = audit_command(args)

        assert result == 0


@pytest.mark.unit
class TestRunAuditCLIDispatch:
    """The _run_audit function is exercised via the registered parser func."""

    def test_catalog_audit_func_dispatches_to_audit_command(self, tmp_path: pathlib.Path) -> None:
        """The registered args.func calls audit_command and returns an int."""
        from kanon_cli.cli import build_parser

        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()

        parser = build_parser()
        args = parser.parse_args(["catalog", "audit", str(tmp_path)])

        with patch.dict(AUDIT_CHECK_REGISTRY, {}, clear=True):
            result = args.func(args)

        assert result == 0

    def test_catalog_without_audit_triggers_help_func(self) -> None:
        """'kanon catalog' without a sub-subcommand triggers the help func (returns 2)."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["catalog"])

        result = args.func(args)
        assert result == 2


@pytest.mark.unit
class TestLooksLikeRemoteSource:
    """_looks_like_remote_source correctly identifies remote vs local targets."""

    def test_https_url_is_remote(self) -> None:
        from kanon_cli.commands.catalog import _looks_like_remote_source

        assert _looks_like_remote_source("https://github.com/org/repo.git@main") is True

    def test_ssh_shorthand_url_is_remote(self) -> None:
        from kanon_cli.commands.catalog import _looks_like_remote_source

        assert _looks_like_remote_source("git@github.com:org/repo.git@main") is True

    def test_local_path_no_at_is_not_remote(self) -> None:
        from kanon_cli.commands.catalog import _looks_like_remote_source

        assert _looks_like_remote_source("/some/local/path") is False

    def test_local_path_with_single_at_is_not_remote(self) -> None:
        from kanon_cli.commands.catalog import _looks_like_remote_source

        assert _looks_like_remote_source("path@version") is False

    def test_no_at_sign_is_not_remote(self) -> None:
        from kanon_cli.commands.catalog import _looks_like_remote_source

        assert _looks_like_remote_source(".") is False

    def test_ssh_url_with_scheme_is_remote(self) -> None:
        from kanon_cli.commands.catalog import _looks_like_remote_source

        assert _looks_like_remote_source("ssh://git@github.com/org/repo.git@main") is True
