"""Happy-path functional tests for 'kanon repo diffmanifests'.

Exercises the happy path of the 'repo diffmanifests' subcommand by invoking
``kanon repo diffmanifests`` as a subprocess against a real initialized and
synced repo directory created in a temporary directory. No mocking -- these
tests use the full CLI stack against actual git operations.

The 'repo diffmanifests' subcommand compares two manifest files and displays
the diff at project level. It requires at least one positional manifest
filename argument (relative to ``.repo/manifests/``) and accepts an optional
second manifest filename. When both manifests are identical the command exits 0
with no output.

Note on AC-TEST-001 wording vs actual behavior: the subcommand requires at
least one positional manifest filename argument -- there is no zero-argument
invocation that succeeds. The AC wording "with default args" is interpreted as
"with the minimal required arguments": one manifest filename. All tests below
assert actual tool behavior with exact exit codes.

Covers:
- AC-TEST-001: 'kanon repo diffmanifests' with one manifest arg exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo diffmanifests' has a happy-path test.
- AC-FUNC-001: 'kanon repo diffmanifests' executes successfully with documented default behavior.
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no inline literals in test bodies
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Diffmanifests Happy Test User"
_GIT_USER_EMAIL = "repo-diffmanifests-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_ALT_MANIFEST_FILENAME = "alt.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "diffmanifests-test-project"
_ALT_PROJECT_PATH = "diffmanifests-alt-project"

# CLI tokens
_CMD_REPO = "repo"
_CMD_DIFFMANIFESTS = "diffmanifests"
_OPT_REPO_DIR = "--repo-dir"
_FLAG_RAW = "--raw"
_FLAG_NO_COLOR = "--no-color"
_FLAG_PRETTY_FORMAT = "--pretty-format"

# Pretty-format sentinel value -- uses a valid git log format string
_PRETTY_FORMAT_VALUE = "%h"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT_CODE = 0

# Phrases expected in stdout when two manifests differ
_PHRASE_ADDED_PROJECTS = "added projects"
_PHRASE_REMOVED_PROJECTS = "removed projects"

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"

# Empty string sentinel for combined-output checks
_EMPTY_OUTPUT = ""


def _write_alt_manifest(manifests_dir: pathlib.Path, fetch_base: str) -> None:
    """Write a second manifest file with an alternate project path into manifests_dir.

    The alt manifest differs from the default only in the project path, which
    ensures that ``diffmanifests default.xml alt.xml`` produces a non-empty
    diff with added/removed project entries.

    Args:
        manifests_dir: Path to the ``.repo/manifests/`` directory.
        fetch_base: The ``file://`` URL to use as the remote fetch base.
    """
    alt_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{fetch_base}" />\n'
        '  <default revision="main" remote="local" />\n'
        f'  <project name="{_PROJECT_NAME}" path="{_ALT_PROJECT_PATH}" />\n'
        "</manifest>\n"
    )
    (manifests_dir / _ALT_MANIFEST_FILENAME).write_text(alt_xml, encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo diffmanifests with one manifest exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsHappyPathOneManifest:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo diffmanifests' with one manifest arg exits 0.

    Note: The subcommand requires at least one positional manifest filename --
    there is no zero-argument form. 'Default args' means the minimum required
    argument: one manifest filename relative to ``.repo/manifests/``. When a
    single manifest is provided, the command compares it against the current
    manifest. In a freshly synced repo both manifests are identical so the
    command exits 0 with empty output. All exit-code assertions use the exact
    constant _EXPECTED_EXIT_CODE.
    """

    def test_diffmanifests_one_manifest_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <manifest>' with one manifest arg must exit 0.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo diffmanifests default.xml'. The manifest is compared against
        the current manifest; since both are identical the command exits 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} {_MANIFEST_FILENAME}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_diffmanifests_one_manifest_produces_empty_output_for_identical_manifests(
        self, tmp_path: pathlib.Path
    ) -> None:
        """'kanon repo diffmanifests <manifest>' produces empty output when manifest equals current.

        In a freshly synced repository, the supplied manifest file is identical
        to the current manifest. No projects are added, removed, or changed, so
        both stdout and stderr must be empty on a successful invocation.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} {_MANIFEST_FILENAME}' "
            f"failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined == _EMPTY_OUTPUT, (
            f"'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} {_MANIFEST_FILENAME}' produced unexpected "
            f"output when comparing identical manifests.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "extra_args",
        [
            [_FLAG_NO_COLOR],
            [_FLAG_RAW],
            [f"{_FLAG_PRETTY_FORMAT}={_PRETTY_FORMAT_VALUE}"],
        ],
        ids=["no-color", "raw", "pretty-format"],
    )
    def test_diffmanifests_with_flag_exits_zero(self, tmp_path: pathlib.Path, extra_args: list[str]) -> None:
        """'kanon repo diffmanifests <flag> <manifest>' exits 0 in a synced repo.

        Parametrized over three optional flags: --no-color (disables ANSI colour
        codes), --raw (machine-parseable output format), and --pretty-format=<fmt>
        (custom git log format string). When the manifests are identical, the
        command exits 0 regardless of which flag is supplied.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            *extra_args,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} {' '.join(extra_args)} {_MANIFEST_FILENAME}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo diffmanifests has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsTwoManifestArgs:
    """AC-TEST-002: happy-path tests for both positional manifest arguments.

    'repo diffmanifests' accepts one or two positional manifest filename arguments.
    When two manifest filenames are supplied, the command compares them against
    each other. This class verifies the two-manifest invocation path: comparing
    identical manifests (exits 0, empty output) and comparing different manifests
    (exits 0, non-empty diff output).
    """

    def test_diffmanifests_two_identical_manifests_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <m1> <m2>' with two identical manifests exits 0.

        After a successful 'kanon repo init' and 'kanon repo sync', passes the
        same manifest filename twice as positional arguments. The projects are
        identical so the command exits 0 with empty output.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} {_MANIFEST_FILENAME} {_MANIFEST_FILENAME}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_diffmanifests_two_identical_manifests_produces_empty_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <m1> <m2>' produces empty output for identical manifests.

        When both positional manifest arguments refer to the same file, no
        projects differ, so both stdout and stderr must be empty on a successful
        invocation.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} "
            f"{_MANIFEST_FILENAME} {_MANIFEST_FILENAME}' failed: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert combined == _EMPTY_OUTPUT, (
            f"'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} {_MANIFEST_FILENAME} {_MANIFEST_FILENAME}' "
            f"produced unexpected output for identical manifests.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_diffmanifests_two_different_manifests_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <m1> <m2>' with two different manifests exits 0.

        After init and sync, an alternate manifest with a different project path
        is written to ``.repo/manifests/``. Comparing the default manifest against
        the alternate manifest produces a diff (added and removed project entries)
        but still exits 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        manifests_dir = repo_dir / "manifests"
        fetch_base = f"file://{repo_dir / 'objects'}"
        _write_alt_manifest(manifests_dir, fetch_base)

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            _ALT_MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} "
            f"{_MANIFEST_FILENAME} {_ALT_MANIFEST_FILENAME}' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_diffmanifests_two_different_manifests_shows_diff_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <m1> <m2>' emits diff output for different manifests.

        When the two supplied manifest files have different project paths, the
        command exits 0 and produces output describing the added and removed
        projects in combined stdout and stderr.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        manifests_dir = repo_dir / "manifests"
        fetch_base = f"file://{repo_dir / 'objects'}"
        _write_alt_manifest(manifests_dir, fetch_base)

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            _ALT_MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} "
            f"{_MANIFEST_FILENAME} {_ALT_MANIFEST_FILENAME}' failed: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert _PHRASE_ADDED_PROJECTS in combined and _PHRASE_REMOVED_PROJECTS in combined, (
            f"Expected both '{_PHRASE_ADDED_PROJECTS}' and '{_PHRASE_REMOVED_PROJECTS}' "
            f"in output of 'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS} "
            f"{_MANIFEST_FILENAME} {_ALT_MANIFEST_FILENAME}' -- the alt manifest "
            f"uses the same project name but a different path, so the diff must "
            f"contain both added and removed project entries.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo diffmanifests'.

    Verifies that successful 'kanon repo diffmanifests' invocations do not write
    Python tracebacks or '{prefix}' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """.format(prefix=_ERROR_PREFIX)

    def test_diffmanifests_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo diffmanifests' must not emit Python tracebacks to stdout.

        On success, stdout must not contain '{marker}'. Tracebacks on stdout
        indicate an unhandled exception that escaped to the wrong channel.
        """.format(marker=_TRACEBACK_MARKER)
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS}' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful "
            f"'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS}'.\n  stdout: {result.stdout!r}"
        )

    def test_diffmanifests_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo diffmanifests' must not emit '{prefix}' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with '{prefix}' on stdout.
        """.format(prefix=_ERROR_PREFIX)
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS}' failed: {result.stderr!r}"
        )
        error_lines = [line for line in result.stdout.splitlines() if line.startswith(_ERROR_PREFIX)]
        assert error_lines == [], (
            f"'{_ERROR_PREFIX}' lines found in stdout of successful "
            f"'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS}': {error_lines!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_diffmanifests_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo diffmanifests' must not emit Python tracebacks to stderr.

        On success, stderr must not contain '{marker}'. A traceback on stderr
        during a successful run indicates an unhandled exception was swallowed
        rather than propagated correctly.
        """.format(marker=_TRACEBACK_MARKER)
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            _CMD_REPO,
            _OPT_REPO_DIR,
            str(repo_dir),
            _CMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS}' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful "
            f"'kanon {_CMD_REPO} {_CMD_DIFFMANIFESTS}'.\n  stderr: {result.stderr!r}"
        )
