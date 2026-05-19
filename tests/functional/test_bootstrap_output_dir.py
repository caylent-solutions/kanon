"""Functional tests for kanon bootstrap --output-dir deprecation shim behavior.

The 'kanon bootstrap' command is now a deprecation shim. Passing --output-dir
does not cause any filesystem mutation; the shim exits 3 without performing work.

Covers:
- AC-FUNC-005: No filesystem mutation when the shim runs (output-dir remains empty)
- AC-FUNC-001: Shim exits 3 regardless of --output-dir value
- AC-CHANNEL-001: stdout vs stderr channel discipline verified
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon


@pytest.mark.functional
class TestBootstrapOutputDirShim:
    """Verify --output-dir does not cause filesystem mutation (shim never delegates)."""

    def test_absolute_output_dir_exits_3(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap kanon --output-dir <abs> must exit 3 (shim, no delegation)."""
        output_dir = tmp_path / "bootstrap-out"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 3, (
            f"Expected exit code 3 (shim), got {result.returncode}.\nstderr: {result.stderr!r}"
        )

    def test_absolute_output_dir_not_created(self, tmp_path: pathlib.Path) -> None:
        """The --output-dir must NOT be created (shim does not delegate)."""
        output_dir = tmp_path / "bootstrap-out"
        _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert not output_dir.exists(), f"Expected --output-dir '{output_dir}' to NOT be created, but it exists."

    def test_absolute_output_dir_no_kanonenv_created(self, tmp_path: pathlib.Path) -> None:
        """No .kanon file must be created (shim does not delegate)."""
        output_dir = tmp_path / "bootstrap-out"
        _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert not (output_dir / ".kanon").exists(), "Expected no .kanon file to be created by the shim."

    def test_absolute_output_dir_no_readme_created(self, tmp_path: pathlib.Path) -> None:
        """No readme file must be created (shim does not delegate)."""
        output_dir = tmp_path / "bootstrap-out"
        _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert not (output_dir / "kanon-readme.md").exists(), "Expected no kanon-readme.md to be created by the shim."

    def test_absolute_output_dir_tmp_path_empty(self, tmp_path: pathlib.Path) -> None:
        """The tmp_path must remain empty after shim invocation (no filesystem mutation)."""
        output_dir = tmp_path / "bootstrap-out"
        _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert list(tmp_path.iterdir()) == [], f"Expected tmp_path to be empty, got: {list(tmp_path.iterdir())}"

    def test_absolute_output_dir_success_has_warn_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Stderr must contain the WARN message (not an empty success output)."""
        output_dir = tmp_path / "bootstrap-out"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        assert result.returncode == 3
        assert "WARN:" in result.stderr, f"Expected WARN on stderr, got: {result.stderr!r}"

    def test_absolute_output_dir_files_not_in_cwd(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No files must appear in cwd after shim invocation."""
        monkeypatch.chdir(tmp_path)
        output_dir = tmp_path / "sub" / "bootstrap-out"
        _run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        created = [p.name for p in tmp_path.iterdir()]
        assert created == [], f"Expected cwd to be empty, got: {created}"


@pytest.mark.functional
class TestBootstrapOutputDirMissingParent:
    """Verify missing-parent --output-dir still exits 3 (shim never inspects the path)."""

    def test_missing_parent_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap with --output-dir whose parent does not exist must exit non-zero."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode != 0, f"Expected non-zero exit for missing parent, got 0.\nstderr: {result.stderr!r}"

    def test_missing_parent_exits_3(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap with missing-parent --output-dir must exit 3 (shim)."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_missing_parent_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """stderr must contain a message (the WARN) when missing-parent path is given."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 3
        assert result.stderr != "", "Expected WARN message on stderr"
        assert "Traceback" not in result.stderr, f"Expected no Python traceback, got: {result.stderr!r}"

    def test_missing_parent_stderr_references_deprecation(self, tmp_path: pathlib.Path) -> None:
        """stderr message must reference the deprecation (WARN or migration docs)."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 3
        assert "WARN:" in result.stderr or "deprecated" in result.stderr, (
            f"Expected deprecation language in stderr, got: {result.stderr!r}"
        )

    def test_missing_parent_nothing_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap with missing-parent --output-dir must not write to stdout."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        result = _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert result.returncode == 3
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"

    def test_missing_parent_no_directory_created(self, tmp_path: pathlib.Path) -> None:
        """No directory must be created for missing-parent paths (shim never delegates)."""
        missing_parent = tmp_path / "nonexistent" / "sub"
        _run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        assert not missing_parent.exists(), "Expected no directory to be created by the shim"


@pytest.mark.functional
class TestBootstrapOutputDirRelative:
    """Verify --output-dir with relative paths does not create files (shim never delegates)."""

    def test_relative_output_dir_exits_3(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """kanon bootstrap with a relative --output-dir must exit 3 (shim)."""
        monkeypatch.chdir(tmp_path)
        result = _run_kanon("bootstrap", "kanon", "--output-dir", "relative-output")
        assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_relative_output_dir_not_created_in_cwd(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The relative --output-dir must NOT be created in cwd (shim does not delegate)."""
        monkeypatch.chdir(tmp_path)
        _run_kanon("bootstrap", "kanon", "--output-dir", "relative-output")
        assert not (tmp_path / "relative-output").exists(), "Expected no directory created by the shim"

    def test_relative_output_dir_does_not_create_files_in_cwd(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No files must appear in cwd after shim invocation with relative output-dir."""
        monkeypatch.chdir(tmp_path)
        _run_kanon("bootstrap", "kanon", "--output-dir", "relative-output")
        assert list(tmp_path.iterdir()) == [], f"Expected empty cwd, got: {list(tmp_path.iterdir())}"

    def test_relative_output_dir_success_has_warn_on_stderr(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stderr must contain the WARN message for relative --output-dir invocations."""
        monkeypatch.chdir(tmp_path)
        result = _run_kanon("bootstrap", "kanon", "--output-dir", "relative-output")
        assert result.returncode == 3
        assert "WARN:" in result.stderr, f"Expected WARN on stderr, got: {result.stderr!r}"
