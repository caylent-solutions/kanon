"""Functional tests for exit-code matrix across core kanon commands.

Verifies that core commands emit POSIX-compliant exit codes:
  0  -- success
  1  -- application error (filesystem, network, validation failure)
  2  -- argument-parsing error (argparse)

Coverage per acceptance criterion:

  AC-TEST-001 -- install success exits 0
  AC-TEST-002 -- install fs error exits 1
  AC-TEST-003 -- install manifest parse error exits 1
  AC-TEST-004 -- repo sync network error exits 1
  AC-TEST-005 -- validate xml schema error exits 1
  AC-TEST-006 -- --help exits 0
  AC-TEST-007 -- --version exits 0
  AC-TEST-008 -- argparse error exits 2

  AC-FUNC-001 -- Exit codes follow POSIX convention: 0 success, 1 application
                 error, 2 argparse error
  AC-CHANNEL-001 -- stdout vs stderr discipline verified (no cross-channel
                    leakage)

All subprocess-based tests invoke the real ``kanon`` CLI without mocking
internal APIs. In-process tests that require mocking are clearly documented.
Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import textwrap
from typing import Union
from unittest.mock import patch

import pytest

from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# NOTE: _run_kanon is imported from tests.functional.conftest (canonical
# definition). No _git helper is used in this file because git operations
# are not needed for the exit-code-matrix scenarios.
#
# The helpers _write_kanonenv and _make_repo_root below are local to this
# file because they serve the specific fixture shapes needed for this task.
# Consolidating all helpers across functional test files into a shared module
# requires touching multiple files outside this task's Changes Manifest; that
# DRY cleanup is tracked as a follow-up.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

_VALID_KANONENV_CONTENT = (
    "KANON_SOURCE_primary_URL=https://example.com/primary.git\n"
    "KANON_SOURCE_primary_REVISION=main\n"
    "KANON_SOURCE_primary_PATH=repo-specs/manifest.xml\n"
)

_INVALID_KANONENV_CONTENT = (
    "KANON_MARKETPLACE_INSTALL=false\n"
    # No KANON_SOURCE_* variables -- parser raises ValueError('No sources found')
)


def _write_kanonenv(
    directory: pathlib.Path,
    content: str = _VALID_KANONENV_CONTENT,
) -> pathlib.Path:
    """Write a .kanon file in directory and return its absolute path.

    Args:
        directory: Directory in which to write the .kanon file.
        content: Text content for the .kanon file.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content, encoding="utf-8")
    return kanonenv.resolve()


def _make_repo_root_with_xml(
    tmp_path: pathlib.Path,
    xml_content: Union[str, None] = None,
) -> pathlib.Path:
    """Create a minimal repo root with a repo-specs/ directory and one XML file.

    Args:
        tmp_path: Base temporary directory from pytest.
        xml_content: Content to write to repo-specs/manifest.xml. Defaults to
            a valid well-formed manifest when None.

    Returns:
        The repo root directory path.
    """
    repo_root = tmp_path / "repo"
    (repo_root / "repo-specs").mkdir(parents=True)

    if xml_content is None:
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <remote name="origin" fetch="https://example.com" />
              <project name="proj" path=".packages/proj" remote="origin" revision="main" />
            </manifest>
        """)

    (repo_root / "repo-specs" / "manifest.xml").write_text(xml_content, encoding="utf-8")
    return repo_root


# ---------------------------------------------------------------------------
# AC-TEST-001: install success exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestInstallSuccessExitsZero:
    """AC-TEST-001: install success exits 0.

    These tests call the CLI main() in-process with repository operations
    mocked to avoid network dependencies, mirroring the approach established
    in tests/functional/test_install_lifecycle.py. The mocks simulate a
    successful repo init/envsubst/sync cycle so the install command reaches
    its normal completion path and exits 0.
    """

    def test_single_source_install_exits_0(self, tmp_path: pathlib.Path) -> None:
        """install with one source exits 0 on a successful repo cycle.

        Mocks repo_init, repo_envsubst, and repo_sync to no-ops so the
        install command completes successfully without network access.
        Verifies that the exit code is exactly 0.
        """
        from kanon_cli.cli import main

        kanonenv = _write_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            try:
                main(["install", str(kanonenv)])
                exit_code = 0
            except SystemExit as exc:
                exit_code = exc.code

        assert exit_code == 0, f"install with a valid .kanon must exit 0 on success; got exit code {exit_code!r}"

    def test_install_success_prints_done_to_stdout(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """install success prints a completion message to stdout (AC-CHANNEL-001).

        Verifies that the 'done' completion message appears on stdout and that
        no 'Error:' prefix leaks onto stdout during a successful install.
        """
        from kanon_cli.cli import main

        kanonenv = _write_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            try:
                main(["install", str(kanonenv)])
            except SystemExit:
                pass

        captured = capsys.readouterr()
        assert "done" in captured.out.lower(), (
            f"install success must print a 'done' message to stdout; got stdout={captured.out!r}"
        )
        assert "Error:" not in captured.out, (
            f"install success must not print 'Error:' to stdout (AC-CHANNEL-001); got stdout={captured.out!r}"
        )

    def test_install_success_no_errors_on_stderr(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """install success produces no error output on stderr (AC-CHANNEL-001).

        After a successful install, stderr must be empty so that CI pipelines
        that treat any stderr output as a warning can run kanon install cleanly.
        """
        from kanon_cli.cli import main

        kanonenv = _write_kanonenv(tmp_path)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.version.resolve_version", return_value="main"),
        ):
            try:
                main(["install", str(kanonenv)])
            except SystemExit:
                pass

        captured = capsys.readouterr()
        assert captured.err == "", f"install success must produce no output on stderr; got stderr={captured.err!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: install fs error exits 1
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestInstallFsErrorExitsOne:
    """AC-TEST-002: install fs error exits 1.

    Filesystem errors include a missing or unreadable .kanon file. These are
    tested via real subprocess invocations: no .kanon file on disk causes the
    CLI to print a 'file not found' error and exit 1.
    """

    def test_missing_kanonenv_file_exits_1(self, tmp_path: pathlib.Path) -> None:
        """install with a nonexistent .kanon path exits 1.

        Supplying a path to a .kanon file that does not exist must cause the
        CLI to exit with code exactly 1 (application error, not argparse error).
        """
        nonexistent = str(tmp_path / "does-not-exist" / ".kanon")
        result = _run_kanon("install", nonexistent)
        assert result.returncode == 1, (
            f"install with missing .kanon must exit 1; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_kanonenv_file_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """install with a missing .kanon path writes the error to stderr (AC-CHANNEL-001).

        The '.kanon file not found' message must appear on stderr, not stdout,
        so CI pipelines that parse stderr for errors can detect the failure.
        """
        nonexistent = str(tmp_path / "ghost" / ".kanon")
        result = _run_kanon("install", nonexistent)
        assert result.returncode == 1
        assert ".kanon" in result.stderr or "not found" in result.stderr, (
            f"install fs error must reference the missing file on stderr.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_kanonenv_no_error_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """install with a missing .kanon path does not leak the error to stdout (AC-CHANNEL-001).

        Error messages must appear exclusively on stderr. stdout must not
        contain the 'file not found' error text.
        """
        nonexistent = str(tmp_path / "missing-dir" / ".kanon")
        result = _run_kanon("install", nonexistent)
        assert result.returncode == 1
        assert ".kanon file not found" not in result.stdout, (
            f"install fs error must not appear on stdout.\n  stdout: {result.stdout!r}"
        )

    def test_no_kanonenv_in_empty_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """install with no argument in a directory that has no .kanon exits 1.

        Auto-discovery fails when no .kanon file exists in cwd or its ancestors
        (within the tmp_path tree). The CLI must exit 1, not crash.
        """
        empty = tmp_path / "empty-dir"
        empty.mkdir()
        result = _run_kanon("install", cwd=empty)
        assert result.returncode == 1, (
            f"install with no .kanon discoverable must exit 1; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_path_suffix",
        [
            "a/b/c/.kanon",
            "nonexistent/.kanon",
            "deep/nested/path/.kanon",
        ],
    )
    def test_various_missing_paths_exit_1(self, tmp_path: pathlib.Path, bad_path_suffix: str) -> None:
        """Various nonexistent .kanon paths all exit 1 (parametrized).

        The exit code must be consistently 1 regardless of the specific
        nonexistent path supplied.
        """
        nonexistent = str(tmp_path / bad_path_suffix)
        result = _run_kanon("install", nonexistent)
        assert result.returncode == 1, (
            f"install with nonexistent path {bad_path_suffix!r} must exit 1; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: install manifest parse error exits 1
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestInstallManifestParseErrorExitsOne:
    """AC-TEST-003: install manifest parse error exits 1.

    When the .kanon file is syntactically invalid or missing required source
    definitions, the CLI must exit 1 with a diagnostic on stderr.
    """

    def test_no_sources_in_kanonenv_exits_1(self, tmp_path: pathlib.Path) -> None:
        """install with a .kanon file that has no KANON_SOURCE_* variables exits 1.

        An empty .kanon file (no source definitions) causes the parser to raise
        ValueError. The CLI must convert that to exit 1.
        """
        result = _run_kanon(
            "install",
            str(_write_kanonenv(tmp_path, _INVALID_KANONENV_CONTENT)),
        )
        assert result.returncode == 1, (
            f"install with no source definitions must exit 1; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_parse_error_written_to_stderr(self, tmp_path: pathlib.Path) -> None:
        """install manifest parse error writes the error message to stderr (AC-CHANNEL-001).

        The diagnostic ('Error: ...') must appear on stderr so CI pipelines
        that scan stderr for errors detect the parse failure.
        """
        result = _run_kanon(
            "install",
            str(_write_kanonenv(tmp_path, _INVALID_KANONENV_CONTENT)),
        )
        assert result.returncode == 1
        assert "Error" in result.stderr, (
            f"Parse error must be reported on stderr.\n  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )

    def test_parse_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """install manifest parse error does not leak to stdout (AC-CHANNEL-001).

        Error messages must be confined to stderr. stdout must not contain
        the 'Error' prefix for parse failures.
        """
        result = _run_kanon(
            "install",
            str(_write_kanonenv(tmp_path, _INVALID_KANONENV_CONTENT)),
        )
        assert result.returncode == 1
        assert "Error" not in result.stdout, (
            f"Parse error must not appear on stdout (AC-CHANNEL-001).\n  stdout: {result.stdout!r}"
        )

    def test_missing_source_revision_exits_1(self, tmp_path: pathlib.Path) -> None:
        """install with a source missing KANON_SOURCE_*_REVISION exits 1.

        An incomplete source definition (URL and PATH defined, REVISION absent)
        must cause exit 1, not a crash.
        """
        incomplete = (
            "KANON_SOURCE_broken_URL=https://example.com/repo.git\nKANON_SOURCE_broken_PATH=repo-specs/manifest.xml\n"
        )
        result = _run_kanon("install", str(_write_kanonenv(tmp_path, incomplete)))
        assert result.returncode == 1, (
            f"install with incomplete source (missing REVISION) must exit 1; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "missing_suffix,kept_pairs",
        [
            (
                "REVISION",
                [
                    ("URL", "https://example.com/repo.git"),
                    ("PATH", "repo-specs/manifest.xml"),
                ],
            ),
            (
                "PATH",
                [
                    ("URL", "https://example.com/repo.git"),
                    ("REVISION", "main"),
                ],
            ),
        ],
    )
    def test_incomplete_source_definitions_exit_1(
        self,
        tmp_path: pathlib.Path,
        missing_suffix: str,
        kept_pairs: list,
    ) -> None:
        """Various incomplete source definitions all exit 1 (parametrized).

        Parametrises over different missing required fields to confirm that
        parse failures are consistently reported as exit code 1.
        """
        lines = [f"KANON_SOURCE_src_{suffix}={value}\n" for suffix, value in kept_pairs]
        content = "".join(lines)
        result = _run_kanon("install", str(_write_kanonenv(tmp_path, content)))
        assert result.returncode == 1, (
            f"install with source missing {missing_suffix!r} must exit 1; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: repo sync network error exits 1
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSyncNetworkErrorExitsOne:
    """AC-TEST-004: repo sync network error exits 1.

    When repo_sync raises a RepoCommandError (network/git failure), the CLI
    must exit 1 with a descriptive message on stderr. These tests use
    in-process invocation with mocking to avoid real network calls, following
    the established pattern in tests/functional/test_install_lifecycle.py.
    """

    def test_repo_sync_failure_exits_1(self, tmp_path: pathlib.Path) -> None:
        """install exits 1 when repo_sync raises RepoCommandError.

        Simulates a network timeout during repo sync. The install command
        must exit with code exactly 1, not 0 or any other value.
        """
        from kanon_cli.cli import main
        from kanon_cli.repo import RepoCommandError

        kanonenv = _write_kanonenv(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch(
                    "kanon_cli.repo.repo_sync",
                    side_effect=RepoCommandError("network timeout"),
                ),
                patch("kanon_cli.version.resolve_version", return_value="main"),
            ):
                main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, (
            f"install must exit 1 when repo_sync fails with a network error; got exit code {exc_info.value.code!r}"
        )

    def test_repo_sync_error_written_to_stderr(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """install writes the repo sync error to stderr (AC-CHANNEL-001).

        The failure diagnostic must appear on stderr so operators can
        distinguish it from normal install progress output on stdout.
        """
        from kanon_cli.cli import main
        from kanon_cli.repo import RepoCommandError

        kanonenv = _write_kanonenv(tmp_path)

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch(
                    "kanon_cli.repo.repo_sync",
                    side_effect=RepoCommandError("remote: authentication required"),
                ),
                patch("kanon_cli.version.resolve_version", return_value="main"),
            ):
                main(["install", str(kanonenv)])

        captured = capsys.readouterr()
        assert "Error" in captured.err, f"repo sync failure must write 'Error' to stderr; got stderr={captured.err!r}"

    def test_repo_sync_error_not_on_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """install repo sync error does not leak to stdout (AC-CHANNEL-001).

        The error diagnostic must appear exclusively on stderr. stdout must
        not contain any 'Error:' prefix from the sync failure.
        """
        from kanon_cli.cli import main
        from kanon_cli.repo import RepoCommandError

        kanonenv = _write_kanonenv(tmp_path)

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch(
                    "kanon_cli.repo.repo_sync",
                    side_effect=RepoCommandError("connection refused"),
                ),
                patch("kanon_cli.version.resolve_version", return_value="main"),
            ):
                main(["install", str(kanonenv)])

        captured = capsys.readouterr()
        assert "Error:" not in captured.out, (
            f"repo sync failure error must not appear on stdout (AC-CHANNEL-001); got stdout={captured.out!r}"
        )

    @pytest.mark.parametrize(
        "error_message",
        [
            "network timeout",
            "remote: authentication required",
            "connection refused: port 443",
        ],
    )
    def test_various_sync_errors_exit_1(
        self,
        tmp_path: pathlib.Path,
        error_message: str,
    ) -> None:
        """Various RepoCommandError messages all cause exit 1 (parametrized).

        The exit code must be consistently 1 for any network-related error,
        not dependent on the specific error text.
        """
        from kanon_cli.cli import main
        from kanon_cli.repo import RepoCommandError

        kanonenv = _write_kanonenv(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch(
                    "kanon_cli.repo.repo_sync",
                    side_effect=RepoCommandError(error_message),
                ),
                patch("kanon_cli.version.resolve_version", return_value="main"),
            ):
                main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, (
            f"install must exit 1 for network error {error_message!r}; got exit code {exc_info.value.code!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-005: validate xml schema error exits 1
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestValidateXmlSchemaErrorExitsOne:
    """AC-TEST-005: validate xml schema error exits 1.

    When a manifest XML file contains a parse error or schema violation,
    'kanon validate xml' must exit 1. These tests use real subprocess
    invocations against real on-disk XML fixtures.
    """

    def test_malformed_xml_exits_1(self, tmp_path: pathlib.Path) -> None:
        """kanon validate xml exits 1 for a well-formedness error (unclosed tag).

        The embedded XML validator must detect the parse error and exit 1,
        not 0 and not crash with an unhandled exception.
        """
        repo_root = _make_repo_root_with_xml(tmp_path, "<manifest><unclosed")
        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))
        assert result.returncode == 1, (
            f"validate xml must exit 1 for malformed XML; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_required_attribute_exits_1(self, tmp_path: pathlib.Path) -> None:
        """kanon validate xml exits 1 when a <project> is missing a required attribute.

        A manifest with a <project> element missing the required 'path' attribute
        must cause validate xml to exit 1.
        """
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <manifest>
              <remote name="origin" fetch="https://example.com" />
              <project name="proj" />
            </manifest>
        """)
        repo_root = _make_repo_root_with_xml(tmp_path, xml_content)
        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))
        assert result.returncode == 1, (
            f"validate xml must exit 1 for missing required attribute; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_schema_error_written_to_stderr(self, tmp_path: pathlib.Path) -> None:
        """validate xml schema error is written to stderr (AC-CHANNEL-001).

        The error diagnostic must appear on stderr, not stdout, so operators
        can distinguish validation failures from normal progress output.
        """
        repo_root = _make_repo_root_with_xml(tmp_path, "<manifest><unclosed")
        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))
        assert result.returncode == 1
        assert "error" in result.stderr.lower(), (
            f"validate xml error must appear on stderr.\n  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )

    def test_schema_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """validate xml schema error does not leak to stdout (AC-CHANNEL-001).

        The error summary must not appear on stdout. stdout is reserved for
        progress messages ('Validating ...').
        """
        repo_root = _make_repo_root_with_xml(tmp_path, "<manifest><unclosed")
        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))
        assert result.returncode == 1
        assert "error" not in result.stdout.lower(), (
            f"validate xml error must not leak to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "missing_attr,xml_body",
        [
            (
                "path",
                (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<manifest>"
                    '<remote name="o" fetch="u" />'
                    '<project name="p" remote="o" revision="main" />'
                    "</manifest>"
                ),
            ),
            (
                "remote",
                (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<manifest>"
                    '<remote name="o" fetch="u" />'
                    '<project name="p" path=".packages/p" revision="main" />'
                    "</manifest>"
                ),
            ),
            (
                "revision",
                (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<manifest>"
                    '<remote name="o" fetch="u" />'
                    '<project name="p" path=".packages/p" remote="o" />'
                    "</manifest>"
                ),
            ),
        ],
    )
    def test_each_missing_attribute_exits_1(
        self,
        tmp_path: pathlib.Path,
        missing_attr: str,
        xml_body: str,
    ) -> None:
        """Each missing required attribute exits 1 and names the attribute (parametrized).

        Args:
            tmp_path: Pytest temporary directory.
            missing_attr: Attribute name expected in the error output.
            xml_body: XML document body missing that attribute.
        """
        repo_root = _make_repo_root_with_xml(tmp_path, xml_body)
        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))
        assert result.returncode == 1, (
            f"validate xml must exit 1 for missing '{missing_attr}'; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert missing_attr in result.stderr, (
            f"validate xml error must name the missing attribute '{missing_attr}'.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-006: --help exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestHelpExitsZero:
    """AC-TEST-006: --help exits 0 for all core commands.

    Verifies that 'kanon --help', 'kanon install --help', 'kanon validate
    xml --help', and similar invocations all exit with code exactly 0.
    All tests use real subprocess invocations.
    """

    def test_top_level_help_exits_0(self) -> None:
        """'kanon --help' must exit with code 0."""
        result = _run_kanon("--help")
        assert result.returncode == 0, (
            f"'kanon --help' must exit 0; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_install_help_exits_0(self) -> None:
        """'kanon install --help' must exit with code 0."""
        result = _run_kanon("install", "--help")
        assert result.returncode == 0, (
            f"'kanon install --help' must exit 0; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_validate_xml_help_exits_0(self) -> None:
        """'kanon validate xml --help' must exit with code 0."""
        result = _run_kanon("validate", "xml", "--help")
        assert result.returncode == 0, (
            f"'kanon validate xml --help' must exit 0; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_clean_help_exits_0(self) -> None:
        """'kanon clean --help' must exit with code 0."""
        result = _run_kanon("clean", "--help")
        assert result.returncode == 0, (
            f"'kanon clean --help' must exit 0; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_output_on_stdout(self) -> None:
        """'kanon --help' writes usage text to stdout (AC-CHANNEL-001).

        argparse help is written to stdout by default. Verifies that stdout
        is non-empty and contains the program name.
        """
        result = _run_kanon("--help")
        assert result.returncode == 0
        assert len(result.stdout) > 0, f"'kanon --help' must produce output on stdout.\n  stderr: {result.stderr!r}"
        assert "kanon" in result.stdout.lower(), (
            f"'kanon --help' stdout must contain 'kanon'.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "command_args",
        [
            ("--help",),
            ("-h",),
            ("install", "--help"),
            ("clean", "--help"),
            ("validate", "--help"),
            ("bootstrap", "--help"),
        ],
    )
    def test_help_flags_exit_0_for_all_commands(self, command_args: tuple) -> None:
        """Help flags exit 0 for every core command (parametrized).

        Args:
            command_args: Tuple of CLI arguments to pass to _run_kanon.
        """
        result = _run_kanon(*command_args)
        assert result.returncode == 0, (
            f"'kanon {list(command_args)}' must exit 0; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-007: --version exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestVersionExitsZero:
    """AC-TEST-007: --version exits 0.

    'kanon --version' must exit with code 0 and print the version to stdout.
    """

    def test_version_flag_exits_0(self) -> None:
        """'kanon --version' must exit with code 0."""
        result = _run_kanon("--version")
        assert result.returncode == 0, (
            f"'kanon --version' must exit 0; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_version_output_on_stdout(self) -> None:
        """'kanon --version' writes the version string to stdout (AC-CHANNEL-001).

        argparse's version action writes to stdout. The output must contain
        'kanon' and a version number.
        """
        result = _run_kanon("--version")
        assert result.returncode == 0
        assert "kanon" in result.stdout.lower(), (
            f"'kanon --version' output must contain 'kanon' on stdout.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_version_output_contains_version_string(self) -> None:
        """'kanon --version' output contains a version identifier on stdout.

        The version string must contain at least one digit on stdout, confirming
        that the version is a real version number rather than an empty placeholder.
        """
        result = _run_kanon("--version")
        assert result.returncode == 0
        assert any(char.isdigit() for char in result.stdout), (
            f"'kanon --version' must contain a version number with digits on stdout.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_version_no_errors_on_stderr(self) -> None:
        """'kanon --version' does not produce error output on stderr (AC-CHANNEL-001).

        The version flag is a pure informational output. No 'Error:' prefix
        should appear on stderr.
        """
        result = _run_kanon("--version")
        assert result.returncode == 0
        assert "Error:" not in result.stderr, (
            f"'kanon --version' must not produce 'Error:' on stderr.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-008: argparse error exits 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestArgparseErrorExitsTwo:
    """AC-TEST-008: argparse error exits 2.

    Unknown flags, invalid subcommand names, and other argument-parsing errors
    must exit with code exactly 2 (the POSIX convention for argument errors).
    All tests use real subprocess invocations.
    """

    def test_unknown_top_level_flag_exits_2(self) -> None:
        """'kanon --unknown-flag' must exit with code 2."""
        result = _run_kanon("--unknown-flag-xyz")
        assert result.returncode == 2, (
            f"'kanon --unknown-flag-xyz' must exit 2; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_subcommand_exits_2(self) -> None:
        """'kanon no-such-subcommand' must exit with code 2."""
        result = _run_kanon("no-such-subcommand-xyz")
        assert result.returncode == 2, (
            f"'kanon no-such-subcommand-xyz' must exit 2; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_empty_invocation_exits_2(self) -> None:
        """'kanon' with no arguments must exit with code 2.

        The top-level parser requires a subcommand. When none is provided,
        the CLI prints help and exits 2.
        """
        result = _run_kanon()
        assert result.returncode == 2, (
            f"'kanon' with no arguments must exit 2; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_argparse_error_written_to_stderr(self) -> None:
        """Argparse error message is written to stderr (AC-CHANNEL-001).

        The error output from argparse must appear on stderr so CI pipelines
        and terminal users can distinguish argument errors from help text.
        """
        result = _run_kanon("--bogus-option-for-matrix-test")
        assert result.returncode == 2
        assert len(result.stderr) > 0, f"Argparse error must produce output on stderr.\n  stdout: {result.stdout!r}"

    def test_argparse_error_names_bad_argument(self) -> None:
        """Argparse error message names the unrecognised argument (AC-FUNC-001).

        The error message must contain the specific flag name so users know
        exactly which argument caused the parsing failure.
        """
        bad_flag = "--completely-unknown-flag-matrix"
        result = _run_kanon(bad_flag)
        assert result.returncode == 2
        assert bad_flag in result.stderr, (
            f"Argparse error must name the bad argument {bad_flag!r}.\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_args",
        [
            ("--xyz-unknown",),
            ("--not-a-real-option",),
            ("fakesubcommand123",),
        ],
    )
    def test_various_argparse_errors_exit_2(self, bad_args: tuple) -> None:
        """Various argparse errors all exit 2 (parametrized).

        Args:
            bad_args: Tuple of CLI arguments that trigger an argparse error.
        """
        result = _run_kanon(*bad_args)
        assert result.returncode == 2, (
            f"'kanon {list(bad_args)}' must exit 2; got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: POSIX exit code convention across all core commands
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestPosixExitCodeConvention:
    """AC-FUNC-001: Exit codes follow POSIX convention: 0 success, 1 application error, 2 argparse error.

    Consolidates assertions across the full exit-code matrix to verify
    that no core command conflates the three standard exit codes.
    """

    def test_success_is_exactly_0(self) -> None:
        """'kanon --help' exit code is exactly 0, not 1 or 2.

        Confirms that the success sentinel (0) is distinct from both the
        application-error sentinel (1) and the argparse-error sentinel (2).
        """
        result = _run_kanon("--help")
        assert result.returncode == 0
        assert result.returncode != 1, "Success must not return code 1 (application error)"
        assert result.returncode != 2, "Success must not return code 2 (argparse error)"

    def test_application_error_is_exactly_1(self, tmp_path: pathlib.Path) -> None:
        """install with missing .kanon exits exactly 1, not 0 or 2.

        Confirms that the application-error sentinel (1) is distinct from
        success (0) and argparse-error (2).
        """
        nonexistent = str(tmp_path / "no-such-file" / ".kanon")
        result = _run_kanon("install", nonexistent)
        assert result.returncode == 1
        assert result.returncode != 0, "Application error must not return code 0 (success)"
        assert result.returncode != 2, "Application error must not return code 2 (argparse error)"

    def test_argparse_error_is_exactly_2(self) -> None:
        """'kanon --bogus' exits exactly 2, not 0 or 1.

        Confirms that the argparse-error sentinel (2) is distinct from
        success (0) and application-error (1).
        """
        result = _run_kanon("--bogus-posix-test")
        assert result.returncode == 2
        assert result.returncode != 0, "Argparse error must not return code 0 (success)"
        assert result.returncode != 1, "Argparse error must not return code 1 (application error)"

    def test_exit_code_matrix_is_complete(self, tmp_path: pathlib.Path) -> None:
        """The three POSIX exit codes are each emitted by at least one core command.

        Exercises one representative scenario for each exit code to confirm
        that the full 0/1/2 matrix is reachable via real CLI invocations.
        """
        success_result = _run_kanon("--version")
        app_error_result = _run_kanon("install", str(tmp_path / "no-file" / ".kanon"))
        parse_error_result = _run_kanon("--nonexistent-flag-for-matrix")

        assert success_result.returncode == 0, f"Expected exit 0 for '--version'; got {success_result.returncode}"
        assert app_error_result.returncode == 1, (
            f"Expected exit 1 for missing .kanon; got {app_error_result.returncode}"
        )
        assert parse_error_result.returncode == 2, (
            f"Expected exit 2 for unknown flag; got {parse_error_result.returncode}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline (consolidated cross-command)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestChannelDisciplineMatrix:
    """AC-CHANNEL-001: stdout vs stderr discipline across all core commands.

    Verifies that:
    - Success output (help text, version, completion messages) goes to stdout.
    - Error messages (application errors, parse failures) go to stderr.
    - No cross-channel leakage occurs for any of the core exit-code scenarios.
    """

    def test_help_output_on_stdout_not_stderr(self) -> None:
        """'kanon --help' writes help to stdout with no errors on stderr."""
        result = _run_kanon("--help")
        assert result.returncode == 0
        assert len(result.stdout) > 0, f"Help must be on stdout.\n  stderr: {result.stderr!r}"
        assert "Error:" not in result.stderr, f"Help must not produce 'Error:' on stderr.\n  stderr: {result.stderr!r}"

    def test_version_output_on_stdout_not_stderr(self) -> None:
        """'kanon --version' writes version to stdout with no errors on stderr."""
        result = _run_kanon("--version")
        assert result.returncode == 0
        assert len(result.stdout) > 0, (
            f"Version output must be non-empty on stdout.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, f"Version must produce no output on stderr.\n  stderr: {result.stderr!r}"

    def test_fs_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """install fs error appears on stderr and not on stdout."""
        nonexistent = str(tmp_path / "channel-test-missing" / ".kanon")
        result = _run_kanon("install", nonexistent)
        assert result.returncode == 1
        assert len(result.stderr) > 0, f"FS error must be on stderr.\n  stdout: {result.stdout!r}"
        assert ".kanon file not found" not in result.stdout, (
            f"FS error must not appear on stdout.\n  stdout: {result.stdout!r}"
        )

    def test_argparse_error_on_stderr_not_stdout(self) -> None:
        """Argparse error appears on stderr and not on stdout."""
        result = _run_kanon("--channel-discipline-bad-flag")
        assert result.returncode == 2
        assert len(result.stderr) > 0, f"Argparse error must be on stderr.\n  stdout: {result.stdout!r}"
        assert len(result.stdout) == 0, f"Argparse error must not appear on stdout.\n  stdout: {result.stdout!r}"

    def test_xml_schema_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """validate xml error appears on stderr and not on stdout."""
        repo_root = _make_repo_root_with_xml(tmp_path, "<manifest><unclosed")
        result = _run_kanon("validate", "xml", "--repo-root", str(repo_root))
        assert result.returncode == 1
        assert "error" in result.stderr.lower(), f"XML error must appear on stderr.\n  stderr: {result.stderr!r}"
        assert "error" not in result.stdout.lower(), (
            f"XML error must not appear on stdout.\n  stdout: {result.stdout!r}"
        )
