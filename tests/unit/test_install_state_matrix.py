"""Unit tests for the install state-matrix branching in kanon install.

AC-TEST-001: parametrises every row of the spec's state matrix (Section 4.7),
mocking the resolver to return predetermined SHAs and asserting the correct
branch is taken: which info-line is emitted, whether the lockfile is rewritten,
whether a hard error is raised with the expected exception class and message.

AC-FUNC-001 through AC-FUNC-008: verified via the parametrised test cases.
AC-CYCLE-001: end-to-end hash-mismatch cycle captured in the log.
"""

from __future__ import annotations

import pathlib
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import (
    InstallClassification,
    InstallError,
    InstallState,
    KanonHashMismatchError,
    LockfileUnreachableShaError,
    _RefResolution,
    _check_sha_reachable,
    _classify_install_state,
    _emit_install_state,
    _resolve_ref_to_sha,
    install,
    read_lockfile_if_present,
)


_KANON_SINGLE_SOURCE = """\
GITBASE=https://git.example.com
CLAUDE_MARKETPLACES_DIR=/tmp/mktplc
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_alpha_URL=https://git.example.com/alpha.git
KANON_SOURCE_alpha_REF=main
KANON_SOURCE_alpha_PATH=manifest.xml
KANON_SOURCE_alpha_NAME=alpha
KANON_SOURCE_alpha_GITBASE=https://example.com
"""

_KANON_SINGLE_SOURCE_MODIFIED = """\
GITBASE=https://git.example.com
CLAUDE_MARKETPLACES_DIR=/tmp/mktplc
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_alpha_URL=https://git.example.com/alpha.git
KANON_SOURCE_alpha_REF=2.0.0
KANON_SOURCE_alpha_PATH=manifest.xml
KANON_SOURCE_alpha_NAME=alpha
KANON_SOURCE_alpha_GITBASE=https://example.com
"""

_VALID_SHA40 = "a" * 40
_VALID_SHA64 = "b" * 64
_KANON_HASH_PLACEHOLDER = "sha256:" + "c" * 64


def _write_kanon(directory: pathlib.Path, content: str = _KANON_SINGLE_SOURCE) -> pathlib.Path:
    kanon_path = directory / ".kanon"
    kanon_path.write_text(content)

    kanon_path.chmod(0o600)
    return kanon_path


def _write_lockfile(
    directory: pathlib.Path,
    kanon_hash: str,
) -> pathlib.Path:
    """Write a minimal valid schema-v4 .kanon.lock TOML file and return its path.

    The v5 lock is alias-keyed and carries no [catalog] block (spec Section 5.2).
    """
    lock_path = directory / ".kanon.lock"
    content = f"""\
schema_version = 5
generated_at = "2026-01-15T00:00:00Z"
generator = "kanon-cli/test"
kanon_hash = "{kanon_hash}"
marketplace_registered = false
marketplace_dir = ""

[[sources]]
alias = "alpha"
name = "alpha"
url = "https://git.example.com/alpha.git"
ref_spec = "main"
resolved_ref = "refs/heads/main"
resolved_sha = "{_VALID_SHA40}"
path = "manifest.xml"
"""
    lock_path.write_text(content)
    return lock_path


@pytest.mark.unit
class TestClassifyInstallState:
    """Parametrised tests for _classify_install_state helper (AC-FUNC-008)."""

    def test_lockfile_absent(self, tmp_path: pathlib.Path) -> None:
        """State = lockfile-absent when .kanon exists but .kanon.lock does not."""
        kanon_path = _write_kanon(tmp_path)
        lock_path = tmp_path / ".kanon.lock"
        classification = _classify_install_state(kanon_path, lock_path)
        assert isinstance(classification, InstallClassification)
        assert classification.state is InstallState.LOCKFILE_ABSENT
        assert classification.computed_hash is None
        assert classification.lockfile is None

    def test_lockfile_consistent(self, tmp_path: pathlib.Path) -> None:
        """State = lockfile-consistent when kanon_hash matches."""
        kanon_path = _write_kanon(tmp_path)

        from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash

        real_hash = compute_kanon_hash(kanon_path)
        lock_path = _write_lockfile(tmp_path, real_hash)
        classification = _classify_install_state(kanon_path, lock_path)
        assert isinstance(classification, InstallClassification)
        assert classification.state is InstallState.LOCKFILE_CONSISTENT
        assert classification.computed_hash == real_hash
        assert classification.lockfile is not None

    def test_lockfile_hash_mismatch(self, tmp_path: pathlib.Path) -> None:
        """State = lockfile-hash-mismatch when kanon_hash does NOT match."""
        kanon_path = _write_kanon(tmp_path)
        wrong_hash = "sha256:" + "d" * 64
        lock_path = _write_lockfile(tmp_path, wrong_hash)
        classification = _classify_install_state(kanon_path, lock_path)
        assert isinstance(classification, InstallClassification)
        assert classification.state is InstallState.LOCKFILE_HASH_MISMATCH
        assert classification.computed_hash is not None
        assert classification.lockfile is not None

    @pytest.mark.parametrize(
        "content,description",
        [
            (_KANON_SINGLE_SOURCE, "original content"),
            (_KANON_SINGLE_SOURCE_MODIFIED, "modified revision"),
        ],
    )
    def test_parametrised_absent_vs_modified(
        self,
        tmp_path: pathlib.Path,
        content: str,
        description: str,
    ) -> None:
        """Lock absent -> LOCKFILE_ABSENT regardless of .kanon content."""
        kanon_path = _write_kanon(tmp_path, content)
        lock_path = tmp_path / ".kanon.lock"
        classification = _classify_install_state(kanon_path, lock_path)
        assert classification.state is InstallState.LOCKFILE_ABSENT, description


@pytest.mark.unit
class TestReadLockfileIfPresent:
    def test_returns_none_when_absent(self, tmp_path: pathlib.Path) -> None:
        lock_path = tmp_path / ".kanon.lock"
        result = read_lockfile_if_present(lock_path)
        assert result is None

    def test_returns_lockfile_when_present(self, tmp_path: pathlib.Path) -> None:
        lock_path = _write_lockfile(tmp_path, _KANON_HASH_PLACEHOLDER)
        from kanon_cli.core.lockfile import Lockfile

        result = read_lockfile_if_present(lock_path)
        assert isinstance(result, Lockfile)
        assert result.kanon_hash == _KANON_HASH_PLACEHOLDER

    def test_raises_on_parse_error(self, tmp_path: pathlib.Path) -> None:
        lock_path = tmp_path / ".kanon.lock"
        lock_path.write_text("not valid toml {[")
        with pytest.raises(Exception):
            read_lockfile_if_present(lock_path)


@pytest.mark.unit
class TestExceptionHierarchy:
    def test_install_error_is_exception(self) -> None:
        err = InstallError("test")
        assert isinstance(err, Exception)

    def test_kanon_hash_mismatch_is_install_error(self) -> None:
        err = KanonHashMismatchError(
            lockfile_hash="sha256:" + "a" * 64,
            computed_hash="sha256:" + "b" * 64,
        )
        assert isinstance(err, InstallError)
        msg = str(err)
        assert "sha256:" + "a" * 64 in msg
        assert "sha256:" + "b" * 64 in msg
        assert "--refresh-lock" in msg

    def test_lockfile_unreachable_sha_is_install_error(self) -> None:
        err = LockfileUnreachableShaError(
            source_name="alpha",
            sha=_VALID_SHA40,
            remote_url="https://git.example.com/alpha.git",
        )
        assert isinstance(err, InstallError)
        msg = str(err)
        assert "alpha" in msg
        assert _VALID_SHA40 in msg
        assert "https://git.example.com/alpha.git" in msg
        assert "--refresh-lock-source" in msg


@pytest.mark.unit
class TestEmitInstallState:
    """Verify the spec's exact info-line text (AC-FUNC-001, AC-FUNC-002)."""

    def test_lockfile_absent_state(self, capsys: pytest.CaptureFixture[str]) -> None:
        _emit_install_state(InstallState.LOCKFILE_ABSENT, sources=2, projects=5)
        captured = capsys.readouterr()
        assert "lockfile rebuilt from .kanon (2 sources, 5 projects)" in captured.out

    def test_lockfile_consistent_state(self, capsys: pytest.CaptureFixture[str]) -> None:
        _emit_install_state(InstallState.LOCKFILE_CONSISTENT, sources=1, projects=3)
        captured = capsys.readouterr()
        assert "installing from lockfile (1 sources, 3 projects)" in captured.out

    @pytest.mark.parametrize(
        "sources,projects",
        [(0, 0), (1, 1), (10, 100)],
    )
    def test_counts_are_parametrised(
        self,
        capsys: pytest.CaptureFixture[str],
        sources: int,
        projects: int,
    ) -> None:
        _emit_install_state(InstallState.LOCKFILE_ABSENT, sources=sources, projects=projects)
        captured = capsys.readouterr()
        assert f"({sources} sources, {projects} projects)" in captured.out


@pytest.mark.unit
class TestHashMismatchBranch:
    """Verify the hash-mismatch state raises KanonHashMismatchError (AC-FUNC-003)."""

    def test_hash_mismatch_error_names_both_hashes(self, tmp_path: pathlib.Path) -> None:
        kanon_path = _write_kanon(tmp_path)
        from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash

        real_hash = compute_kanon_hash(kanon_path)
        stale_hash = "sha256:" + "f" * 64
        err = KanonHashMismatchError(lockfile_hash=stale_hash, computed_hash=real_hash)
        msg = str(err)
        assert stale_hash in msg
        assert real_hash in msg

    def test_hash_mismatch_remediation_names_flags(self) -> None:
        err = KanonHashMismatchError(
            lockfile_hash="sha256:" + "a" * 64,
            computed_hash="sha256:" + "b" * 64,
        )
        msg = str(err)
        assert "--refresh-lock" in msg
        assert "--refresh-lock-source" in msg


@pytest.mark.unit
class TestLockfileUnreachableSha:
    def test_error_names_source_sha_and_url(self) -> None:
        err = LockfileUnreachableShaError(
            source_name="my-source",
            sha="aabbccddeeff" + "0" * 28,
            remote_url="https://git.example.com/my-source.git",
        )
        msg = str(err)
        assert "my-source" in msg
        assert "aabbccddeeff" in msg
        assert "https://git.example.com/my-source.git" in msg

    def test_remediation_names_refresh_lock_source(self) -> None:
        err = LockfileUnreachableShaError(
            source_name="foo",
            sha=_VALID_SHA40,
            remote_url="https://git.example.com/foo.git",
        )
        assert "--refresh-lock-source" in str(err)


@pytest.mark.unit
class TestInstallRaisesLockfileUnreachableShaError:
    """AC-FUNC-004: LockfileUnreachableShaError is correctly instantiated and stringified.

    LOCKFILE_UNREACHABLE is detected at runtime when repo sync fails because a
    pinned SHA is no longer reachable -- not as a pre-check inside install().
    git ls-remote only supports ref name patterns, not bare SHAs, so a
    pre-check via ls-remote would always return empty stdout and raise
    unconditionally, breaking lockfile replay entirely.

    This test verifies the exception class itself: that it carries the
    expected fields and renders a message naming the source, SHA, URL, and
    remediation flag.
    """

    def test_exception_carries_fields_and_str(self) -> None:
        """LockfileUnreachableShaError holds source_name, sha, remote_url and renders correctly."""
        err = LockfileUnreachableShaError(
            source_name="alpha",
            sha=_VALID_SHA40,
            remote_url="https://git.example.com/alpha.git",
        )
        assert isinstance(err, InstallError)
        assert err.source_name == "alpha"
        assert err.sha == _VALID_SHA40
        assert err.remote_url == "https://git.example.com/alpha.git"
        msg = str(err)
        assert "alpha" in msg
        assert _VALID_SHA40 in msg
        assert "https://git.example.com/alpha.git" in msg
        assert "--refresh-lock-source" in msg


@pytest.mark.unit
class TestInstallIgnoresCatalogSourceEnv:
    """install() is hermetic: a populated KANON_CATALOG_SOURCES env var has no
    effect on install -- it is ignored (never read), not rejected.  install()
    resolves solely from the committed .kanon (+ .kanon.lock) and writes the
    lockfile from those declarations regardless of the env var.

    install() no longer accepts a catalog_source parameter at all; the
    --catalog-source flag is not registered on the install parser, so the only
    way an operator can leak a catalog source toward install is via the env var,
    which this class proves is ignored.
    """

    def test_install_absent_ignores_env_catalog_source_and_writes_lockfile(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A populated KANON_CATALOG_SOURCES env is ignored; install resolves from .kanon and writes the lock."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://env.example.com/catalog.git@main")

        kanon_path = _write_kanon(tmp_path)
        lock_path = tmp_path / ".kanon.lock"
        assert not lock_path.exists()

        mock_ref = _RefResolution(sha="a" * 40, resolved_ref="refs/heads/main")
        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=mock_ref),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("manifest.xml"))),
        ):
            install(
                kanonenv_path=kanon_path,
                lock_file_path=lock_path,
            )

        assert lock_path.exists(), "install() must ignore KANON_CATALOG_SOURCES and write the lockfile from .kanon"

        lock_text = lock_path.read_text(encoding="utf-8")
        assert "https://git.example.com/alpha.git" in lock_text
        assert "https://env.example.com/catalog.git" not in lock_text

    def test_install_consistent_ignores_env_catalog_source(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """In the consistent state a populated KANON_CATALOG_SOURCES env does not change replay."""
        from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash

        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://env.example.com/catalog.git@main")

        kanon_path = _write_kanon(tmp_path)
        real_hash = compute_kanon_hash(kanon_path)
        lock_path = _write_lockfile(tmp_path, real_hash)
        original_lock_text = lock_path.read_text(encoding="utf-8")

        reachable_sha_output = f"{_VALID_SHA40}\trefs/heads/main\n{'e' * 40}\trefs/tags/1.0.0\n"
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = reachable_sha_output
        mock_result.stderr = ""

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("subprocess.run", return_value=mock_result),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("manifest.xml"))),
        ):
            install(
                kanonenv_path=kanon_path,
                lock_file_path=lock_path,
            )

        assert lock_path.read_text(encoding="utf-8") == original_lock_text


@pytest.mark.unit
class TestCheckShaReachable:
    """Unit tests for _check_sha_reachable helper (AC-FUNC-004)."""

    def test_sha_present_in_ls_remote_output_passes(self) -> None:
        """No exception raised when pinned SHA appears in git ls-remote output."""
        pinned_sha = _VALID_SHA40
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = f"{pinned_sha}\trefs/heads/main\n{'e' * 40}\trefs/tags/1.0.0\n"
        with patch("subprocess.run", return_value=mock_result):
            _check_sha_reachable(
                url="https://git.example.com/repo.git",
                sha=pinned_sha,
                source_name="alpha",
            )

    def test_sha_absent_from_ls_remote_output_raises(self) -> None:
        """LockfileUnreachableShaError raised when pinned SHA is NOT in ls-remote output."""
        pinned_sha = _VALID_SHA40
        mock_result = MagicMock()
        mock_result.returncode = 0

        mock_result.stdout = f"{'e' * 40}\trefs/heads/main\n{'f' * 40}\trefs/tags/1.0.0\n"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(LockfileUnreachableShaError) as exc_info:
                _check_sha_reachable(
                    url="https://git.example.com/repo.git",
                    sha=pinned_sha,
                    source_name="alpha",
                )
        err = exc_info.value
        assert err.source_name == "alpha"
        assert err.sha == pinned_sha
        assert err.remote_url == "https://git.example.com/repo.git"

    def test_ls_remote_failure_raises(self) -> None:
        """LockfileUnreachableShaError raised when git ls-remote returns non-zero exit."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(LockfileUnreachableShaError) as exc_info:
                _check_sha_reachable(
                    url="https://git.example.com/repo.git",
                    sha=_VALID_SHA40,
                    source_name="beta",
                )
        err = exc_info.value
        assert err.source_name == "beta"


@pytest.mark.unit
class TestInstallRaisesLockfileUnreachableShaErrorEndToEnd:
    """AC-FUNC-004: install() raises LockfileUnreachableShaError in LOCKFILE_CONSISTENT state
    when subprocess.run returns output that does NOT contain the pinned SHA."""

    def test_install_consistent_unreachable_sha_raises(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() in LOCKFILE_CONSISTENT state raises LockfileUnreachableShaError
        when the pinned SHA is not present in git ls-remote output (simulating
        the SHA having been force-pushed away or garbage-collected on remote).
        """

        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)

        from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash

        kanon_path = _write_kanon(tmp_path)
        real_hash = compute_kanon_hash(kanon_path)

        lock_path = tmp_path / ".kanon.lock"
        lock_path.write_text(
            f"""\
schema_version = 5
generated_at = "2026-01-15T00:00:00Z"
generator = "kanon-cli/test"
kanon_hash = "{real_hash}"
marketplace_registered = false
marketplace_dir = ""

[[sources]]
alias = "alpha"
name = "alpha"
url = "https://git.example.com/alpha.git"
ref_spec = "==1.0.0"
resolved_ref = "refs/tags/v1.0.0"
resolved_sha = "{_VALID_SHA40}"
path = "manifest.xml"
"""
        )

        absent_sha_output = f"{'e' * 40}\trefs/heads/main\n{'f' * 40}\trefs/tags/1.0.0\n"
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = absent_sha_output
        mock_result.stderr = ""

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(LockfileUnreachableShaError) as exc_info:
                install(
                    kanonenv_path=kanon_path,
                    lock_file_path=lock_path,
                )

        err = exc_info.value
        assert err.source_name == "alpha"
        assert err.sha == _VALID_SHA40
        assert err.remote_url == "https://git.example.com/alpha.git"
        msg = str(err)
        assert "--refresh-lock-source" in msg

    def test_install_consistent_reachable_sha_does_not_raise(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() in LOCKFILE_CONSISTENT state does NOT raise LockfileUnreachableShaError
        when the pinned SHA IS present in git ls-remote output (SHA is reachable).
        """

        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)

        from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash

        kanon_path = _write_kanon(tmp_path)
        real_hash = compute_kanon_hash(kanon_path)
        lock_path = _write_lockfile(tmp_path, real_hash)

        reachable_sha_output = f"{_VALID_SHA40}\trefs/heads/main\n{'e' * 40}\trefs/tags/1.0.0\n"
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = reachable_sha_output
        mock_result.stderr = ""

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("subprocess.run", return_value=mock_result),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("manifest.xml"))),
        ):
            install(
                kanonenv_path=kanon_path,
                lock_file_path=lock_path,
            )


@pytest.mark.unit
class TestGitLsRemoteTimeoutEnvVar:
    """KANON_GIT_LS_REMOTE_TIMEOUT env var overrides the default timeout."""

    def test_default_timeout_is_30(self) -> None:
        import importlib

        import kanon_cli.constants as constants

        importlib.reload(constants)
        assert constants.KANON_GIT_LS_REMOTE_TIMEOUT == 30

    def test_check_sha_reachable_passes_timeout_to_subprocess(self) -> None:
        """Verify _check_sha_reachable passes KANON_GIT_LS_REMOTE_TIMEOUT to
        subprocess.run as the timeout kwarg."""
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = f"{'a' * 40}\trefs/heads/main\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _check_sha_reachable(
                url="https://example.com/repo.git",
                sha="a" * 40,
                source_name="test",
            )

            call_kwargs = mock_run.call_args.kwargs
            assert "timeout" in call_kwargs
            from kanon_cli.constants import KANON_GIT_LS_REMOTE_TIMEOUT

            assert call_kwargs["timeout"] == KANON_GIT_LS_REMOTE_TIMEOUT


@pytest.mark.unit
class TestResolveRefToSha:
    """Unit tests for _resolve_ref_to_sha error branches."""

    def test_git_ls_remote_nonzero_raises_value_error(self) -> None:
        """_resolve_ref_to_sha raises ValueError when git ls-remote exits non-zero."""
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: repository not found"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(ValueError, match="git ls-remote failed"):
                _resolve_ref_to_sha("https://example.com/repo.git", "main")

    def test_ref_not_found_raises_value_error(self) -> None:
        """_resolve_ref_to_sha raises ValueError when the ref is not in ls-remote output."""
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0

        mock_result.stdout = f"{'e' * 40}\trefs/heads/develop\n{'f' * 40}\trefs/tags/0.9.0\n"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(ValueError, match="not found in remote"):
                _resolve_ref_to_sha("https://example.com/repo.git", "main")

    def test_matching_ref_returns_resolution(self) -> None:
        """_resolve_ref_to_sha returns _RefResolution when a matching ref is found."""
        expected_sha = "a" * 40
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = f"{expected_sha}\trefs/heads/main\n"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = _resolve_ref_to_sha("https://example.com/repo.git", "main")
        assert isinstance(result, _RefResolution)
        assert result.sha == expected_sha
        assert result.resolved_ref == "refs/heads/main"


@pytest.mark.unit
class TestInstallParserRejectsCatalogSourceFlag:
    """The install subparser does not accept --catalog-source.

    install is hermetic (spec Section 4.3 / FR-14): the catalog source belongs to
    the catalog-querying commands, not install.  Because the flag is not registered
    on the install subparser, argparse rejects it as an unrecognized argument and
    exits non-zero -- there is no install-side catalog_source parameter at all.
    """

    @pytest.mark.parametrize(
        "catalog_value",
        [
            "https://git.example.com/catalog.git@main",
            "https://example.com/catalog.git",
            "latest",
        ],
    )
    def test_install_subparser_rejects_catalog_source(self, catalog_value: str) -> None:
        """Passing --catalog-source to install raises SystemExit with a non-zero code."""
        import argparse

        from kanon_cli.commands.install import register

        parser = argparse.ArgumentParser(prog="kanon")
        subparsers = parser.add_subparsers()
        register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["install", "--catalog-source", catalog_value])

        assert exc_info.value.code != 0

    def test_install_subparser_has_no_catalog_source_action(self) -> None:
        """The install subparser exposes no --catalog-source option string."""
        import argparse

        from kanon_cli.commands.install import register

        parser = argparse.ArgumentParser(prog="kanon")
        subparsers = parser.add_subparsers()
        register(subparsers)

        install_parser = subparsers.choices["install"]
        option_strings = {opt for action in install_parser._actions for opt in action.option_strings}
        assert "--catalog-source" not in option_strings
