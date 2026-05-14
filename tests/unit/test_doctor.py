"""Unit tests for kanon_cli.commands.doctor.

Covers:
- Subparser registration structure
- run_doctor --refresh-completion-cache creates .kanon-data/completion-cache/
- run_doctor --refresh-completion-cache creates .kanon-data/ via workspace lock
- run_doctor (no flags) health check paths
- Workspace lock acquisition on --refresh-completion-cache path

AC-FUNC-005: kanon doctor --refresh-completion-cache wraps cache mutation
in kanon_workspace_lock.
"""

import argparse
import pathlib

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_refresh_args(
    kanon_file: str | None = None,
    refresh_completion_cache: bool = False,
) -> argparse.Namespace:
    """Construct a Namespace matching what argparse would produce for 'kanon doctor'.

    Args:
        kanon_file: Path to the .kanon file, or None to use the default.
        refresh_completion_cache: Whether --refresh-completion-cache was passed.

    Returns:
        Namespace instance suitable for passing to run_doctor.
    """
    return argparse.Namespace(
        kanon_file=kanon_file,
        refresh_completion_cache=refresh_completion_cache,
    )


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDoctorSubparser:
    """register() adds a 'doctor' subparser with the required arguments."""

    def test_register_creates_doctor_subparser(self) -> None:
        """register() creates a 'doctor' subparser with the expected name."""
        from kanon_cli.commands.doctor import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["doctor"])
        assert args.command == "doctor"

    def test_refresh_completion_cache_flag_exists(self) -> None:
        """The 'doctor' subcommand accepts --refresh-completion-cache."""
        from kanon_cli.commands.doctor import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["doctor", "--refresh-completion-cache"])
        assert args.refresh_completion_cache is True

    def test_refresh_completion_cache_default_false(self) -> None:
        """--refresh-completion-cache defaults to False when not supplied."""
        from kanon_cli.commands.doctor import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["doctor"])
        assert args.refresh_completion_cache is False

    def test_doctor_sets_run_doctor_as_func(self) -> None:
        """The 'doctor' subcommand sets args.func to run_doctor.

        run_doctor is the registered CLI entrypoint for 'kanon doctor'. It
        handles --refresh-completion-cache first, then delegates to
        doctor_command for all other (health-check) invocations.
        """
        from kanon_cli.commands.doctor import register, run_doctor

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        args = parser.parse_args(["doctor"])
        assert args.func is run_doctor

    # NOTE: test_doctor_registered_in_top_level_cli is intentionally omitted here.
    # Registering 'doctor' in the top-level cli.py (build_parser) is owned by the
    # task that also owns src/kanon_cli/cli.py (currently claimed by E4-F1-S1-T1 and
    # others via PRE_CONFLICT).  The integration between register() and the live
    # top-level parser will be verified by whichever task lands that registration.


# ---------------------------------------------------------------------------
# run_doctor -- workspace lock acquisition on --refresh-completion-cache
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunDoctorRefreshCompletionCache:
    """run_doctor --refresh-completion-cache wraps mutation in kanon_workspace_lock."""

    def test_refresh_creates_completion_cache_dir(self, tmp_path: pathlib.Path) -> None:
        """--refresh-completion-cache creates .kanon-data/completion-cache/.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        args = _make_refresh_args(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        result = run_doctor(args)

        assert result == 0
        cache_dir = tmp_path / ".kanon-data" / "completion-cache"
        assert cache_dir.is_dir(), f"run_doctor --refresh-completion-cache must create {cache_dir}"

    def test_refresh_creates_kanon_data_dir(self, tmp_path: pathlib.Path) -> None:
        """--refresh-completion-cache creates .kanon-data/ via workspace lock.

        The kanon_workspace_lock context manager creates .kanon-data/ eagerly
        before acquiring the lock. A fresh workspace with no prior .kanon-data/
        must end up with the directory after run_doctor --refresh-completion-cache.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        assert not (tmp_path / ".kanon-data").exists()

        args = _make_refresh_args(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        run_doctor(args)

        assert (tmp_path / ".kanon-data").is_dir(), (
            "run_doctor --refresh-completion-cache must create .kanon-data/ "
            "as a side effect of kanon_workspace_lock eager-create"
        )

    def test_refresh_prints_confirmation(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """--refresh-completion-cache prints a confirmation message to stdout.

        Args:
            tmp_path: Pytest-provided temporary directory.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        args = _make_refresh_args(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        run_doctor(args)

        captured = capsys.readouterr()
        assert "completion cache" in captured.out.lower(), (
            "run_doctor --refresh-completion-cache must print a confirmation "
            f"mentioning 'completion cache'. stdout: {captured.out!r}"
        )

    @pytest.mark.parametrize(
        "kanon_file_rel",
        [".kanon", "subdir/.kanon"],
        ids=["root", "subdir"],
    )
    def test_refresh_resolves_workspace_root_from_kanon_file(self, tmp_path: pathlib.Path, kanon_file_rel: str) -> None:
        """--refresh-completion-cache resolves workspace root from the kanon file path.

        The workspace root is the parent directory of the .kanon file. The lock
        and completion-cache dir are created relative to this root, not the cwd.

        Args:
            tmp_path: Pytest-provided temporary directory.
            kanon_file_rel: Relative path of the .kanon file inside tmp_path.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / kanon_file_rel
        kanon_file.parent.mkdir(parents=True, exist_ok=True)
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        expected_workspace = kanon_file.resolve().parent

        args = _make_refresh_args(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        run_doctor(args)

        assert (expected_workspace / ".kanon-data" / "completion-cache").is_dir(), (
            f"completion-cache must be at {expected_workspace}/.kanon-data/completion-cache"
        )


# ---------------------------------------------------------------------------
# run_doctor -- no-flag health check path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunDoctorHealthChecks:
    """run_doctor without flags runs non-mutating health checks."""

    def test_health_check_returns_0_when_kanon_exists(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run_doctor returns 0 when a .kanon file exists at the workspace root.

        Args:
            tmp_path: Pytest-provided temporary directory.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        args = _make_refresh_args(kanon_file=str(kanon_file))
        result = run_doctor(args)

        assert result == 0

    def test_health_check_exits_nonzero_when_kanon_missing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run_doctor returns non-zero when no .kanon file is found.

        Args:
            tmp_path: Pytest-provided temporary directory.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import run_doctor

        # Use a .kanon file path that does not exist.
        missing_kanon = tmp_path / ".kanon"
        args = _make_refresh_args(kanon_file=str(missing_kanon))

        result = run_doctor(args)

        assert result != 0
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err

    def test_health_check_does_not_create_kanon_data(self, tmp_path: pathlib.Path) -> None:
        """run_doctor (no flags) does not create .kanon-data/.

        The health check path is non-mutating and does not acquire the workspace
        lock, so .kanon-data/ must not be created as a side effect.

        Args:
            tmp_path: Pytest-provided temporary directory.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        args = _make_refresh_args(kanon_file=str(kanon_file))
        run_doctor(args)

        assert not (tmp_path / ".kanon-data").exists(), (
            "run_doctor (no flags) must not create .kanon-data/; "
            "the health check path is non-mutating and does not acquire the workspace lock"
        )

    def test_health_check_prints_workspace_ok(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """run_doctor (no flags, no lockfile) prints an INFO notice to stderr.

        When .kanon is present but no .kanon.lock exists, run_doctor routes
        through doctor_command which emits an INFO notice to stderr indicating
        that no lockfile is present. The 'workspace OK' message no longer
        applies once the new consistency subchecks are wired in.

        Args:
            tmp_path: Pytest-provided temporary directory.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_src_URL=https://example.com/org/repo.git\n"
            "KANON_SOURCE_src_REVISION=main\n"
            "KANON_SOURCE_src_PATH=repo-specs/meta.xml\n"
            "KANON_MARKETPLACE_INSTALL=false\n",
            encoding="utf-8",
        )
        kanon_file.chmod(0o644)

        args = _make_refresh_args(kanon_file=str(kanon_file))
        result = run_doctor(args)

        assert result == 0
        captured = capsys.readouterr()
        # When no lockfile is present, doctor_command emits an INFO notice to stderr.
        assert "No lockfile present" in captured.err, (
            f"run_doctor (no flags, no lockfile) must emit an INFO notice to stderr. stderr: {captured.err!r}"
        )

    def test_health_check_reports_kanon_data_exists(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run_doctor (no flags, no lockfile) prints INFO stderr notice about no lockfile.

        When .kanon is present (and .kanon-data/ exists) but no .kanon.lock,
        run_doctor delegates to doctor_command which emits an INFO stderr notice.
        The test confirms the notice is present and the return code is 0.

        Args:
            tmp_path: Pytest-provided temporary directory.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_src_URL=https://example.com/org/repo.git\n"
            "KANON_SOURCE_src_REVISION=main\n"
            "KANON_SOURCE_src_PATH=repo-specs/meta.xml\n"
            "KANON_MARKETPLACE_INSTALL=false\n",
            encoding="utf-8",
        )
        kanon_file.chmod(0o644)
        (tmp_path / ".kanon-data").mkdir()

        args = _make_refresh_args(kanon_file=str(kanon_file))
        result = run_doctor(args)

        assert result == 0
        captured = capsys.readouterr()
        # When no lockfile is present, doctor_command emits an INFO stderr notice.
        assert "No lockfile present" in captured.err, (
            f"run_doctor must emit INFO notice when no lockfile exists. stderr: {captured.err!r}"
        )

    def test_kanon_file_resolved_from_env_var(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When args.kanon_file is None, the KANON_KANON_FILE env var is used.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatching fixture.
        """
        from kanon_cli.commands.doctor import run_doctor
        from kanon_cli.constants import KANON_KANON_FILE_ENV

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        monkeypatch.setenv(KANON_KANON_FILE_ENV, str(kanon_file))
        args = _make_refresh_args(kanon_file=None)
        result = run_doctor(args)

        assert result == 0

    def test_kanon_file_falls_back_to_default_when_no_env_var(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When args.kanon_file is None and env var is unset, the default is used.

        The default is KANON_KANON_FILE_DEFAULT (typically '.kanon'). This test
        creates that file in a temp dir and changes cwd so the default path
        resolves correctly.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatching fixture.
        """
        import os

        from kanon_cli.commands.doctor import run_doctor
        from kanon_cli.constants import KANON_KANON_FILE_DEFAULT, KANON_KANON_FILE_ENV

        # Ensure env var is not set so we exercise the default-fallback branch.
        monkeypatch.delenv(KANON_KANON_FILE_ENV, raising=False)

        kanon_file = tmp_path / KANON_KANON_FILE_DEFAULT
        kanon_file.parent.mkdir(parents=True, exist_ok=True)
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        args = _make_refresh_args(kanon_file=None)
        result = run_doctor(args)

        assert result == 0
        monkeypatch.chdir(os.getcwd())


# ---------------------------------------------------------------------------
# _refresh_completion_cache -- error path (OSError on mkdir)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRefreshCompletionCacheErrors:
    """_refresh_completion_cache exits non-zero on OSError from mkdir."""

    def test_refresh_exits_nonzero_on_mkdir_oserror(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """_refresh_completion_cache prints an error and exits 1 when mkdir raises OSError.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatching fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        import pathlib

        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        original_mkdir = pathlib.Path.mkdir

        def _failing_mkdir(self: pathlib.Path, **kwargs: object) -> None:
            if "completion-cache" in str(self):
                raise OSError(13, "Permission denied")
            original_mkdir(self, **kwargs)

        monkeypatch.setattr(pathlib.Path, "mkdir", _failing_mkdir)

        args = _make_refresh_args(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )

        with pytest.raises(SystemExit) as exc_info:
            run_doctor(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
