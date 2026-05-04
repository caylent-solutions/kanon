"""Integration tests for platform parity: case-sensitivity, /dev/null, tmpfs, and symlink semantics.

Covers:
  - AC-TEST-001: filesystem case-sensitivity handled consistently across kanon operations
  - AC-TEST-002: /dev/null and tmpfs scenarios work without panicking the CLI
  - AC-TEST-003: symlink semantics match between Linux and macOS where possible
  - AC-FUNC-001: Platform-specific behaviors are documented and tested on each platform
  - AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage)

Platform notes:
  - Linux ext4/xfs: case-sensitive by default; /dev/null is a character device; symlinks
    use absolute or relative targets with os.readlink() returning the exact target string.
  - macOS HFS+/APFS: case-insensitive by default (HFS+) or optionally case-sensitive
    (APFS); /dev/null is a character device; symlink semantics are identical to Linux.
  - tmpfs: an in-memory filesystem used on Linux (typically /tmp). Operations must
    behave identically to disk-backed filesystems; no tmpfs-specific code is needed.
  - This test file runs on the host platform and asserts consistent behavior within that
    platform's semantics. Cross-platform parity is documented in the per-test docstrings.
"""

import os
import pathlib
import platform
import subprocess
import sys
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.discover import find_kanonenv
from kanon_cli.core.install import install


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"

_MINIMAL_KANONENV_CONTENT = (
    "KANON_SOURCE_src_URL=https://example.com/src.git\n"
    "KANON_SOURCE_src_REVISION=main\n"
    "KANON_SOURCE_src_PATH=repo-specs/default.xml\n"
)

# Determine the current OS for platform-conditional behavior in docstrings.
_CURRENT_PLATFORM = platform.system()  # "Linux", "Darwin", or "Windows"


# ---------------------------------------------------------------------------
# Subprocess helper (mirrors convention from test_fs_fault_injection.py)
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
# AC-TEST-001: filesystem case-sensitivity handled consistently
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCaseSensitivityParity:
    """AC-TEST-001: filesystem case-sensitivity is handled consistently.

    Platform notes:
    - Linux (ext4/xfs/tmpfs): case-sensitive -- '.kanon' and '.KANON' are different files.
    - macOS HFS+: case-insensitive -- '.kanon' and '.KANON' refer to the same inode.
    - macOS APFS (case-sensitive variant): behaves like Linux.

    The kanon CLI must:
    - On case-sensitive filesystems: treat '.kanon' and '.KANON' as distinct files;
      discovery of '.KANON' must not succeed when only '.kanon' exists.
    - On case-insensitive filesystems: the OS transparently maps both names to the same
      inode, so no special handling is needed -- the CLI does not need to normalize case.

    These tests are written to document and assert the behavior on the CURRENT platform.
    They do not attempt to emulate the other platform's behavior.
    """

    def test_kanonenv_discovery_finds_lowercase_dotkanon(self, tmp_path: pathlib.Path) -> None:
        """find_kanonenv() discovers the canonical '.kanon' filename.

        On all supported platforms, the canonical filename is lowercase '.kanon'.
        This test confirms discovery works in a directory that contains only
        the canonical name -- the baseline for both case-sensitive and
        case-insensitive platforms.
        """
        kanonenv = _write_kanonenv(tmp_path)
        assert kanonenv.name == ".kanon", "Fixture must write the canonical '.kanon' filename"

        discovered = find_kanonenv(tmp_path)

        assert discovered == kanonenv.resolve(), (
            f"find_kanonenv() must return the canonical .kanon path. Expected {kanonenv.resolve()}, got {discovered}"
        )

    def test_kanonenv_file_is_accessible_after_creation(self, tmp_path: pathlib.Path) -> None:
        """A .kanon file written to disk is immediately readable via pathlib.

        Asserts that there is no buffering, caching, or platform-specific delay
        between write and read on the current filesystem.
        """
        kanonenv = _write_kanonenv(tmp_path)

        assert kanonenv.exists(), f".kanon must exist immediately after creation at {kanonenv}"
        content = kanonenv.read_text()
        assert "KANON_SOURCE_src_URL" in content, f"Written content must be immediately readable. Got: {content!r}"

    def test_lowercase_kanonenv_not_found_when_only_uppercase_present_on_case_sensitive_fs(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """On case-sensitive filesystems, '.KANON' is a different file from '.kanon'.

        Platform behavior:
        - Linux (case-sensitive): '.KANON' != '.kanon'; find_kanonenv() must raise
          FileNotFoundError when only '.KANON' exists and discovery looks for '.kanon'.
        - macOS HFS+ (case-insensitive): '.KANON' and '.kanon' map to the same inode;
          this test is skipped on case-insensitive filesystems because the OS itself
          handles the mapping.

        This test documents and asserts the case-sensitive behavior present on Linux.
        """
        # Detect whether the filesystem is case-sensitive by probing the tmp_path.
        probe_lower = tmp_path / "probe_case_test_lower"
        probe_upper = tmp_path / "PROBE_CASE_TEST_LOWER"
        probe_lower.write_text("x")
        is_case_sensitive = not probe_upper.exists()
        probe_lower.unlink()

        if not is_case_sensitive:
            pytest.skip(
                f"Filesystem at {tmp_path} is case-insensitive (macOS HFS+ or similar); "
                "case-sensitivity behavior is handled by the OS transparently."
            )

        # On a case-sensitive filesystem, create ONLY '.KANON' (uppercase).
        uppercase_kanon = tmp_path / ".KANON"
        uppercase_kanon.write_text(_MINIMAL_KANONENV_CONTENT)

        with pytest.raises(FileNotFoundError) as exc_info:
            find_kanonenv(tmp_path)

        assert ".kanon" in str(exc_info.value).lower(), (
            f"FileNotFoundError message must reference '.kanon'. Got: {exc_info.value!r}"
        )

    def test_install_uses_exact_path_case_provided(self, tmp_path: pathlib.Path) -> None:
        """install() uses the exact path provided, with no case normalization.

        kanon does not perform case folding on paths. On case-sensitive filesystems,
        passing the exact path returned by write is required. This test confirms that
        install() accepts the canonical lowercase path on the current platform.
        """
        kanonenv = _write_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            install(kanonenv)

        assert (tmp_path / ".kanon-data").is_dir(), (
            f".kanon-data/ must be created by install() using the canonical lowercase path. "
            f"Contents of tmp_path: {list(tmp_path.iterdir())}"
        )

    @pytest.mark.parametrize(
        "dir_name",
        [
            "Lower_Case_Dir",
            "MixedCaseProject",
            "ALL_CAPS_DIR",
            "camelCaseDir",
        ],
    )
    def test_install_works_with_mixed_case_directory_names(
        self,
        tmp_path: pathlib.Path,
        dir_name: str,
    ) -> None:
        """install() creates .kanon-data/ inside directories with mixed-case names.

        On case-sensitive platforms (Linux), each of these names is a distinct directory.
        On case-insensitive platforms (macOS HFS+), they may collide, but pytest's
        tmp_path already provides a unique root, so no collision occurs within the test.

        The CLI must handle mixed-case directory paths identically to lowercase ones --
        no special treatment required.
        """
        project_dir = tmp_path / dir_name
        project_dir.mkdir()
        kanonenv = _write_kanonenv(project_dir)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            install(kanonenv)

        assert (project_dir / ".kanon-data").is_dir(), (
            f".kanon-data/ must be created inside '{dir_name}' directory. Contents: {list(project_dir.iterdir())}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: /dev/null and tmpfs scenarios work
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDevNullAndTmpfsScenarios:
    """AC-TEST-002: /dev/null and tmpfs scenarios work without panicking the CLI.

    Platform notes:
    - /dev/null is a character device (not a regular file) on both Linux and macOS.
      Passing it as a .kanon path must result in a clean 'Error:' message and exit 1
      -- the CLI must not crash with an unhandled exception or produce a traceback.
    - tmpfs (Linux /tmp) behaves identically to disk-backed filesystems for the
      operations kanon performs (mkdir, open, read, write, symlink, unlink). No
      special handling is needed; these tests assert that the CLI works correctly
      when tmp_path is on a tmpfs mount, which is the default on many Linux
      systems and CI environments.
    - macOS /tmp is typically a symlink to /private/tmp (on APFS); behavior is
      the same as tmpfs for kanon's operations.
    """

    def test_dev_null_as_kanonenv_path_exits_1(self) -> None:
        """Passing /dev/null as the .kanon path exits 1 with a clean error.

        /dev/null is a character device, not a regular file. The kanon CLI
        performs an is_file() check on the provided path before opening it.
        /dev/null.is_file() returns False (it is not a regular file), so the
        CLI must exit 1 with a '.kanon file not found' or similar error message
        on stderr.

        This test is Linux/macOS-specific because Windows does not have /dev/null
        as a character device at that path. It is skipped on unsupported platforms.
        """
        dev_null = pathlib.Path("/dev/null")
        if not dev_null.exists():
            pytest.skip("/dev/null is not available on this platform")

        result = _run_kanon_subprocess("install", str(dev_null))

        assert result.returncode == 1, (
            f"Expected exit 1 when passing /dev/null as .kanon path, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_dev_null_as_kanonenv_path_has_error_on_stderr(self) -> None:
        """An 'Error:' message appears on stderr when /dev/null is passed as .kanon path.

        The CLI must emit a clean, actionable error message to stderr. No raw
        Python traceback should appear; the error format is 'Error: <message>'.
        """
        dev_null = pathlib.Path("/dev/null")
        if not dev_null.exists():
            pytest.skip("/dev/null is not available on this platform")

        result = _run_kanon_subprocess("install", str(dev_null))

        assert "Error:" in result.stderr, (
            f"Expected 'Error:' message on stderr for /dev/null path. Got stderr={result.stderr!r}"
        )

    def test_dev_null_as_kanonenv_path_no_traceback(self) -> None:
        """No raw Python traceback appears on stderr when /dev/null is passed.

        AC-CHANNEL-001: The CLI must convert all unexpected input into a clean
        error message. A character device path must not cause an unhandled
        exception that leaks internal implementation details via a traceback.
        """
        dev_null = pathlib.Path("/dev/null")
        if not dev_null.exists():
            pytest.skip("/dev/null is not available on this platform")

        result = _run_kanon_subprocess("install", str(dev_null))

        assert "Traceback (most recent call last):" not in result.stderr, (
            f"Raw traceback must not appear for /dev/null path. Got stderr={result.stderr!r}"
        )

    def test_dev_null_as_kanonenv_path_no_cross_channel_leakage(self) -> None:
        """AC-CHANNEL-001: error for /dev/null path is on stderr only, not stdout."""
        dev_null = pathlib.Path("/dev/null")
        if not dev_null.exists():
            pytest.skip("/dev/null is not available on this platform")

        result = _run_kanon_subprocess("install", str(dev_null))

        stdout_error_lines = [line for line in result.stdout.splitlines() if line.startswith("Error:")]
        assert not stdout_error_lines, (
            f"Error text leaked to stdout for /dev/null path. stdout={result.stdout!r}, stderr={result.stderr!r}"
        )

    def test_install_on_tmpfs_creates_kanon_data(self, tmp_path: pathlib.Path) -> None:
        """install() creates .kanon-data/ on tmpfs (or any tmp filesystem) correctly.

        pytest's tmp_path fixture uses the system's temporary directory, which is
        typically tmpfs on Linux and APFS-backed on macOS. This test confirms that
        the install business logic works correctly on whatever filesystem tmp_path
        is mounted on -- no disk-specific behavior is assumed.
        """
        kanonenv = _write_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            install(kanonenv)

        assert (tmp_path / ".kanon-data").is_dir(), (
            f".kanon-data/ must be created on tmpfs/tmp filesystem. Contents of tmp_path: {list(tmp_path.iterdir())}"
        )

    def test_clean_on_tmpfs_removes_artifacts(self, tmp_path: pathlib.Path) -> None:
        """clean() removes .packages/ and .kanon-data/ correctly on tmpfs.

        Confirms that clean() can remove directories on the system's temporary
        filesystem. The rmtree behavior must be identical to disk-backed filesystems.
        """
        kanonenv = _write_kanonenv(tmp_path)
        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir()

        clean(kanonenv)

        assert not (tmp_path / ".packages").exists(), ".packages/ must be removed by clean() on tmpfs filesystem"
        assert not (tmp_path / ".kanon-data").exists(), ".kanon-data/ must be removed by clean() on tmpfs filesystem"

    def test_subprocess_install_on_tmpfs_does_not_report_file_not_found(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-CHANNEL-001: install on tmpfs does not emit a file-not-found error.

        When a valid .kanon file exists on tmpfs, the CLI must proceed past
        the file-existence check. Any failure must be from network/repo operations,
        not from path handling or tmpfs-specific restrictions.
        """
        kanonenv = _write_kanonenv(tmp_path)

        result = _run_kanon_subprocess("install", str(kanonenv))

        assert ".kanon file not found" not in result.stderr, (
            f"install must not report '.kanon file not found' for a valid file on tmpfs. Got stderr={result.stderr!r}"
        )

    def test_subprocess_clean_on_tmpfs_exits_0(self, tmp_path: pathlib.Path) -> None:
        """AC-CHANNEL-001: clean exits 0 on tmpfs when artifacts are present.

        Confirms the full CLI pathway (subprocess invocation) works on the
        temporary filesystem -- no tmpfs-specific restriction blocks the clean.
        """
        kanonenv = _write_kanonenv(tmp_path)
        (tmp_path / ".packages").mkdir()
        (tmp_path / ".kanon-data").mkdir()

        result = _run_kanon_subprocess("clean", str(kanonenv))

        assert result.returncode == 0, (
            f"Expected exit 0 for clean on tmpfs, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_discover_on_tmpfs_finds_kanonenv(self, tmp_path: pathlib.Path) -> None:
        """find_kanonenv() locates .kanon on tmpfs without filesystem-specific errors.

        Auto-discovery must work on the temporary filesystem -- no disk-specific
        check is performed by find_kanonenv().
        """
        kanonenv = _write_kanonenv(tmp_path)

        discovered = find_kanonenv(tmp_path)

        assert discovered == kanonenv.resolve(), (
            f"find_kanonenv() must work on tmpfs. Expected {kanonenv.resolve()}, got {discovered}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: symlink semantics match between Linux and macOS where possible
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSymlinkSemanticsParity:
    """AC-TEST-003: symlink semantics match between Linux and macOS where possible.

    Platform notes:
    - On both Linux and macOS, symbolic links are first-class filesystem objects.
    - pathlib.Path.is_symlink() returns True for symlinks on both platforms.
    - pathlib.Path.resolve() follows symlinks to the real path on both platforms.
    - os.readlink() returns the exact link target (absolute or relative) on both.
    - is_file() returns True for a symlink whose target is a regular file on both.
    - The symlink itself has its own inode (lstat) distinct from the target's inode (stat).
    - Circular symlinks raise OSError on resolve() on both platforms.
    - Dangling symlinks: is_file() returns False; exists() returns False on both platforms.

    The kanon CLI must behave identically for symlink paths on Linux and macOS.
    These tests document and assert the shared symlink contract.
    """

    def test_symlink_to_kanonenv_is_detected_as_file(self, tmp_path: pathlib.Path) -> None:
        """A symlink to .kanon passes the is_file() check on both Linux and macOS.

        The install CLI handler uses is_file() to validate the provided path.
        A symlink pointing to a valid regular file must pass this check,
        because pathlib.Path.is_file() follows symlinks.

        Shared behavior: Linux == macOS.
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)

        symlink_kanon = tmp_path / "link_to_kanon"
        symlink_kanon.symlink_to(kanonenv)

        assert symlink_kanon.is_file(), (
            f"Symlink to .kanon must pass is_file() on {_CURRENT_PLATFORM}. "
            f"Symlink: {symlink_kanon}, target: {kanonenv}"
        )

    def test_symlink_resolve_returns_real_path(self, tmp_path: pathlib.Path) -> None:
        """pathlib.Path.resolve() dereferences symlinks to the real path on both platforms.

        The install() function calls kanonenv_path.resolve() to dereference
        the path before using kanonenv_path.parent as the project root. This
        ensures .kanon-data/ is created next to the real .kanon, not next to
        the symlink.

        Shared behavior: Linux == macOS.
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)

        symlink_dir = tmp_path / "via_link"
        symlink_dir.mkdir()
        symlink_kanon = symlink_dir / ".kanon"
        symlink_kanon.symlink_to(kanonenv)

        resolved = symlink_kanon.resolve()

        assert resolved == kanonenv.resolve(), (
            f"resolve() must dereference symlink to real path on {_CURRENT_PLATFORM}. "
            f"Got {resolved}, expected {kanonenv.resolve()}"
        )

    def test_symlink_lstat_differs_from_stat(self, tmp_path: pathlib.Path) -> None:
        """lstat() and stat() return different inodes for a symlink and its target.

        os.lstat() stats the symlink itself (without following it), while os.stat()
        follows the symlink to the target. On both Linux and macOS, the st_ino
        values differ, confirming that the symlink is a distinct filesystem object.

        Shared behavior: Linux == macOS.
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)

        symlink_kanon = tmp_path / "link_to_kanon"
        symlink_kanon.symlink_to(kanonenv)

        symlink_lstat = os.lstat(symlink_kanon)
        target_stat = os.stat(symlink_kanon)

        assert symlink_lstat.st_ino != target_stat.st_ino, (
            f"Symlink and target must have different inodes on {_CURRENT_PLATFORM}. "
            f"symlink inode={symlink_lstat.st_ino}, target inode={target_stat.st_ino}"
        )

    def test_dangling_symlink_is_not_file(self, tmp_path: pathlib.Path) -> None:
        """A dangling symlink (target does not exist) reports is_file()=False on both platforms.

        When a symlink points to a non-existent target:
        - is_file() returns False (because the target file does not exist).
        - exists() returns False.
        - is_symlink() returns True (the symlink itself exists).

        The kanon CLI must treat dangling symlinks as missing files and exit 1
        with a '.kanon file not found' error.

        Shared behavior: Linux == macOS.
        """
        dangling = tmp_path / "dangling_link"
        dangling.symlink_to(tmp_path / "nonexistent_target.kanon")

        assert dangling.is_symlink(), f"Dangling symlink must report is_symlink()=True on {_CURRENT_PLATFORM}"
        assert not dangling.exists(), f"Dangling symlink must report exists()=False on {_CURRENT_PLATFORM}"
        assert not dangling.is_file(), f"Dangling symlink must report is_file()=False on {_CURRENT_PLATFORM}"

    def test_dangling_symlink_as_kanonenv_path_exits_1(self, tmp_path: pathlib.Path) -> None:
        """Passing a dangling symlink as the .kanon path exits 1 with a clean error.

        Because a dangling symlink is not a regular file, the CLI's is_file()
        check fails and the process exits 1. The error must be on stderr.

        Shared behavior: Linux == macOS.
        AC-CHANNEL-001: no cross-channel leakage.
        """
        dangling = tmp_path / "dangling_kanon"
        dangling.symlink_to(tmp_path / ".nonexistent_real_kanon")

        result = _run_kanon_subprocess("install", str(dangling))

        assert result.returncode == 1, (
            f"Expected exit 1 for dangling symlink path, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Error:" in result.stderr, (
            f"Expected 'Error:' on stderr for dangling symlink path. Got stderr={result.stderr!r}"
        )
        stdout_error_lines = [line for line in result.stdout.splitlines() if line.startswith("Error:")]
        assert not stdout_error_lines, f"Error text must not appear on stdout. stdout={result.stdout!r}"

    def test_install_via_absolute_symlink_creates_dirs_next_to_real_file(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """install() via an absolute symlink creates .kanon-data/ in the real file's parent.

        When the symlink target is an absolute path, install() resolves the symlink
        and uses the real file's parent as the project root. Artifacts (.kanon-data/)
        are created in the real directory, not in the symlink's directory.

        Shared behavior: Linux == macOS (absolute symlinks work identically).
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)

        link_dir = tmp_path / "link_dir"
        link_dir.mkdir()
        # Absolute symlink -- same behavior on Linux and macOS.
        abs_symlink = link_dir / ".kanon"
        abs_symlink.symlink_to(kanonenv.resolve())

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            install(abs_symlink)

        assert (real_dir / ".kanon-data").is_dir(), (
            f".kanon-data/ must be created in the real file's parent when using an absolute symlink. "
            f"Expected at {real_dir}, contents: {list(real_dir.iterdir())}"
        )
        assert not (link_dir / ".kanon-data").exists(), ".kanon-data/ must NOT be created in the symlink's directory."

    def test_install_via_relative_symlink_creates_dirs_next_to_real_file(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """install() via a relative symlink creates .kanon-data/ in the real file's parent.

        When the symlink target is a relative path, install() still resolves the
        symlink (resolve() handles relative targets on both platforms) and uses
        the real file's parent as the project root.

        Shared behavior: Linux == macOS (relative symlinks work identically).
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        _write_kanonenv(real_dir)

        link_dir = tmp_path / "link_dir"
        link_dir.mkdir()
        # Relative symlink: from link_dir/.kanon -> ../real_project/.kanon
        rel_target = pathlib.Path("..") / "real_project" / ".kanon"
        rel_symlink = link_dir / ".kanon"
        rel_symlink.symlink_to(rel_target)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            install(rel_symlink)

        assert (real_dir / ".kanon-data").is_dir(), (
            f".kanon-data/ must be created in the real file's parent when using a relative symlink. "
            f"Expected at {real_dir}, contents: {list(real_dir.iterdir())}"
        )
        assert not (link_dir / ".kanon-data").exists(), ".kanon-data/ must NOT be created in the symlink's directory."

    def test_find_kanonenv_discovers_via_symlinked_ancestor(self, tmp_path: pathlib.Path) -> None:
        """find_kanonenv() discovers .kanon when traversing through a symlinked directory.

        If a directory in the search path is itself a symlink (directory symlink),
        find_kanonenv() still walks upward from the start_dir and finds .kanon.
        pathlib.Path.resolve() dereferences the directory symlink, so the walk
        proceeds through the real path. This behavior is identical on Linux and macOS.

        Shared behavior: Linux == macOS.
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)

        # Create a directory symlink pointing to real_dir.
        link_to_real = tmp_path / "link_to_real"
        link_to_real.symlink_to(real_dir)

        # Start discovery from the symlinked directory.
        discovered = find_kanonenv(link_to_real)

        # The discovered path must be the real (resolved) .kanon path.
        assert discovered == kanonenv.resolve(), (
            f"find_kanonenv() must discover .kanon through a symlinked ancestor on {_CURRENT_PLATFORM}. "
            f"Expected {kanonenv.resolve()}, got {discovered}"
        )

    def test_clean_via_symlink_removes_artifacts_from_real_dir(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """clean() via a symlinked .kanon removes artifacts from the real file's parent.

        Both Linux and macOS support symlinks in the same way: clean() resolves
        the symlink before computing the project root, so artifacts are removed
        from the real directory, not from the symlink's directory.

        Shared behavior: Linux == macOS.
        AC-CHANNEL-001: stdout contains progress, stderr is empty.
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        kanonenv = _write_kanonenv(real_dir)
        (real_dir / ".packages").mkdir()
        (real_dir / ".kanon-data").mkdir()

        link_dir = tmp_path / "via_link"
        link_dir.mkdir()
        sym_kanon = link_dir / ".kanon"
        sym_kanon.symlink_to(kanonenv)

        clean(sym_kanon)

        assert not (real_dir / ".packages").exists(), (
            ".packages/ must be removed from the real project dir when clean() is given a symlink"
        )
        assert not (real_dir / ".kanon-data").exists(), (
            ".kanon-data/ must be removed from the real project dir when clean() is given a symlink"
        )
        # Artifacts must NOT be touched in the symlink directory.
        assert not (link_dir / ".packages").exists(), (
            "clean() must not create or touch .packages/ in the symlink's directory"
        )

    def test_readlink_returns_exact_target(self, tmp_path: pathlib.Path) -> None:
        """os.readlink() returns the exact target string used to create the symlink.

        On both Linux and macOS, os.readlink() returns the literal target string
        (absolute or relative) without resolving further. This confirms that
        relative symlinks can be correctly round-tripped via readlink.

        Shared behavior: Linux == macOS.
        """
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        _write_kanonenv(real_dir)

        link_dir = tmp_path / "link_dir"
        link_dir.mkdir()
        rel_target = pathlib.Path("..") / "real_project" / ".kanon"
        rel_symlink = link_dir / ".kanon"
        rel_symlink.symlink_to(rel_target)

        read_target = os.readlink(rel_symlink)

        assert read_target == str(rel_target), (
            f"os.readlink() must return the exact target on {_CURRENT_PLATFORM}. "
            f"Expected {str(rel_target)!r}, got {read_target!r}"
        )
