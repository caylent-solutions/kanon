"""Unit tests for kanon_cli.commands.doctor.

Covers:
- Subparser registration structure
- run_doctor --refresh-completion-cache uses <KANON_HOME>/cache/completion-cache/
- run_doctor (no flags) health check paths

AC-FUNC-001: kanon doctor --refresh-completion-cache uses the KANON_HOME cache.
AC-FUNC-004: kanon doctor without flags does not mutate the cache.
"""

import argparse
import pathlib

import pytest


def _make_refresh_args(
    kanon_file: str | None = None,
    refresh_completion_cache: bool = False,
    prune_cache: bool = False,
) -> argparse.Namespace:
    """Construct a Namespace matching what argparse would produce for 'kanon doctor'.

    Args:
        kanon_file: Path to the .kanon file, or None to use the default.
        refresh_completion_cache: Whether --refresh-completion-cache was passed.
        prune_cache: Whether --prune-cache was passed.

    Returns:
        Namespace instance suitable for passing to run_doctor.
    """
    return argparse.Namespace(
        kanon_file=kanon_file,
        refresh_completion_cache=refresh_completion_cache,
        prune_cache=prune_cache,
    )


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

    def test_doctor_short_dash_h_exits_0(self) -> None:
        """kanon doctor -h exits 0 (add_help=True on the doctor subparser)."""
        from kanon_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["doctor", "-h"])
        assert exc_info.value.code == 0

    def test_doctor_subparser_has_add_help_true(self) -> None:
        """The 'doctor' subparser has add_help=True set explicitly."""
        from kanon_cli.commands.doctor import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)
        doctor_parser = subparsers.choices["doctor"]
        assert doctor_parser.add_help is True, "doctor subparser must have add_help=True so '-h' is accepted"


@pytest.mark.unit
class TestRunDoctorRefreshCompletionCache:
    """run_doctor --refresh-completion-cache invalidates <KANON_HOME>/cache/completion-cache/."""

    def test_refresh_creates_completion_cache_dir_under_cache_dir(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--refresh-completion-cache creates <KANON_HOME>/cache/completion-cache/ with mode 0700.

        The completion-cache subdir is created under the resolved KANON_HOME
        cache, not under .kanon-data/.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")
        monkeypatch.setenv("KANON_HOME", str(tmp_path))
        cache_dir = tmp_path / "cache"

        args = _make_refresh_args(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        result = run_doctor(args)

        assert result == 0
        completion_cache = cache_dir / "completion-cache"
        assert completion_cache.is_dir(), (
            f"--refresh-completion-cache must create <KANON_HOME>/cache/completion-cache/; expected {completion_cache}"
        )

    def test_refresh_targets_kanon_home_cache_not_cwd(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--refresh-completion-cache acts on the KANON_HOME cache, never on cwd/.kanon-data/.

        The cache always resolves under KANON_HOME (there is no unset state), so
        the refresh creates the completion-cache under <KANON_HOME>/cache and never
        beside the project .kanon.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_home = tmp_path / "home"
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setenv("KANON_HOME", str(kanon_home))
        kanon_file = project / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        args = _make_refresh_args(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        result = run_doctor(args)

        assert result == 0
        assert (kanon_home / "cache" / "completion-cache").is_dir(), (
            "--refresh-completion-cache must create the completion-cache under <KANON_HOME>/cache"
        )
        assert not (project / ".kanon-data").exists(), (
            "--refresh-completion-cache must not create .kanon-data/ beside the project .kanon"
        )

    def test_refresh_emits_info_finding_to_stderr(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--refresh-completion-cache emits an INFO: finding mentioning the cache.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest stdout/stderr capture fixture.
        """
        from kanon_cli.commands.doctor import run_doctor

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")
        monkeypatch.setenv("KANON_HOME", str(tmp_path))

        args = _make_refresh_args(
            kanon_file=str(kanon_file),
            refresh_completion_cache=True,
        )
        run_doctor(args)

        captured = capsys.readouterr()
        assert "INFO:" in captured.err, (
            f"run_doctor --refresh-completion-cache must emit an INFO: finding to stderr. stderr: {captured.err!r}"
        )
        assert "completion" in captured.err.lower(), (
            f"The INFO: finding must mention 'completion'. stderr: {captured.err!r}"
        )


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

        monkeypatch.delenv(KANON_KANON_FILE_ENV, raising=False)

        kanon_file = tmp_path / KANON_KANON_FILE_DEFAULT
        kanon_file.parent.mkdir(parents=True, exist_ok=True)
        kanon_file.write_text("KANON_MARKETPLACE_INSTALL=false\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        args = _make_refresh_args(kanon_file=None)
        result = run_doctor(args)

        assert result == 0
        monkeypatch.chdir(os.getcwd())


@pytest.mark.unit
class TestRefreshCompletionCacheErrors:
    """_refresh_completion_cache propagates OSError from mkdir."""

    def test_refresh_raises_on_mkdir_oserror(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_refresh_completion_cache raises OSError when mkdir fails.

        The helper propagates the OS-level error; callers decide how to handle it.
        The error is not swallowed silently.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatching fixture.
        """
        from kanon_cli.commands.doctor import _refresh_completion_cache

        cache_dir = tmp_path / "completion-cache"

        tmp_path.chmod(0o555)
        try:
            with pytest.raises(OSError):
                _refresh_completion_cache(cache_dir)
        finally:
            tmp_path.chmod(0o755)


@pytest.mark.unit
class TestDoctorImportsGitRunner:
    """doctor.py imports run_git_ls_remote from kanon_cli.core.git_runner (AC-4)."""

    def test_run_git_ls_remote_importable_from_doctor_module(self) -> None:
        """The run_git_ls_remote name is accessible via the doctor module namespace."""
        import kanon_cli.commands.doctor as doctor_mod

        assert hasattr(doctor_mod, "run_git_ls_remote")

    def test_doctor_has_no_time_sleep(self) -> None:
        """doctor.py source does not contain time.sleep calls (issue #64 / spec Section 3.5)."""
        import inspect

        import kanon_cli.commands.doctor as doctor_mod

        source = inspect.getsource(doctor_mod)
        assert "time.sleep" not in source, (
            "doctor.py must not contain time.sleep calls; use the event-driven retry in git_runner"
        )
