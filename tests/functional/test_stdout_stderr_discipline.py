"""Functional tests for stdout/stderr channel discipline across CLI subcommands.

Verifies that each CLI surface routes output to the correct channel:
  - Success output goes to stdout only
  - Error and warning output goes to stderr only
  - No cross-channel leakage

Covers:
  AC-TEST-001: install success writes nothing to stderr
  AC-TEST-002: install failure writes nothing to stdout
  AC-TEST-003: validate xml success writes results to stdout, errors to stderr
  AC-TEST-004: kanon repo sync stdout/stderr separation matches upstream repo conventions
  AC-FUNC-001: success output goes to stdout only; error/warning output goes to stderr only
  AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage)
"""

import pathlib
import subprocess
import textwrap
from unittest.mock import patch

import pytest

from tests.functional.conftest import _git, _run_kanon
from kanon_cli.core.install import install
from kanon_cli.core.xml_validator import validate_xml

# NOTE: _git is imported from tests.functional.conftest to avoid duplication.
# This follows the established pattern in test_validate_xml_repo_root.py.


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_GIT_USER_EMAIL = "stdout-stderr-test@example.com"
_GIT_USER_NAME = "Stdout Stderr Test"
_MANIFEST_FILENAME = "default.xml"
_VALID_MANIFEST_CONTENT = textwrap.dedent("""\
    <manifest>
      <remote name="origin" fetch="https://example.com" />
      <project name="proj" path=".packages/proj" remote="origin" revision="main" />
    </manifest>
""")

_MINIMAL_KANONENV_CONTENT = (
    "KANON_SOURCE_src_URL=https://example.com/src.git\n"
    "KANON_SOURCE_src_REVISION=main\n"
    "KANON_SOURCE_src_PATH=default.xml\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: pathlib.Path, content: str = _MINIMAL_KANONENV_CONTENT) -> pathlib.Path:
    """Write a .kanon file in directory and return its path.

    Args:
        directory: Directory in which to write the .kanon file.
        content: Content of the .kanon file. Defaults to a minimal valid config.

    Returns:
        The path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content, encoding="utf-8")
    return kanonenv


def _write_xml(path: pathlib.Path, content: str) -> pathlib.Path:
    """Write an XML file, creating parent directories as needed.

    Args:
        path: Target file path.
        content: XML body (without the XML declaration header).

    Returns:
        The path that was written.
    """
    # NOTE: _write_xml duplicates the same helper in test_validate_lifecycle.py
    # and test_validate_xml_repo_root.py. Consolidation into conftest.py requires
    # updating those files too, which is outside this task's Changes Manifest.
    # Tracked as a follow-up DRY cleanup.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + content, encoding="utf-8")
    return path


def _init_git_repo(directory: pathlib.Path) -> None:
    """Initialise a minimal git repo with a committed file.

    Args:
        directory: Directory to initialise as a git repository.
    """
    _git(["init", "-b", "main"], cwd=directory)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=directory)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=directory)
    placeholder = directory / ".gitkeep"
    placeholder.write_text("", encoding="utf-8")
    _git(["add", ".gitkeep"], cwd=directory)
    _git(["commit", "-m", "Initial commit"], cwd=directory)


def _create_bare_content_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a bare git repo with one committed file and return its resolved path.

    Args:
        base: Parent directory under which repos are created.

    Returns:
        The resolved absolute path to the bare git repository directory.
    """
    work_dir = base / "content-work"
    work_dir.mkdir()
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    (work_dir / "README.md").write_text("hello from content repo", encoding="utf-8")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)
    bare_dir = base / "content-bare.git"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)
    return bare_dir.resolve()


def _create_manifest_repo(base: pathlib.Path, fetch_base: str) -> pathlib.Path:
    """Create a bare manifest git repo pointing at a content repo.

    Args:
        base: Parent directory under which repos are created.
        fetch_base: The fetch base URL for the remote element.

    Returns:
        The resolved absolute path to the bare manifest repository.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir()
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{fetch_base}" />\n'
        '  <default revision="main" remote="local" />\n'
        '  <project name="content-bare" path="sync-project" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)
    bare_dir = base / "manifest-bare.git"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)
    return bare_dir.resolve()


def _run_repo_init(
    checkout_dir: pathlib.Path,
    repo_dir: pathlib.Path,
    manifest_url: str,
) -> subprocess.CompletedProcess:
    """Run kanon repo init with the given manifest URL.

    Args:
        checkout_dir: The working directory for the subprocess.
        repo_dir: The .repo directory to pass via --repo-dir.
        manifest_url: The manifest repository URL (file:// or https://).

    Returns:
        The CompletedProcess from the init invocation.
    """
    return _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "init",
        "--no-repo-verify",
        "-u",
        manifest_url,
        "-b",
        "main",
        "-m",
        _MANIFEST_FILENAME,
        cwd=checkout_dir,
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: install success writes nothing to stderr
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestInstallSuccessNoStderr:
    """AC-TEST-001: a successful install writes nothing to stderr."""

    def test_install_success_stderr_is_empty(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """AC-TEST-001: install() with mocked repo writes all output to stdout; stderr must be empty.

        Verifies that on a fully successful install lifecycle, every message
        produced by install() goes to stdout and nothing leaks to stderr.
        """
        kanonenv = _write_kanonenv(tmp_path)

        def fake_repo_sync(repo_dir: str, **kwargs) -> None:
            """Simulate a successful repo sync that creates one package."""
            pkg = pathlib.Path(repo_dir) / ".packages" / "test-pkg"
            pkg.mkdir(parents=True, exist_ok=True)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync", side_effect=fake_repo_sync),
        ):
            install(kanonenv)

        captured = capsys.readouterr()
        assert captured.err == "", (
            f"AC-TEST-001: install success must write nothing to stderr.\n"
            f"  stderr: {captured.err!r}\n"
            f"  stdout: {captured.out!r}"
        )

    def test_install_success_stdout_is_non_empty(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """AC-FUNC-001: install() on success writes progress messages to stdout only.

        Confirms that the success path actually produces output, and that all
        of it is on stdout rather than silently suppressed.
        """
        kanonenv = _write_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
        ):
            install(kanonenv)

        captured = capsys.readouterr()
        assert len(captured.out) > 0, (
            f"AC-FUNC-001: install success must write progress messages to stdout.\n  stdout: {captured.out!r}"
        )
        assert captured.err == "", (
            f"AC-FUNC-001: install success must write nothing to stderr.\n  stderr: {captured.err!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: install failure writes nothing to stdout
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestInstallFailureNoStdout:
    """AC-TEST-002: a failed install (file not found) writes nothing to stdout."""

    def test_missing_kanonenv_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002: 'kanon install' with a missing .kanon writes nothing to stdout.

        When .kanon is not found, the CLI must write the error only to stderr
        and produce no stdout output at all. The stdout channel must be empty.
        """
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = _run_kanon("install", cwd=empty_dir)

        assert result.returncode == 1, (
            f"AC-TEST-002: expected exit code 1 when .kanon is missing.\n"
            f"  returncode: {result.returncode}\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == "", (
            f"AC-TEST-002: install failure must write nothing to stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_explicit_missing_path_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-002 + AC-CHANNEL-001: explicit nonexistent .kanon path writes nothing to stdout.

        When an explicit path is given and the file does not exist, the CLI
        must write the error only to stderr. stdout must be empty.
        """
        nonexistent = str(tmp_path / "ghost" / ".kanon")
        result = _run_kanon("install", nonexistent)

        assert result.returncode == 1, (
            f"AC-TEST-002: expected exit code 1 for nonexistent explicit path.\n"
            f"  returncode: {result.returncode}\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == "", (
            f"AC-TEST-002 + AC-CHANNEL-001: install failure must write nothing to stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_kanonenv_error_goes_to_stderr(self, tmp_path: pathlib.Path) -> None:
        """AC-CHANNEL-001: install failure error message appears on stderr, not stdout.

        Verifies that the '.kanon file not found' (or equivalent) error message
        is routed exclusively to stderr.
        """
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = _run_kanon("install", cwd=empty_dir)

        assert result.returncode == 1
        assert len(result.stderr) > 0, (
            f"AC-CHANNEL-001: install failure must produce an error message on stderr.\n  stderr: {result.stderr!r}"
        )
        assert result.stdout == "", (
            f"AC-CHANNEL-001: install failure error must not appear on stdout.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: validate xml success writes results to stdout, errors to stderr
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestValidateXmlChannelDiscipline:
    """AC-TEST-003: validate xml success writes results to stdout, errors to stderr."""

    def test_valid_xml_success_output_goes_to_stdout(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """AC-TEST-003 + AC-FUNC-001: validate_xml() success writes results to stdout.

        On a successful validation the 'all manifest files are valid' summary
        must appear on stdout. stderr must be empty.
        """
        _write_xml(tmp_path / "repo-specs" / "valid.xml", _VALID_MANIFEST_CONTENT)

        exit_code = validate_xml(tmp_path)

        captured = capsys.readouterr()
        assert exit_code == 0, (
            f"AC-TEST-003: expected validate_xml to return 0 for valid manifest.\n"
            f"  stdout: {captured.out!r}\n"
            f"  stderr: {captured.err!r}"
        )
        assert "valid" in captured.out.lower(), (
            f"AC-TEST-003: success summary must appear on stdout.\n  stdout: {captured.out!r}"
        )
        assert captured.err == "", (
            f"AC-TEST-003 + AC-CHANNEL-001: no output expected on stderr for a successful validation.\n"
            f"  stderr: {captured.err!r}"
        )

    def test_validation_progress_goes_to_stdout(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """AC-TEST-003: per-file validation progress lines go to stdout, not stderr.

        validate_xml() prints 'Validating <file>...' for each file it checks.
        Those progress messages must appear on stdout.
        """
        _write_xml(tmp_path / "repo-specs" / "valid.xml", _VALID_MANIFEST_CONTENT)

        validate_xml(tmp_path)

        captured = capsys.readouterr()
        assert "Validating" in captured.out, (
            f"AC-TEST-003: per-file 'Validating ...' lines must appear on stdout.\n  stdout: {captured.out!r}"
        )
        assert "Validating" not in captured.err, (
            f"AC-CHANNEL-001: 'Validating ...' lines must not appear on stderr.\n  stderr: {captured.err!r}"
        )

    def test_xml_validation_errors_go_to_stderr(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """AC-TEST-003 + AC-CHANNEL-001: validate_xml() error details go to stderr.

        When a manifest file contains validation errors, the error details must
        appear on stderr. The per-file progress line ('Validating ...') still
        appears on stdout.
        """
        _write_xml(
            tmp_path / "repo-specs" / "bad.xml",
            '<manifest><project name="proj" /></manifest>',
        )

        exit_code = validate_xml(tmp_path)

        captured = capsys.readouterr()
        assert exit_code == 1, "AC-TEST-003: expected validate_xml to return 1 for invalid manifest."
        assert len(captured.err) > 0, (
            f"AC-TEST-003 + AC-CHANNEL-001: validation error details must appear on stderr.\n  stderr: {captured.err!r}"
        )
        assert "error" in captured.err.lower() or "missing" in captured.err.lower(), (
            f"AC-CHANNEL-001: stderr must contain the error description.\n  stderr: {captured.err!r}"
        )

    def test_xml_validation_errors_not_on_stdout(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """AC-CHANNEL-001: validate_xml() error details must not appear on stdout.

        The 'Found N error(s)' summary and individual error lines must be
        routed to stderr, not stdout, so that stdout is usable for machine
        parsing of success output.
        """
        _write_xml(
            tmp_path / "repo-specs" / "bad.xml",
            '<manifest><project name="proj" /></manifest>',
        )

        validate_xml(tmp_path)

        captured = capsys.readouterr()
        assert "Found" not in captured.out, (
            f"AC-CHANNEL-001: 'Found N error(s)' summary must not appear on stdout. stdout: {captured.out!r}"
        )
        assert "missing required attribute" not in captured.out, (
            f"AC-CHANNEL-001: attribute error details must not appear on stdout.\n  stdout: {captured.out!r}"
        )

    def test_validate_xml_subprocess_success_stderr_empty(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-003 via subprocess: 'kanon validate xml' success writes nothing to stderr.

        Invokes the CLI as a subprocess to confirm that the end-to-end path
        (including any CLI boundary formatting) does not produce stderr output
        on a valid repository.
        """
        _write_xml(tmp_path / "repo-specs" / "valid.xml", _VALID_MANIFEST_CONTENT)

        result = _run_kanon("validate", "xml", "--repo-root", str(tmp_path))

        assert result.returncode == 0, (
            f"AC-TEST-003: expected exit 0 for valid manifest.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"AC-TEST-003 + AC-CHANNEL-001: 'kanon validate xml' success must write nothing to stderr.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert "valid" in result.stdout.lower(), (
            f"AC-TEST-003: success message must appear on stdout.\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: kanon repo sync stdout/stderr separation matches upstream conventions
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncChannelDiscipline:
    """AC-TEST-004: kanon repo sync separates stdout and stderr per upstream conventions.

    The embedded repo tool writes sync progress and the final 'repo sync has
    finished successfully.' message to stdout. Warnings from non-TTY stdin
    detection go to stderr. Neither channel should contain output from the other.
    """

    def test_repo_sync_success_message_goes_to_stdout(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-004 + AC-FUNC-001: 'kanon repo sync' success message appears on stdout.

        Creates real local bare git repos, runs kanon repo init, then runs
        kanon repo sync. Verifies that the success summary produced by the
        underlying repo tool appears on stdout.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
        repo_dir = checkout_dir / ".repo"

        init_result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, (
            f"Prerequisite init failed.\n  stdout: {init_result.stdout!r}\n  stderr: {init_result.stderr!r}"
        )

        sync_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert sync_result.returncode == 0, (
            f"AC-TEST-004: 'kanon repo sync' must exit 0 on success.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )
        assert len(sync_result.stdout) > 0, (
            f"AC-TEST-004 + AC-FUNC-001: sync success output must appear on stdout, stdout was empty: {sync_result.stdout!r}"
        )

    def test_repo_sync_success_no_errors_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """AC-TEST-004 + AC-CHANNEL-001: 'kanon repo sync' success writes no errors to stderr.

        On a successful sync, stderr must not contain any error-class output.
        The upstream repo tool may emit informational warnings (such as
        'skipping interactive prompts: stdin is not a TTY') to stderr -- these
        are not errors and do not indicate a failure. This test verifies that
        no error-level output appears on stderr, and that stdout is not empty.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
        repo_dir = checkout_dir / ".repo"

        init_result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, (
            f"Prerequisite init failed.\n  stdout: {init_result.stdout!r}\n  stderr: {init_result.stderr!r}"
        )

        sync_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert sync_result.returncode == 0, (
            f"AC-TEST-004: 'kanon repo sync' must exit 0 on success.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )
        # Error-level indicators must not appear on stderr for a successful sync.
        error_indicators = ("error", "fatal", "traceback", "exception")
        for indicator in error_indicators:
            assert indicator not in sync_result.stderr.lower(), (
                f"AC-TEST-004 + AC-CHANNEL-001: '{indicator}' must not appear on stderr for a successful sync.\n"
                f"  stderr: {sync_result.stderr!r}"
            )

    def test_repo_sync_success_result_not_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """AC-CHANNEL-001: 'kanon repo sync' success result must not appear on stderr.

        The final sync result summary must be on stdout. Verifies that the
        sync success message does not cross-pollute the stderr channel.
        """
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        checkout_dir = tmp_path / "checkout"
        checkout_dir.mkdir()

        bare_content = _create_bare_content_repo(repos_dir)
        fetch_base = f"file://{bare_content.parent}"
        manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
        repo_dir = checkout_dir / ".repo"

        init_result = _run_repo_init(checkout_dir, repo_dir, f"file://{manifest_bare}")
        assert init_result.returncode == 0, (
            f"Prerequisite init failed.\n  stdout: {init_result.stdout!r}\n  stderr: {init_result.stderr!r}"
        )

        sync_result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert sync_result.returncode == 0, (
            f"AC-TEST-004: 'kanon repo sync' must exit 0 on success.\n"
            f"  stdout: {sync_result.stdout!r}\n"
            f"  stderr: {sync_result.stderr!r}"
        )
        # The success message from repo sync must appear on stdout, not stderr.
        assert len(sync_result.stdout) > 0, (
            f"AC-CHANNEL-001: sync success output must appear on stdout, stdout was empty: {sync_result.stdout!r}"
        )
        assert "finished successfully" not in sync_result.stderr, (
            f"AC-CHANNEL-001: sync success result must not appear on stderr.\n  stderr: {sync_result.stderr!r}"
        )
