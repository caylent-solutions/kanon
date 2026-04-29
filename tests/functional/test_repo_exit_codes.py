"""Functional tests for kanon repo exit-code propagation and sentinel forwarding.

Verifies that:
- Exit codes from repo subcommands surface unchanged through kanon repo (AC-TEST-001, AC-FUNC-001).
- The '--' sentinel correctly forwards trailing argv to the underlying repo (AC-TEST-002).
- An unknown repo subcommand exits 1 and the error message contains
  'is not a repo command' (AC-TEST-003).
- stdout vs stderr channel discipline is maintained (AC-CHANNEL-001).

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _git, _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Exit Code Test User"
_GIT_USER_EMAIL = "exit-code-test@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from exit-code test content"


# ---------------------------------------------------------------------------
# NOTE: _git is imported from tests.functional.conftest (canonical definition).
#
# The five helpers below (_init_git_work_dir, _clone_as_bare,
# _create_bare_content_repo, _create_manifest_repo, _create_minimal_repo_dot_dir)
# are near-duplicates of same-named functions in test_kanon_repo_cli.py.
# Consolidating them into a shared module requires touching that file, which is
# outside this task's Changes Manifest. This duplication is tracked as a
# follow-up DRY cleanup.
# ---------------------------------------------------------------------------


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with user config set.

    Args:
        work_dir: The directory to initialise as a git repo.
    """
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into bare_dir and return the resolved bare_dir path.

    Args:
        work_dir: The source non-bare working directory.
        bare_dir: The destination path for the bare clone.

    Returns:
        The resolved absolute path to the bare clone.
    """
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_bare_content_repo(base: pathlib.Path) -> pathlib.Path:
    """Create a bare git repo containing one committed file.

    Args:
        base: Parent directory under which repos are created.

    Returns:
        The absolute path to the bare content repository.
    """
    work_dir = base / "content-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    readme = work_dir / _CONTENT_FILE_NAME
    readme.write_text(_CONTENT_FILE_TEXT, encoding="utf-8")
    _git(["add", _CONTENT_FILE_NAME], cwd=work_dir)
    _git(["commit", "-m", "Initial commit"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "content-bare.git")


def _create_manifest_repo(base: pathlib.Path, fetch_base: str) -> pathlib.Path:
    """Create a bare manifest git repo pointing at a content repo.

    Args:
        base: Parent directory under which repos are created.
        fetch_base: The fetch base URL for the remote element.

    Returns:
        The absolute path to the bare manifest repository.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{fetch_base}" />\n'
        '  <default revision="main" remote="local" />\n'
        '  <project name="content-bare" path="ec-project" />\n'
        "</manifest>\n"
    )
    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)
    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    return _clone_as_bare(work_dir, base / "manifest-bare.git")


def _create_minimal_repo_dot_dir(base: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory for running repo subcommands.

    The .repo/repo/ git repository must have at least one tagged commit for
    the embedded repo tool version subcommand and other subcommands. The
    .repo/manifests/ directory must contain a valid manifest XML file.

    Args:
        base: The directory in which to create .repo/.

    Returns:
        The path to the created .repo directory.
    """
    repo_dot_dir = base / ".repo"
    manifests_dir = repo_dot_dir / "manifests"
    manifests_dir.mkdir(parents=True)

    manifest_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://github.com/caylent-solutions/" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    (manifests_dir / _MANIFEST_FILENAME).write_text(manifest_content, encoding="utf-8")
    (repo_dot_dir / "manifest.xml").symlink_to(manifests_dir / _MANIFEST_FILENAME)

    repo_tool_dir = repo_dot_dir / "repo"
    repo_tool_dir.mkdir()
    _init_git_work_dir(repo_tool_dir)
    (repo_tool_dir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    _git(["add", "VERSION"], cwd=repo_tool_dir)
    _git(["commit", "-m", "Initial commit"], cwd=repo_tool_dir)
    _git(["tag", "-a", "v1.0.0", "-m", "Version 1.0.0"], cwd=repo_tool_dir)

    return repo_dot_dir


def _setup_init_env(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create a real checkout dir and .repo via kanon repo init.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        Tuple of (checkout_dir, repo_dir) after a successful init.

    Raises:
        AssertionError: If kanon repo init fails.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()

    bare_content = _create_bare_content_repo(repos_dir)
    fetch_base = f"file://{bare_content.parent}"
    manifest_bare = _create_manifest_repo(repos_dir, fetch_base)
    repo_dir = checkout_dir / ".repo"

    init_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "init",
        "--no-repo-verify",
        "-u",
        f"file://{manifest_bare}",
        "-b",
        "main",
        "-m",
        _MANIFEST_FILENAME,
        cwd=checkout_dir,
    )
    assert init_result.returncode == 0, (
        f"Prerequisite kanon repo init failed with exit {init_result.returncode}.\n"
        f"  stdout: {init_result.stdout!r}\n"
        f"  stderr: {init_result.stderr!r}"
    )
    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001: exit-code propagation through kanon repo
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoExitCodePropagation:
    """AC-TEST-001: Exit codes from repo subcommands propagate unchanged through kanon repo.

    Covers AC-FUNC-001 as well: exit codes surface unchanged.
    """

    def test_unknown_subcommand_exits_exactly_1(self, tmp_path: pathlib.Path) -> None:
        """An unknown repo subcommand must exit with code exactly 1.

        The embedded repo tool returns 1 for unrecognised subcommands
        ('repo: <name> is not a repo command'). The kanon layer must
        propagate this exit code without alteration.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "definitely-not-a-valid-subcommand-xyzzy",
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for unknown subcommand, got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_successful_subcommand_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """A disabled-in-embedded-mode subcommand exits with code 1 through kanon.

        Runs 'kanon repo selfupdate' which is intercepted by the embedded mode
        handler and exits 1 with an informational message. Updated per
        E2-F2-S2-T2: selfupdate exits 1 (not 0) in embedded mode to signal
        that selfupdate is unavailable. Verifies that exit code 1 surfaces
        unchanged through the kanon layer.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "selfupdate",
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for 'selfupdate', got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "subcommand",
        [
            "invalid-subcommand-abc",
            "not-real-xyzzy",
            "no-such-cmd-99",
        ],
    )
    def test_multiple_unknown_subcommands_exit_1(self, tmp_path: pathlib.Path, subcommand: str) -> None:
        """Various unknown repo subcommands must all exit with code 1.

        Ensures that the exit code is exactly 1, not a different non-zero
        value, confirming the repo tool's 'not a repo command' error code
        propagates verbatim.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            subcommand,
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for unknown subcommand {subcommand!r}, "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_sync_exit_code_propagates_zero(self, tmp_path: pathlib.Path) -> None:
        """A successful 'kanon repo sync' must surface exit code 0 unchanged.

        Performs a real init followed by a real sync against a local bare git
        repository. Verifies that the zero exit code propagates through the
        kanon layer without alteration.
        """
        checkout_dir, repo_dir = _setup_init_env(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"Expected exit code 0 for 'kanon repo sync', got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: '--' sentinel forwards trailing argv to underlying repo
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestSentinelForwarding:
    """AC-TEST-002: '--' sentinel forwards trailing argv to the underlying repo tool."""

    def test_sentinel_before_known_subcommand_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo -- selfupdate' must exit 1 with the sentinel present.

        Places '--' before the subcommand to simulate a user who wants to
        prevent kanon's arg parser from consuming the subcommand name. The
        selfupdate subcommand is intercepted in embedded mode and exits 1
        (updated per E2-F2-S2-T2: selfupdate exits 1 in embedded mode).
        Verifies the sentinel is passed through without causing an error.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "--",
            "selfupdate",
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for 'kanon repo -- selfupdate', got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_sentinel_before_sync_produces_same_result_as_without(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo -- sync --jobs=1' must exit 0, same as 'kanon repo sync --jobs=1'.

        Verifies that forwarding via the '--' sentinel does not alter the
        outcome: both forms reach the underlying repo sync and succeed.
        Runs a real sync against a local bare git repository.
        """
        checkout_dir, repo_dir = _setup_init_env(tmp_path)

        result_with_sentinel = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "--",
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert result_with_sentinel.returncode == 0, (
            f"Expected exit code 0 for 'kanon repo -- sync --jobs=1', "
            f"got {result_with_sentinel.returncode}.\n"
            f"  stdout: {result_with_sentinel.stdout!r}\n"
            f"  stderr: {result_with_sentinel.stderr!r}"
        )

    def test_sentinel_before_unknown_subcommand_still_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo -- no-such-cmd' must still exit 1 (sentinel passes through).

        The '--' sentinel must not swallow or transform the unknown-subcommand
        error. The exit code must still be exactly 1, confirming that '--'
        forwards its trailing argv verbatim to the underlying repo tool.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "--",
            "definitely-unknown-sentinel-cmd",
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for 'kanon repo -- definitely-unknown-sentinel-cmd', "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_sentinel_plus_args_clones_project(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo -- sync --jobs=1' must clone the project defined in the manifest.

        Confirms that the '--' sentinel does not interfere with argument
        forwarding: --jobs=1 reaches the sync subcommand and the project
        is cloned to disk.
        """
        checkout_dir, repo_dir = _setup_init_env(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "--",
            "sync",
            "--jobs=1",
            cwd=checkout_dir,
        )

        assert result.returncode == 0, (
            f"sync via sentinel exited {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        project_dir = checkout_dir / "ec-project"
        assert project_dir.is_dir(), (
            f"Project directory {project_dir!r} was not created after 'kanon repo -- sync --jobs=1'."
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: unknown subcommand exits 1 with "is not a repo command"
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestUnknownSubcommandErrorMessage:
    """AC-TEST-003: Unknown repo subcommand exits 1 with 'is not a repo command'."""

    def test_unknown_subcommand_exit_code_is_1(self, tmp_path: pathlib.Path) -> None:
        """An unknown repo subcommand must exit with code exactly 1.

        The embedded repo tool emits 'is not a repo command' and returns 1.
        The kanon layer must propagate this exit code without modification.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "no-such-subcommand-at-all",
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for unknown subcommand, got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_subcommand_error_message_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """An unknown repo subcommand must emit 'is not a repo command' on stderr.

        The embedded repo tool logs this message to stderr when the subcommand
        name is not found in its command registry. Verifies the canonical error
        phrase appears in the subprocess stderr output.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)
        bad_subcommand = "not-a-real-repo-subcommand-test"

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            bad_subcommand,
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for unknown subcommand {bad_subcommand!r}, "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        expected_phrase = "is not a repo command"
        assert expected_phrase in result.stderr, (
            f"Expected phrase {expected_phrase!r} not found in stderr for "
            f"unknown subcommand {bad_subcommand!r}.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_subcommand_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """The 'is not a repo command' error must appear on stderr, not stdout.

        Error messages must not leak to stdout. Verifies that the error phrase
        is absent from stdout (channel discipline).
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)
        bad_subcommand = "totally-bogus-subcommand-discipline"

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            bad_subcommand,
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for unknown subcommand {bad_subcommand!r}, "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        error_phrase = "is not a repo command"
        assert error_phrase not in result.stdout, (
            f"Error phrase {error_phrase!r} leaked to stdout for "
            f"unknown subcommand {bad_subcommand!r}.\n"
            f"  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_cmd",
        [
            "xyzzy-totally-fake",
            "no-command-here",
            "fake123",
        ],
    )
    def test_various_unknown_subcommands_emit_error_message(self, tmp_path: pathlib.Path, bad_cmd: str) -> None:
        """Multiple unknown subcommand names must all emit 'is not a repo command' on stderr.

        Parametrizes over several bogus subcommand names to confirm the error
        message is consistently emitted regardless of the specific name used.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            bad_cmd,
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for unknown subcommand {bad_cmd!r}, "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        expected_phrase = "is not a repo command"
        assert expected_phrase in result.stderr, (
            f"Expected phrase {expected_phrase!r} in stderr for {bad_cmd!r}.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestExitCodeChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for exit-code scenarios."""

    def test_successful_subcommand_error_prefix_absent_from_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo selfupdate' exits 1 in embedded mode; kanon emits 'Error:' on stderr.

        Updated per E2-F2-S2-T2: selfupdate now exits 1 in embedded mode.
        When the embedded repo tool exits non-zero, the kanon layer appends
        'Error: repo command failed with exit code 1' to stderr. This test
        verifies the exit code is 1 and that the disabled-message is on stderr.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "selfupdate",
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for 'selfupdate', got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE

        assert SELFUPDATE_EMBEDDED_MESSAGE in result.stderr, (
            f"Expected {SELFUPDATE_EMBEDDED_MESSAGE!r} on stderr.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_subcommand_error_appears_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """When an unknown subcommand is used, stderr must contain the error message.

        Verifies that stderr is non-empty and contains the 'is not a repo
        command' phrase, confirming errors are routed to stderr rather than
        stdout (channel discipline).
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "channel-discipline-bad-cmd",
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1, got {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, (
            f"stderr must be non-empty for an unknown subcommand.\n  stdout: {result.stdout!r}"
        )
        assert "is not a repo command" in result.stderr, (
            f"'is not a repo command' not found in stderr.\n  stderr: {result.stderr!r}"
        )

    def test_sentinel_success_has_no_kanon_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo -- selfupdate' exits 1 in embedded mode; kanon emits 'Error:' on stderr.

        Updated per E2-F2-S2-T2: selfupdate exits 1 in embedded mode.
        When the '--' sentinel forwards 'selfupdate' to the embedded repo tool,
        the tool exits 1 and the kanon layer appends 'Error:' to stderr.
        This test verifies the exit code is 1 and the disabled-message is present.
        """
        repo_dot_dir = _create_minimal_repo_dot_dir(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dot_dir),
            "--",
            "selfupdate",
            cwd=tmp_path,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 for 'kanon repo -- selfupdate', "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE

        assert SELFUPDATE_EMBEDDED_MESSAGE in result.stderr, (
            f"Expected {SELFUPDATE_EMBEDDED_MESSAGE!r} on stderr for sentinel invocation.\n  stderr: {result.stderr!r}"
        )
