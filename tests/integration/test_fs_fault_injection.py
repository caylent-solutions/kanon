"""Integration tests for filesystem fault injection and path variation handling.

Covers:
  - AC-TEST-001: readonly parent directory exits 1 with permission error
  - AC-TEST-002: missing parent directory exits 1
  - AC-TEST-003: symlinked .kanon is followed correctly
  - AC-TEST-004: paths with spaces work throughout install/clean/validate

AC-FUNC-001: Filesystem faults surface actionable errors; successful cases handle
             common path variations.
AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage).
"""

import os
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import install


# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in source files)
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"

_MINIMAL_KANONENV_CONTENT = (
    "KANON_SOURCE_src_URL=https://example.com/src.git\n"
    "KANON_SOURCE_src_REVISION=main\n"
    "KANON_SOURCE_src_PATH=repo-specs/default.xml\n"
)


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_kanon_subprocess(
    *args: str,
    cwd: "pathlib.Path | None" = None,
    extra_env: "dict[str, str] | None" = None,
) -> subprocess.CompletedProcess:
    """Invoke kanon_cli in a subprocess and return the completed process.

    Ensures PYTHONPATH points at the current source tree so the subprocess
    uses the locally checked-out kanon_cli rather than any installed version.
    Sets REPO_TRACE=0 to suppress trace file writes during tests.

    Args:
        *args: CLI arguments passed after ``python -m kanon_cli``.
        cwd: Working directory for the subprocess. Defaults to None.
        extra_env: Additional environment variables merged on top of os.environ.

    Returns:
        The CompletedProcess object (check=False).
    """
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_str = str(_SRC_DIR)
    path_entries = [src_str] + [p for p in existing_pythonpath.split(os.pathsep) if p and p != src_str]
    env["PYTHONPATH"] = os.pathsep.join(path_entries)
    env.setdefault("REPO_TRACE", "0")
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
    )


def _write_kanonenv(directory: pathlib.Path) -> pathlib.Path:
    """Write a minimal .kanon file in directory and return its absolute path.

    Args:
        directory: Directory in which to create the .kanon file.

    Returns:
        Absolute path to the created .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(_MINIMAL_KANONENV_CONTENT)
    return kanonenv


# ---------------------------------------------------------------------------
# AC-TEST-001: readonly parent directory exits 1 with actionable error
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReadonlyParentDirectory:
    """AC-TEST-001: install into a read-only parent directory exits 1 with an
    actionable error message on stderr; no raw traceback; no output on stdout."""

    def test_readonly_parent_install_exits_1(self, tmp_path: pathlib.Path) -> None:
        """Exit code is 1 when the install destination directory is read-only."""
        kanonenv = _write_kanonenv(tmp_path)
        tmp_path.chmod(0o555)
        try:
            result = _run_kanon_subprocess("install", str(kanonenv))
        finally:
            tmp_path.chmod(0o755)

        assert result.returncode == 1, (
            f"Expected exit code 1 for read-only parent, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_readonly_parent_install_clean_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """An actionable 'Error:' message (not a raw traceback) appears on stderr."""
        kanonenv = _write_kanonenv(tmp_path)
        tmp_path.chmod(0o555)
        try:
            result = _run_kanon_subprocess("install", str(kanonenv))
        finally:
            tmp_path.chmod(0o755)

        # The error message must begin with 'Error:' for it to be an actionable message.
        stderr_lines = result.stderr.splitlines()
        error_lines = [line for line in stderr_lines if line.startswith("Error:")]
        assert error_lines, f"Expected at least one line starting with 'Error:' on stderr. Got stderr={result.stderr!r}"

    def test_readonly_parent_install_no_raw_traceback(self, tmp_path: pathlib.Path) -> None:
        """A raw Python traceback must NOT appear on stderr for read-only failures.

        The CLI must catch filesystem permission errors and emit a clean,
        actionable 'Error:' message rather than exposing internal stack frames.
        """
        kanonenv = _write_kanonenv(tmp_path)
        tmp_path.chmod(0o555)
        try:
            result = _run_kanon_subprocess("install", str(kanonenv))
        finally:
            tmp_path.chmod(0o755)

        assert "Traceback (most recent call last):" not in result.stderr, (
            f"Raw Python traceback must not appear on stderr for read-only parent directory. "
            f"Got stderr={result.stderr!r}"
        )

    def test_readonly_parent_install_error_mentions_path(self, tmp_path: pathlib.Path) -> None:
        """The error message must mention the affected path so the user can act on it."""
        kanonenv = _write_kanonenv(tmp_path)
        tmp_path.chmod(0o555)
        try:
            result = _run_kanon_subprocess("install", str(kanonenv))
        finally:
            tmp_path.chmod(0o755)

        assert str(tmp_path) in result.stderr, (
            f"Expected the affected path {tmp_path!r} to appear in stderr. Got stderr={result.stderr!r}"
        )

    def test_readonly_parent_install_no_cross_channel_leakage(self, tmp_path: pathlib.Path) -> None:
        """AC-CHANNEL-001: error text is on stderr only; stdout must contain no 'Error:' line."""
        kanonenv = _write_kanonenv(tmp_path)
        tmp_path.chmod(0o555)
        try:
            result = _run_kanon_subprocess("install", str(kanonenv))
        finally:
            tmp_path.chmod(0o755)

        stdout_error_lines = [line for line in result.stdout.splitlines() if line.startswith("Error:")]
        assert not stdout_error_lines, (
            f"Error text leaked to stdout. stdout={result.stdout!r}, stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: missing parent directory exits 1
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMissingParentDirectory:
    """AC-TEST-002: kanon install and clean with a .kanon path whose parent directory
    does not exist exit 1 with a clean error message on stderr."""

    @pytest.mark.parametrize(
        "subcommand",
        ["install", "clean"],
    )
    def test_missing_parent_dir_exits_1(
        self,
        tmp_path: pathlib.Path,
        subcommand: str,
    ) -> None:
        """Exit code is 1 when the parent directory of the .kanon path does not exist."""
        nonexistent = tmp_path / "does_not_exist" / ".kanon"
        result = _run_kanon_subprocess(subcommand, str(nonexistent))

        assert result.returncode == 1, (
            f"Expected exit code 1 for missing parent dir ({subcommand!r}), "
            f"got {result.returncode}.\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "subcommand",
        ["install", "clean"],
    )
    def test_missing_parent_dir_clean_error_on_stderr(
        self,
        tmp_path: pathlib.Path,
        subcommand: str,
    ) -> None:
        """A clean 'Error:' message appears on stderr, not a raw traceback."""
        nonexistent = tmp_path / "does_not_exist" / ".kanon"
        result = _run_kanon_subprocess(subcommand, str(nonexistent))

        stderr_lines = result.stderr.splitlines()
        error_lines = [line for line in stderr_lines if line.startswith("Error:")]
        assert error_lines, (
            f"Expected at least one line starting with 'Error:' on stderr ({subcommand!r}), "
            f"got stderr={result.stderr!r}"
        )
        assert "Traceback" not in result.stderr, (
            f"Raw traceback must not appear on stderr ({subcommand!r}). Got stderr={result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "subcommand",
        ["install", "clean"],
    )
    def test_missing_parent_dir_no_cross_channel_leakage(
        self,
        tmp_path: pathlib.Path,
        subcommand: str,
    ) -> None:
        """AC-CHANNEL-001: error text is on stderr only; stdout must contain no 'Error:' line."""
        nonexistent = tmp_path / "does_not_exist" / ".kanon"
        result = _run_kanon_subprocess(subcommand, str(nonexistent))

        stdout_error_lines = [line for line in result.stdout.splitlines() if line.startswith("Error:")]
        assert not stdout_error_lines, (
            f"Error text leaked to stdout ({subcommand!r}). stdout={result.stdout!r}, stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: symlinked .kanon is followed correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSymlinkedKanonFile:
    """AC-TEST-003: when the .kanon path is a symlink, the CLI resolves it and
    uses the resolved parent directory as the project root for artifact creation."""

    def test_symlink_kanon_is_recognized_as_file(self, tmp_path: pathlib.Path) -> None:
        """A symlink pointing to a valid .kanon file is treated as a valid file path."""
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)

        symlink_kanon = tmp_path / "link_to_kanon"
        symlink_kanon.symlink_to(kanonenv)

        # symlink.is_file() must return True for a symlink to an existing regular file.
        assert symlink_kanon.is_file(), f"Expected symlink {symlink_kanon} to report is_file()=True"
        # The resolved path must equal the real file.
        assert symlink_kanon.resolve() == kanonenv.resolve(), (
            f"Expected symlink to resolve to {kanonenv}, got {symlink_kanon.resolve()}"
        )

    def test_symlink_install_creates_dirs_next_to_real_file(self, tmp_path: pathlib.Path) -> None:
        """install creates .kanon-data/ relative to the resolved (real) .kanon location.

        When kanon install is given a symlink path, it resolves the symlink and
        creates all artifacts (e.g., .kanon-data/) relative to the real file's
        parent directory, not the symlink's parent directory.
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)

        symlink_dir = tmp_path / "via_symlink"
        symlink_dir.mkdir()
        symlink_kanon = symlink_dir / ".kanon"
        symlink_kanon.symlink_to(kanonenv)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            install(symlink_kanon)

        # .kanon-data/ must be created inside the real project directory (where .kanon lives),
        # not inside the directory where the symlink lives.
        assert (real_dir / ".kanon-data").is_dir(), (
            f".kanon-data/ expected next to real .kanon at {real_dir}, but was not found.\n"
            f"Contents of real_dir: {list(real_dir.iterdir())}\n"
            f"Contents of symlink_dir: {list(symlink_dir.iterdir())}"
        )
        assert not (symlink_dir / ".kanon-data").exists(), (
            ".kanon-data/ must not be created next to the symlink, only next to the real file."
        )

    def test_symlink_install_does_not_exit_with_file_not_found(self, tmp_path: pathlib.Path) -> None:
        """install does not reject a symlink path with a file-not-found error.

        A symlink that points to a valid .kanon file must pass the is_file()
        guard in the install CLI handler, so the operation proceeds past the
        file-existence check.
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)

        symlink_dir = tmp_path / "via_symlink"
        symlink_dir.mkdir()
        symlink_kanon = symlink_dir / ".kanon"
        symlink_kanon.symlink_to(kanonenv)

        result = _run_kanon_subprocess("install", str(symlink_kanon))

        # The error must NOT be a "file not found" error -- the symlink is valid.
        assert ".kanon file not found" not in result.stderr, (
            f"install must not report '.kanon file not found' for a valid symlink. Got stderr={result.stderr!r}"
        )

    def test_symlink_clean_follows_symlink_to_real_dir(self, tmp_path: pathlib.Path) -> None:
        """clean creates .packages/ and .kanon-data/ removal relative to the real file's parent.

        When kanon clean is given a symlink path, it resolves the symlink and
        removes artifacts from the real file's parent directory.
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)
        (real_dir / ".packages").mkdir()
        (real_dir / ".kanon-data").mkdir()

        symlink_dir = tmp_path / "via_symlink"
        symlink_dir.mkdir()
        symlink_kanon = symlink_dir / ".kanon"
        symlink_kanon.symlink_to(kanonenv)

        clean(symlink_kanon)

        assert not (real_dir / ".packages").exists(), (
            ".packages/ must be removed from the real project directory after clean via symlink"
        )
        assert not (real_dir / ".kanon-data").exists(), (
            ".kanon-data/ must be removed from the real project directory after clean via symlink"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: paths with spaces work throughout install/clean/validate
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPathsWithSpaces:
    """AC-TEST-004: directories and paths containing spaces are handled correctly
    in install and clean operations."""

    @pytest.fixture()
    def spaced_project(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """Create a .kanon file inside a directory whose name contains spaces.

        Returns:
            Path to the .kanon file inside the spaced directory.
        """
        spaced_dir = tmp_path / "my project with spaces"
        spaced_dir.mkdir()
        return _write_kanonenv(spaced_dir)

    def test_install_creates_kanon_data_with_space_in_path(
        self,
        spaced_project: pathlib.Path,
    ) -> None:
        """install creates .kanon-data/ correctly when the project path has spaces."""
        spaced_dir = spaced_project.parent

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            install(spaced_project)

        assert (spaced_dir / ".kanon-data").is_dir(), (
            f".kanon-data/ must be created inside directory with spaces: {spaced_dir}"
        )

    def test_install_creates_gitignore_with_space_in_path(
        self,
        spaced_project: pathlib.Path,
    ) -> None:
        """install creates .gitignore with correct entries when path has spaces."""
        spaced_dir = spaced_project.parent

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            install(spaced_project)

        gitignore = spaced_dir / ".gitignore"
        assert gitignore.is_file(), f".gitignore must be created inside directory with spaces: {spaced_dir}"
        content = gitignore.read_text()
        assert ".packages/" in content
        assert ".kanon-data/" in content

    def test_clean_removes_dirs_with_space_in_path(
        self,
        spaced_project: pathlib.Path,
    ) -> None:
        """clean removes .packages/ and .kanon-data/ when the project path has spaces."""
        spaced_dir = spaced_project.parent
        (spaced_dir / ".packages").mkdir()
        (spaced_dir / ".kanon-data").mkdir()

        clean(spaced_project)

        assert not (spaced_dir / ".packages").exists(), ".packages/ must be removed by clean even when path has spaces"
        assert not (spaced_dir / ".kanon-data").exists(), (
            ".kanon-data/ must be removed by clean even when path has spaces"
        )

    def test_clean_subprocess_exits_0_with_space_in_path(
        self,
        spaced_project: pathlib.Path,
    ) -> None:
        """AC-CHANNEL-001: clean succeeds and emits progress to stdout when path has spaces."""
        spaced_dir = spaced_project.parent
        (spaced_dir / ".packages").mkdir()
        (spaced_dir / ".kanon-data").mkdir()

        result = _run_kanon_subprocess("clean", str(spaced_project))

        assert result.returncode == 0, (
            f"Expected exit 0 for clean with spaces in path, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_clean_stdout_contains_progress_with_space_in_path(
        self,
        spaced_project: pathlib.Path,
    ) -> None:
        """AC-CHANNEL-001: clean progress output goes to stdout, not stderr."""
        spaced_dir = spaced_project.parent
        (spaced_dir / ".packages").mkdir()
        (spaced_dir / ".kanon-data").mkdir()

        result = _run_kanon_subprocess("clean", str(spaced_project))

        assert result.returncode == 0
        assert "kanon clean" in result.stdout, f"Expected 'kanon clean' progress on stdout. stdout={result.stdout!r}"
        assert not result.stderr, f"Expected empty stderr for successful clean. stderr={result.stderr!r}"

    def test_install_subprocess_error_on_missing_file_with_space_in_path(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-CHANNEL-001: install error message goes to stderr when path with spaces is missing."""
        spaced_dir = tmp_path / "my project with spaces"
        spaced_dir.mkdir()
        nonexistent_kanon = spaced_dir / ".kanon"
        # Do NOT create the .kanon file -- it must be missing.

        result = _run_kanon_subprocess("install", str(nonexistent_kanon))

        assert result.returncode == 1
        assert "Error:" in result.stderr, (
            f"Expected 'Error:' on stderr for missing .kanon in spaced path. Got stderr={result.stderr!r}"
        )
        assert "Error:" not in result.stdout, f"Error text must not appear on stdout. stdout={result.stdout!r}"
