"""Tests for the catalog resolution module."""

import json
from unittest.mock import patch

import pytest

from kanon_cli.commands.catalog import AuditFinding, _build_findings_payload
from kanon_cli.constants import (
    CATALOG_DEFAULT_BRANCH_ENV_VAR,
)
from kanon_cli.core.catalog import (
    DefaultBranchResolutionError,
    _parse_catalog_source,
    resolve_default_branch,
)


@pytest.mark.unit
class TestParseCatalogSource:
    """Verify catalog source string parsing."""

    def test_parses_https_url_with_tag(self) -> None:
        url, ref = _parse_catalog_source("https://github.com/org/repo.git@v1.0.0")
        assert url == "https://github.com/org/repo.git"
        assert ref == "v1.0.0"

    def test_parses_ssh_url_with_branch(self) -> None:
        url, ref = _parse_catalog_source("git@github.com:org/repo.git@main")
        assert url == "git@github.com:org/repo.git"
        assert ref == "main"

    def test_parses_latest(self) -> None:
        url, ref = _parse_catalog_source("https://github.com/org/repo.git@latest")
        assert url == "https://github.com/org/repo.git"
        assert ref == "latest"

    def test_missing_at_sign_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid catalog source format"):
            _parse_catalog_source("https://github.com/org/repo.git")

    def test_empty_ref_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty ref"):
            _parse_catalog_source("https://github.com/org/repo.git@")

    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty URL"):
            _parse_catalog_source("@main")

    def test_ambiguous_ssh_url_without_ref_raises(self) -> None:
        """SSH-style URL with no trailing @<ref> is rejected (lines 105-111 guard)."""
        with pytest.raises(ValueError, match="Invalid catalog source format"):
            _parse_catalog_source("git@host:org/repo.git")


@pytest.mark.unit
class TestCatalogSubparserHelp:
    """The 'catalog' and 'catalog audit' subparsers have add_help=True and accept '-h'."""

    def test_catalog_short_dash_h_exits_0(self) -> None:
        """kanon catalog -h exits 0 (add_help=True on the catalog subparser)."""

        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["catalog", "-h"])
        assert exc_info.value.code == 0

    def test_catalog_audit_short_dash_h_exits_0(self) -> None:
        """kanon catalog audit -h exits 0 (add_help=True on the audit sub-subparser)."""

        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["catalog", "audit", "-h"])
        assert exc_info.value.code == 0

    def test_catalog_subparser_has_add_help_true(self) -> None:
        """The 'catalog' subparser has add_help=True set explicitly."""
        import argparse

        from kanon_cli.commands.catalog import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        catalog_parser = subparsers.choices["catalog"]
        assert catalog_parser.add_help is True, "catalog subparser must have add_help=True so '-h' is accepted"

    def test_catalog_audit_subparser_has_add_help_true(self) -> None:
        """The 'catalog audit' sub-subparser has add_help=True set explicitly."""
        import argparse

        from kanon_cli.commands.catalog import register

        root_parser = argparse.ArgumentParser()
        subparsers = root_parser.add_subparsers(dest="command")
        register(subparsers)
        catalog_parser = subparsers.choices["catalog"]
        for action in catalog_parser._actions:
            if hasattr(action, "choices") and action.choices and "audit" in action.choices:
                audit_parser = action.choices["audit"]
                assert audit_parser.add_help is True, (
                    "catalog audit sub-subparser must have add_help=True so '-h' is accepted"
                )
                return
        raise AssertionError("No 'audit' sub-subparser found under 'catalog'")


@pytest.mark.unit
class TestBuildFindingsPayload:
    """_build_findings_payload returns a dict consumed by _emit_json_payload."""

    def _make_finding(
        self,
        kind: str = "error",
        code: str = "E001",
        message: str = "Something wrong.",
        remediation: str = "",
    ) -> AuditFinding:
        """Build a minimal AuditFinding for testing."""
        return AuditFinding(kind=kind, code=code, message=message, remediation=remediation)

    def test_payload_has_findings_key(self) -> None:
        """The payload dict has a single 'findings' key."""
        finding = self._make_finding()
        payload = _build_findings_payload([finding])
        assert "findings" in payload
        assert set(payload.keys()) == {"findings"}

    def test_findings_list_length_matches_input(self) -> None:
        """The 'findings' list has the same length as the input list."""
        findings = [self._make_finding(), self._make_finding(kind="warn", code="W001")]
        payload = _build_findings_payload(findings)
        assert len(payload["findings"]) == 2

    def test_empty_input_produces_empty_findings_list(self) -> None:
        """Empty input produces {'findings': []}."""
        payload = _build_findings_payload([])
        assert payload == {"findings": []}

    def test_finding_fields_are_preserved(self) -> None:
        """Each finding dict contains the expected fields."""
        finding = self._make_finding(kind="error", code="E001", message="Bad.", remediation="Fix it.")
        payload = _build_findings_payload([finding])
        finding_dict = payload["findings"][0]
        assert finding_dict["kind"] == "error"
        assert finding_dict["code"] == "E001"
        assert finding_dict["message"] == "Bad."
        assert finding_dict["remediation"] == "Fix it."

    def test_result_is_json_serialisable(self) -> None:
        """The payload round-trips through json.dumps / json.loads without error."""
        finding = self._make_finding()
        payload = _build_findings_payload([finding])
        serialised = json.dumps(payload)
        parsed = json.loads(serialised)
        assert parsed["findings"][0]["code"] == "E001"


_TEST_URL = "https://example.com/org/manifest-repo.git"
_TEST_SHA = "abcdef1234567890abcdef1234567890abcdef12"


@pytest.mark.unit
class TestResolveDefaultBranchPrecedence:
    """Verify the default-branch precedence (AC-15 / FR-26 / FR-27, spec Section 6)."""

    def test_inline_ref_wins_over_flag_and_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit inline @ref short-circuits the precedence verbatim."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "env-branch")

        with patch("kanon_cli.core.catalog._list_branch_head") as mock_exists:
            with patch("kanon_cli.core.catalog._resolve_symref_default_branch") as mock_symref:
                result = resolve_default_branch(_TEST_URL, inline_ref="v1.2.3", flag_value="flag-branch")
        assert result == "v1.2.3"
        mock_exists.assert_not_called()
        mock_symref.assert_not_called()

    def test_flag_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The --catalog-default-branch flag value beats the env default."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "env-branch")
        with patch("kanon_cli.core.catalog._list_branch_head", return_value=_TEST_SHA) as mock_exists:
            result = resolve_default_branch(_TEST_URL, inline_ref=None, flag_value="flag-branch")
        assert result == "flag-branch"
        mock_exists.assert_called_once_with(_TEST_URL, "flag-branch")

    def test_env_default_used_when_no_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no inline ref and no flag, the env value is used."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "env-branch")
        with patch("kanon_cli.core.catalog._list_branch_head", return_value=_TEST_SHA):
            result = resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None)
        assert result == "env-branch"

    def test_falls_back_to_main_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no inline ref, no flag, and no env, the default is 'main'."""
        monkeypatch.delenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, raising=False)
        with patch("kanon_cli.core.catalog._list_branch_head", return_value=_TEST_SHA) as mock_exists:
            result = resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None)
        assert result == "main"
        mock_exists.assert_called_once_with(_TEST_URL, "main")

    def test_auto_resolves_symref_advertised_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The literal 'auto' resolves the symref-advertised branch."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "auto")
        with patch("kanon_cli.core.catalog._resolve_symref_default_branch", return_value="trunk") as mock_symref:
            with patch("kanon_cli.core.catalog._list_branch_head", return_value=_TEST_SHA) as mock_exists:
                result = resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None)
        assert result == "trunk"
        mock_symref.assert_called_once_with(_TEST_URL)
        mock_exists.assert_called_once_with(_TEST_URL, "trunk")

    def test_auto_via_flag_resolves_symref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A --catalog-default-branch=auto flag also triggers symref resolution."""
        monkeypatch.delenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, raising=False)
        with patch("kanon_cli.core.catalog._resolve_symref_default_branch", return_value="main") as mock_symref:
            with patch("kanon_cli.core.catalog._list_branch_head", return_value=_TEST_SHA):
                result = resolve_default_branch(_TEST_URL, inline_ref=None, flag_value="auto")
        assert result == "main"
        mock_symref.assert_called_once_with(_TEST_URL)


@pytest.mark.unit
class TestResolveDefaultBranchSymrefAbsent:
    """Verify the symref-absent fail-fast (spec Section 6 error)."""

    def test_symref_absent_raises_default_branch_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """auto with no advertised HEAD symref fails fast with the actionable error."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "auto")
        with patch("kanon_cli.core.catalog._resolve_symref_default_branch", return_value=None):
            with pytest.raises(DefaultBranchResolutionError) as exc_info:
                resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None)
        message = str(exc_info.value)
        assert "cannot resolve the default branch" in message
        assert _TEST_URL in message
        assert "KANON_CATALOG_DEFAULT_BRANCH" in message
        assert "--catalog-default-branch" in message
        assert "@<ref>" in message

    def test_symref_absent_skips_existence_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No branch-existence lookup is attempted when symref resolution fails."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "auto")
        with patch("kanon_cli.core.catalog._resolve_symref_default_branch", return_value=None):
            with patch("kanon_cli.core.catalog._list_branch_head") as mock_exists:
                with pytest.raises(DefaultBranchResolutionError):
                    resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None)
        mock_exists.assert_not_called()


@pytest.mark.unit
class TestResolveDefaultBranchExistenceCheck:
    """Verify a defaulted branch is verified to exist (spec Section 6)."""

    def test_missing_defaulted_branch_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A defaulted branch absent from the remote raises DefaultBranchResolutionError."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "nonexistent")
        not_found = ValueError(
            f"ERROR: Branch 'nonexistent' (refs/heads/nonexistent) not found on remote {_TEST_URL!r}."
        )
        with patch("kanon_cli.core.catalog._list_branch_head", side_effect=not_found):
            with pytest.raises(DefaultBranchResolutionError) as exc_info:
                resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None)
        assert "not found on remote" in str(exc_info.value)

    def test_ls_remote_failure_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A ls-remote RuntimeError during existence verify is surfaced fail-fast."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "main")
        runtime_err = RuntimeError("ERROR: git ls-remote failed for 'x': boom")
        with patch("kanon_cli.core.catalog._list_branch_head", side_effect=runtime_err):
            with pytest.raises(DefaultBranchResolutionError, match="git ls-remote failed"):
                resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None)


@pytest.mark.unit
class TestResolveDefaultBranchWarn:
    """Verify the deduped yellow WARN to stderr (spec Section 6)."""

    def test_defaulted_branch_emits_warn_to_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A defaulted branch writes a WARNING naming the branch to stderr only."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "develop")
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setattr("kanon_cli.constants._NO_COLOR_ACTIVE", True)
        with patch("kanon_cli.core.catalog._list_branch_head", return_value=_TEST_SHA):
            resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "WARNING" in captured.err
        assert "develop" in captured.err
        assert _TEST_URL in captured.err

    def test_inline_ref_emits_no_warn(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A pinned inline ref emits no WARN (the operator pinned it explicitly)."""
        with patch("kanon_cli.core.catalog._list_branch_head"):
            resolve_default_branch(_TEST_URL, inline_ref="v1.0.0", flag_value=None)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_warn_deduped_once_per_source(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With a shared dedup set, the WARN fires once per defaulted source."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "main")
        monkeypatch.setattr("kanon_cli.constants._NO_COLOR_ACTIVE", True)
        warned: set[str] = set()
        with patch("kanon_cli.core.catalog._list_branch_head", return_value=_TEST_SHA):
            resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None, warned_urls=warned)
            resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None, warned_urls=warned)
        captured = capsys.readouterr()
        assert captured.err.count("WARNING") == 1
        assert warned == {_TEST_URL}

    def test_warn_is_yellow_when_color_active(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The WARN is rendered in ANSI yellow when color is not suppressed."""
        monkeypatch.setenv(CATALOG_DEFAULT_BRANCH_ENV_VAR, "main")
        monkeypatch.setattr("kanon_cli.constants._NO_COLOR_ACTIVE", False)
        with patch("kanon_cli.core.catalog._list_branch_head", return_value=_TEST_SHA):
            resolve_default_branch(_TEST_URL, inline_ref=None, flag_value=None)
        captured = capsys.readouterr()
        assert "\033[33m" in captured.err
        assert "\033[0m" in captured.err
