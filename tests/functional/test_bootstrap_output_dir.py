"""Functional tests for kanon bootstrap --output-dir variations.

Covers:
- AC-TEST-001: --output-dir <absolute path> creates target files under that path
- AC-TEST-002: --output-dir with missing parent exits 1 with clear message
- AC-FUNC-001: --output-dir accepts both absolute and relative paths and resolves them consistently
- AC-CHANNEL-001: stdout vs stderr discipline verified (no cross-channel leakage)
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon


@pytest.mark.functional
class TestBootstrapOutputDirAbsolute:
    """AC-TEST-001: kanon bootstrap --output-dir <absolute path> creates files under that path.

    Verifies that when --output-dir is given an absolute path, the bootstrapped
    files are created under that absolute path rather than in the current working
    directory.
    """

    def test_absolute_output_dir_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <absolute> must exit with code 0."""
        target = tmp_path / "myproject"
        target.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(target))
        assert result.returncode == 0, (
            f"Expected exit code 0 with absolute --output-dir, got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_absolute_output_dir_creates_kanonenv(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <absolute> must create .kanon under that directory."""
        target = tmp_path / "myproject"
        target.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(target))
        assert result.returncode == 0
        assert (target / ".kanon").is_file(), f".kanon not found in {target} after bootstrap with absolute --output-dir"

    def test_absolute_output_dir_creates_readme(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <absolute> must create kanon-readme.md under that directory."""
        target = tmp_path / "myproject"
        target.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(target))
        assert result.returncode == 0
        assert (target / "kanon-readme.md").is_file(), (
            f"kanon-readme.md not found in {target} after bootstrap with absolute --output-dir"
        )

    def test_absolute_output_dir_creates_exactly_expected_files(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <absolute> must create exactly .kanon and kanon-readme.md."""
        target = tmp_path / "myproject"
        target.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(target))
        assert result.returncode == 0
        created_files = sorted(f.name for f in target.iterdir())
        assert created_files == [".kanon", "kanon-readme.md"], (
            f"Expected ['.kanon', 'kanon-readme.md'] in {target}, got {created_files!r}"
        )

    def test_absolute_output_dir_files_not_in_cwd(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <absolute> must not create files in the current directory."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(target), cwd=cwd)
        assert result.returncode == 0
        cwd_contents = list(cwd.iterdir())
        assert cwd_contents == [], f"Expected no files written to cwd {cwd}, found: {cwd_contents!r}"

    def test_absolute_output_dir_success_has_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <absolute> must not write to stderr on success (AC-CHANNEL-001)."""
        target = tmp_path / "myproject"
        target.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(target))
        assert result.returncode == 0
        assert result.stderr == "", (
            f"Expected empty stderr on success with absolute --output-dir, got: {result.stderr!r}"
        )


@pytest.mark.functional
class TestBootstrapOutputDirMissingParent:
    """AC-TEST-002: kanon bootstrap --output-dir with missing parent must exit 1 with clear message.

    Verifies the fail-fast behavior when the parent directory of the given
    --output-dir does not exist. The command must exit 1 with a diagnostic
    message on stderr, and must not create any files.
    """

    def test_missing_parent_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir with missing parent must exit with a non-zero code."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode != 0, (
            f"Expected non-zero exit for missing parent, got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_missing_parent_exits_1(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir with missing parent must exit with code exactly 1."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 1, (
            f"Expected exit code 1 for missing parent, got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_missing_parent_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir with missing parent must write an error message to stderr."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 1
        assert result.stderr != "", "Expected error message on stderr for missing parent directory"

    def test_missing_parent_stderr_references_parent_directory(self, tmp_path: pathlib.Path) -> None:
        """The stderr error message must mention 'parent' to help the user diagnose the problem."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 1
        assert "parent" in result.stderr.lower(), f"Expected 'parent' in stderr error message, got: {result.stderr!r}"

    def test_missing_parent_nothing_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir with missing parent must not write to stdout (AC-CHANNEL-001)."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 1
        assert result.stdout == "", f"Expected empty stdout for missing parent error, got: {result.stdout!r}"

    def test_missing_parent_no_directory_created(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir with missing parent must not create the target directory."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 1
        assert not missing_parent.exists(), f"Expected {missing_parent} to not be created after missing-parent error"


@pytest.mark.functional
class TestBootstrapOutputDirRelative:
    """AC-FUNC-001: kanon bootstrap --output-dir accepts relative paths and resolves them against CWD.

    Verifies that a relative path given to --output-dir is resolved relative to
    the subprocess working directory, not relative to any other anchor.
    """

    def test_relative_output_dir_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <relative> must exit with code 0."""
        cwd = tmp_path / "workspace"
        cwd.mkdir()
        target_subdir = cwd / "myproject"
        target_subdir.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", "myproject", cwd=cwd)
        assert result.returncode == 0, (
            f"Expected exit code 0 with relative --output-dir, got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_relative_output_dir_creates_kanonenv_in_correct_location(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <relative> must create .kanon under the resolved path."""
        cwd = tmp_path / "workspace"
        cwd.mkdir()
        target_subdir = cwd / "myproject"
        target_subdir.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", "myproject", cwd=cwd)
        assert result.returncode == 0
        assert (target_subdir / ".kanon").is_file(), (
            f".kanon not found in {target_subdir} after bootstrap with relative --output-dir"
        )

    def test_relative_output_dir_creates_readme_in_correct_location(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <relative> must create kanon-readme.md under the resolved path."""
        cwd = tmp_path / "workspace"
        cwd.mkdir()
        target_subdir = cwd / "myproject"
        target_subdir.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", "myproject", cwd=cwd)
        assert result.returncode == 0
        assert (target_subdir / "kanon-readme.md").is_file(), (
            f"kanon-readme.md not found in {target_subdir} after bootstrap with relative --output-dir"
        )

    def test_relative_output_dir_does_not_create_files_in_cwd(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <relative> must only write files to the resolved subdirectory."""
        cwd = tmp_path / "workspace"
        cwd.mkdir()
        target_subdir = cwd / "myproject"
        target_subdir.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", "myproject", cwd=cwd)
        assert result.returncode == 0
        cwd_files = [f.name for f in cwd.iterdir() if f != target_subdir]
        assert cwd_files == [], f"Expected no files written directly to cwd {cwd}, found: {cwd_files!r}"

    def test_relative_output_dir_success_has_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap --output-dir <relative> must not write to stderr on success (AC-CHANNEL-001)."""
        cwd = tmp_path / "workspace"
        cwd.mkdir()
        target_subdir = cwd / "myproject"
        target_subdir.mkdir()
        result = _run_kanon("bootstrap", "kanon", "--output-dir", "myproject", cwd=cwd)
        assert result.returncode == 0
        assert result.stderr == "", (
            f"Expected empty stderr on success with relative --output-dir, got: {result.stderr!r}"
        )
