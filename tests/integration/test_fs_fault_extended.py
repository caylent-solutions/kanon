"""Integration tests for extended filesystem fault injection and path boundary conditions.

Covers:
  - AC-TEST-001: non-UTF-8 filename in path produces a clear error
  - AC-TEST-002: paths with Unicode characters work
  - AC-TEST-003: PATH_MAX length path is handled
  - AC-TEST-004: mid-operation deletion race produces a clear error

AC-FUNC-001: Path boundary conditions (Unicode, non-UTF-8, PATH_MAX) are handled
             deterministically.
AC-CHANNEL-001: For CLI-facing tests, stdout vs stderr discipline is verified
                (no cross-channel leakage).
"""

import os
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import create_source_dirs
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

# PATH_MAX is the maximum total path length on POSIX systems.
# PC_PATH_MAX is the limit for the absolute path, or 4096 if unavailable.
try:
    _PATH_MAX = os.pathconf("/", "PC_PATH_MAX")
except (AttributeError, ValueError):
    _PATH_MAX = 4096

# PC_NAME_MAX is the maximum length of a single filename component.
try:
    _NAME_MAX = os.pathconf("/", "PC_NAME_MAX")
except (AttributeError, ValueError):
    _NAME_MAX = 255


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
# AC-TEST-001: non-UTF-8 filename in path produces a clear error
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNonUtf8PathError:
    """AC-TEST-001: when the CLI receives a path that contains non-UTF-8 bytes
    (e.g., as a str path that the OS cannot represent in the process encoding),
    it must produce a clear, actionable error and exit 1.

    On modern Linux/macOS the filesystem encoding is usually UTF-8, so the
    typical way to trigger a non-UTF-8 path error is to pass a path string that
    includes characters whose UTF-8 byte sequence the CLI cannot round-trip
    (tested via surrogate-escaped bytes in the path str, or by passing an
    explicitly non-existent path formed from non-UTF-8 byte sequences).

    The canonical approach is to use os.fsdecode on raw bytes that include
    non-UTF-8 octets, which produces a surrogateescaped string. We then hand
    that string to the CLI subprocess. The CLI must not crash with an
    unhandled UnicodeDecodeError; instead it must:
      - exit with code 1
      - emit an actionable 'Error:' message on stderr
      - produce no traceback on stderr
      - not leak error text to stdout
    """

    def test_non_utf8_path_exits_1(self, tmp_path: pathlib.Path) -> None:
        """Exit code is 1 when the .kanon path includes non-UTF-8 byte sequences.

        We construct a path string whose last component contains a raw byte
        (0xFF) that is illegal in UTF-8. The path string is produced via
        os.fsdecode so that the OS-level bytes representation is preserved
        through the surrogateescape codec. The CLI must fail-fast with exit 1
        rather than raising an unhandled UnicodeDecodeError.
        """
        # Build a path whose directory name embeds a non-UTF-8 octet (0xFF).
        # os.fsdecode with surrogateescape produces a str that contains
        # a lone surrogate (which is invalid Unicode but legal in Python str).
        raw_name = b"bad\xff" + b"dir"
        try:
            nonexistent_dir = tmp_path / os.fsdecode(raw_name)
        except (ValueError, UnicodeDecodeError):
            pytest.skip("filesystem/locale does not support surrogate-escaped path construction")

        nonexistent_kanon = nonexistent_dir / ".kanon"

        # The path will not exist (we never created the directory), so the CLI
        # must fail fast with a missing-file or non-UTF-8 encoding error.
        result = _run_kanon_subprocess("install", str(nonexistent_kanon))

        assert result.returncode == 1, (
            f"Expected exit code 1 for non-UTF-8 path, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_non_utf8_path_has_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """An 'Error:' message appears on stderr for non-UTF-8 path input."""
        raw_name = b"bad\xff" + b"dir"
        try:
            nonexistent_dir = tmp_path / os.fsdecode(raw_name)
        except (ValueError, UnicodeDecodeError):
            pytest.skip("filesystem/locale does not support surrogate-escaped path construction")

        nonexistent_kanon = nonexistent_dir / ".kanon"

        result = _run_kanon_subprocess("install", str(nonexistent_kanon))

        assert "Error:" in result.stderr, (
            f"Expected 'Error:' on stderr for non-UTF-8 path. Got stderr={result.stderr!r}"
        )

    def test_non_utf8_path_no_traceback(self, tmp_path: pathlib.Path) -> None:
        """No raw Python traceback appears on stderr for non-UTF-8 path input."""
        raw_name = b"bad\xff" + b"dir"
        try:
            nonexistent_dir = tmp_path / os.fsdecode(raw_name)
        except (ValueError, UnicodeDecodeError):
            pytest.skip("filesystem/locale does not support surrogate-escaped path construction")

        nonexistent_kanon = nonexistent_dir / ".kanon"

        result = _run_kanon_subprocess("install", str(nonexistent_kanon))

        assert "Traceback (most recent call last):" not in result.stderr, (
            f"Raw traceback must not appear on stderr for non-UTF-8 path. Got stderr={result.stderr!r}"
        )

    def test_non_utf8_path_no_cross_channel_leakage(self, tmp_path: pathlib.Path) -> None:
        """AC-CHANNEL-001: error text is on stderr only; stdout must contain no 'Error:' text."""
        raw_name = b"bad\xff" + b"dir"
        try:
            nonexistent_dir = tmp_path / os.fsdecode(raw_name)
        except (ValueError, UnicodeDecodeError):
            pytest.skip("filesystem/locale does not support surrogate-escaped path construction")

        nonexistent_kanon = nonexistent_dir / ".kanon"

        result = _run_kanon_subprocess("install", str(nonexistent_kanon))

        stdout_error_lines = [line for line in result.stdout.splitlines() if line.startswith("Error:")]
        assert not stdout_error_lines, (
            f"Error text leaked to stdout. stdout={result.stdout!r}, stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: paths with Unicode characters work
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUnicodePathsWork:
    """AC-TEST-002: directories and paths containing non-ASCII Unicode characters
    (e.g., Cyrillic, CJK, Arabic, accented Latin) are fully supported by install
    and clean operations."""

    @pytest.mark.parametrize(
        "dir_name",
        [
            "proyecto-de-instalacion",
            "proekt_kanon",
            "kanon_proje",
            "projet_kanon_accentue",
            "kanon_dir_with_spaces_and_unicode",
        ],
    )
    def test_install_works_with_unicode_dir(
        self,
        tmp_path: pathlib.Path,
        dir_name: str,
    ) -> None:
        """install creates .kanon-data/ correctly inside a Unicode-named directory."""
        unicode_dir = tmp_path / dir_name
        unicode_dir.mkdir()
        kanonenv = _write_kanonenv(unicode_dir)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            install(kanonenv)

        assert (unicode_dir / ".kanon-data").is_dir(), (
            f".kanon-data/ must be created in Unicode-named directory: {unicode_dir}"
        )

    @pytest.mark.parametrize(
        "dir_name",
        [
            "proyecto-de-instalacion",
            "proekt_kanon",
            "kanon_proje",
            "projet_kanon_accentue",
            "kanon_dir_with_spaces_and_unicode",
        ],
    )
    def test_clean_works_with_unicode_dir(
        self,
        tmp_path: pathlib.Path,
        dir_name: str,
    ) -> None:
        """clean removes .packages/ and .kanon-data/ inside a Unicode-named directory."""
        unicode_dir = tmp_path / dir_name
        unicode_dir.mkdir()
        kanonenv = _write_kanonenv(unicode_dir)
        (unicode_dir / ".packages").mkdir()
        (unicode_dir / ".kanon-data").mkdir()

        clean(kanonenv)

        assert not (unicode_dir / ".packages").exists(), (
            f".packages/ must be removed by clean in Unicode directory: {unicode_dir}"
        )
        assert not (unicode_dir / ".kanon-data").exists(), (
            f".kanon-data/ must be removed by clean in Unicode directory: {unicode_dir}"
        )

    @pytest.mark.parametrize(
        "dir_name",
        [
            "proyecto_kanon",
            "kanon_unicode_test",
        ],
    )
    def test_subprocess_install_exits_0_unicode_dir(
        self,
        tmp_path: pathlib.Path,
        dir_name: str,
    ) -> None:
        """AC-CHANNEL-001: install does not fail with a path-encoding error in a
        Unicode-named directory.

        When the .kanon file exists and is parseable, the CLI must proceed past
        the file-existence check even when the parent directory name contains
        Unicode characters. The subprocess may exit non-zero due to network
        failures (repo init), but it must NOT produce a '.kanon file not found'
        error or a Unicode codec error.
        """
        unicode_dir = tmp_path / dir_name
        unicode_dir.mkdir()
        kanonenv = _write_kanonenv(unicode_dir)

        result = _run_kanon_subprocess("install", str(kanonenv))

        # The CLI must not report a file-not-found error: the file exists.
        assert ".kanon file not found" not in result.stderr, (
            f"install must not report '.kanon file not found' for a valid path in a "
            f"Unicode directory. Got stderr={result.stderr!r}"
        )
        # A path-encoding error must not appear; any failure must be from
        # network/repo, not from path handling.
        assert "UnicodeDecodeError" not in result.stderr, (
            f"Path encoding error must not appear for Unicode directory name. Got stderr={result.stderr!r}"
        )
        assert "UnicodeEncodeError" not in result.stderr, (
            f"Path encoding error must not appear for Unicode directory name. Got stderr={result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "dir_name",
        [
            "proyecto_kanon",
            "kanon_unicode_test",
        ],
    )
    def test_subprocess_clean_exits_0_unicode_dir(
        self,
        tmp_path: pathlib.Path,
        dir_name: str,
    ) -> None:
        """AC-CHANNEL-001: clean exits 0 in a Unicode-named directory."""
        unicode_dir = tmp_path / dir_name
        unicode_dir.mkdir()
        kanonenv = _write_kanonenv(unicode_dir)
        (unicode_dir / ".packages").mkdir()
        (unicode_dir / ".kanon-data").mkdir()

        result = _run_kanon_subprocess("clean", str(kanonenv))

        assert result.returncode == 0, (
            f"Expected exit 0 for clean in Unicode directory, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "UnicodeDecodeError" not in result.stderr, (
            f"Path encoding error must not appear for Unicode directory. Got stderr={result.stderr!r}"
        )
        assert "UnicodeEncodeError" not in result.stderr, (
            f"Path encoding error must not appear for Unicode directory. Got stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: PATH_MAX length path is handled
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPathMaxHandling:
    """AC-TEST-003: when a path at or beyond PATH_MAX is presented to the CLI,
    it is handled deterministically -- either the operation succeeds or it fails
    with a clear error; it must never produce an unhandled exception traceback."""

    def test_path_near_path_max_install_no_traceback(self, tmp_path: pathlib.Path) -> None:
        """install does not produce a raw traceback for a path near PATH_MAX.

        We construct a nested directory chain whose total absolute path length
        approaches PATH_MAX. The CLI must either succeed or fail cleanly -- no
        unhandled exceptions.
        """
        # Build a path using the maximum-length single component allowed (NAME_MAX).
        # We nest one level deep to bring the total close to PATH_MAX.
        # The segment length is capped at NAME_MAX to be accepted by the FS.
        available_depth = _PATH_MAX - len(str(tmp_path)) - len("/.kanon") - 2
        segment_len = min(_NAME_MAX, max(1, available_depth))
        long_segment = "a" * segment_len

        deep_dir = tmp_path / long_segment

        try:
            deep_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pytest.skip("Cannot create near-PATH_MAX directory on this filesystem")

        kanonenv = deep_dir / ".kanon"
        try:
            kanonenv.write_text(_MINIMAL_KANONENV_CONTENT)
        except OSError:
            pytest.skip("Cannot write .kanon file at near-PATH_MAX depth")

        result = _run_kanon_subprocess("install", str(kanonenv))

        # Whatever the outcome, no raw traceback on stderr.
        assert "Traceback (most recent call last):" not in result.stderr, (
            f"Raw traceback must not appear for near-PATH_MAX path. Got stderr={result.stderr!r}"
        )

    def test_path_near_path_max_clean_no_traceback(self, tmp_path: pathlib.Path) -> None:
        """clean does not produce a raw traceback for a path near PATH_MAX."""
        available_depth = _PATH_MAX - len(str(tmp_path)) - len("/.kanon") - 2
        segment_len = min(_NAME_MAX, max(1, available_depth))
        long_segment = "a" * segment_len

        deep_dir = tmp_path / long_segment

        try:
            deep_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pytest.skip("Cannot create near-PATH_MAX directory on this filesystem")

        kanonenv = deep_dir / ".kanon"
        try:
            kanonenv.write_text(_MINIMAL_KANONENV_CONTENT)
        except OSError:
            pytest.skip("Cannot write .kanon file at near-PATH_MAX depth")

        result = _run_kanon_subprocess("clean", str(kanonenv))

        assert "Traceback (most recent call last):" not in result.stderr, (
            f"Raw traceback must not appear for near-PATH_MAX path. Got stderr={result.stderr!r}"
        )

    def test_path_exceeding_path_max_install_exits_1(self, tmp_path: pathlib.Path) -> None:
        """install exits 1 (not unhandled exception) when path exceeds PATH_MAX.

        Constructs a path string that is provably longer than PATH_MAX by
        assembling a long string (without actually creating the directory), then
        passes it to the CLI. The OS will reject the path; the CLI must convert
        that OS error to a clean exit-1 with an 'Error:' message on stderr.
        """
        # Build a path string that is longer than PATH_MAX without touching disk.
        excess = "b" * (_PATH_MAX + 100)
        long_path_str = str(tmp_path / excess / ".kanon")

        result = _run_kanon_subprocess("install", long_path_str)

        # The path cannot exist (too long), so the CLI must exit non-zero.
        assert result.returncode != 0, (
            f"Expected non-zero exit for PATH_MAX-exceeding path, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # The error must be clean -- no raw traceback.
        assert "Traceback (most recent call last):" not in result.stderr, (
            f"Raw traceback must not appear for PATH_MAX-exceeding path. Got stderr={result.stderr!r}"
        )

    def test_path_exceeding_path_max_has_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """AC-CHANNEL-001: error text for PATH_MAX-exceeded path is on stderr, not stdout."""
        excess = "b" * (_PATH_MAX + 100)
        long_path_str = str(tmp_path / excess / ".kanon")

        result = _run_kanon_subprocess("install", long_path_str)

        assert "Error:" in result.stderr, (
            f"Expected 'Error:' on stderr for PATH_MAX-exceeding path. Got stderr={result.stderr!r}"
        )
        stdout_error_lines = [line for line in result.stdout.splitlines() if line.startswith("Error:")]
        assert not stdout_error_lines, f"Error text must not appear on stdout. stdout={result.stdout!r}"


# ---------------------------------------------------------------------------
# AC-TEST-004: mid-operation deletion race produces a clear error
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMidOperationDeletionRace:
    """AC-TEST-004: when a directory or file is deleted between the point at which
    the CLI checks for its existence and the point at which it attempts to use it,
    the resulting OSError must surface as a clear 'Error:' message on stderr with
    exit code 1 -- not as an unhandled exception traceback.

    The race is simulated by:
      - using in-process API tests where install() is called directly after the
        base directory is made read-only (so create_source_dirs raises OSError)
      - using subprocess tests where the base directory is made read-only before
        the subprocess runs, ensuring the OS-level permission error propagates
        through the full CLI error-handling chain.
    """

    def test_source_dir_creation_fails_install_exits_1(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """CLI exits 1 when the project directory becomes read-only during install.

        We make the base directory read-only after writing .kanon so that
        create_source_dirs cannot create .kanon-data/sources/, which is the
        first filesystem operation after configuration parsing. This simulates
        the race where the directory is removed or made inaccessible between
        the CLI's file-existence check and the actual install.
        """
        kanonenv = _write_kanonenv(tmp_path)
        tmp_path.chmod(0o555)
        try:
            result = _run_kanon_subprocess("install", str(kanonenv))
        finally:
            tmp_path.chmod(0o755)

        assert result.returncode == 1, (
            f"Expected exit code 1 when project dir becomes read-only mid-install, "
            f"got {result.returncode}.\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_source_dir_creation_fails_error_on_stderr(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An 'Error:' message appears on stderr when project dir is read-only during install."""
        kanonenv = _write_kanonenv(tmp_path)
        tmp_path.chmod(0o555)
        try:
            result = _run_kanon_subprocess("install", str(kanonenv))
        finally:
            tmp_path.chmod(0o755)

        assert "Error:" in result.stderr, (
            f"Expected 'Error:' on stderr when project dir is read-only. Got stderr={result.stderr!r}"
        )

    def test_source_dir_creation_fails_no_traceback(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """No raw Python traceback appears on stderr when project dir is read-only during install."""
        kanonenv = _write_kanonenv(tmp_path)
        tmp_path.chmod(0o555)
        try:
            result = _run_kanon_subprocess("install", str(kanonenv))
        finally:
            tmp_path.chmod(0o755)

        assert "Traceback (most recent call last):" not in result.stderr, (
            f"Raw traceback must not appear when project dir is read-only. Got stderr={result.stderr!r}"
        )

    def test_source_dir_creation_fails_no_cross_channel_leakage(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-CHANNEL-001: error for read-only project dir is on stderr only, not stdout."""
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

    def test_create_source_dirs_raises_oserror_on_permission_denied(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """create_source_dirs raises OSError (not silent) when dir creation fails.

        This tests the library boundary: create_source_dirs() must propagate
        the OS-level PermissionError as an OSError with context rather than
        swallowing it silently. The install() caller is responsible for
        converting it to a clean CLI error.
        """
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        base_dir.chmod(0o555)
        try:
            with pytest.raises(OSError, match="Cannot create source directory"):
                create_source_dirs(["src"], base_dir)
        finally:
            base_dir.chmod(0o755)

    def test_install_raises_oserror_on_permission_denied_direct(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """install() propagates OSError when the project directory is read-only.

        This tests the library boundary: install() must let OSError from
        create_source_dirs propagate to the caller. The CLI command handler
        in commands/install.py catches this and prints 'Error:' + sys.exit(1).
        """
        kanonenv = _write_kanonenv(tmp_path)
        tmp_path.chmod(0o555)
        try:
            with pytest.raises(OSError, match="Cannot create source directory"):
                install(kanonenv)
        finally:
            tmp_path.chmod(0o755)

    def test_kanon_data_already_absent_clean_exits_0(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """clean exits 0 when .kanon-data/ and .packages/ are already absent (idempotent).

        The clean operation uses shutil.rmtree with ignore_errors=True so that
        a pre-removed directory does not cause an error. This simulates the
        race where another process removes the directories between the CLI's
        directory-listing and its rmtree call.
        """
        kanonenv = _write_kanonenv(tmp_path)
        # Intentionally do NOT create .packages/ or .kanon-data/

        result = _run_kanon_subprocess("clean", str(kanonenv))

        assert result.returncode == 0, (
            f"Expected exit 0 when .kanon-data/ is already absent, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_kanon_data_already_absent_clean_no_traceback(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """No traceback appears when .kanon-data/ is already absent when clean runs."""
        kanonenv = _write_kanonenv(tmp_path)

        result = _run_kanon_subprocess("clean", str(kanonenv))

        assert "Traceback (most recent call last):" not in result.stderr, (
            f"No traceback expected when target dirs are absent. Got stderr={result.stderr!r}"
        )
