"""Integration tests for kanon install error paths (E1-F1-S2-T5).

Verifies that all install error paths exit non-zero with actionable stderr
diagnostics, satisfying the fail-fast contract of the CLI boundary.

AC-TEST-001: parse failure in .kanon exits 1 with parse error message
AC-TEST-002: git sync failure exits 1 with actionable message
AC-TEST-003: duplicate path collision across sources exits 1 with diagnostic

AC-FUNC-001: All install error paths exit non-zero with stderr diagnostics (fail fast)
AC-CHANNEL-001: stdout vs stderr discipline verified (no cross-channel leakage)
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.cli import main
from kanon_cli.repo import RepoCommandError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SOURCE_URL_TEMPLATE = "https://example.com/{name}.git"


def _write_kanonenv(directory: pathlib.Path, content: str) -> pathlib.Path:
    """Write a .kanon file in directory and return its absolute path.

    Args:
        directory: Directory in which to write the .kanon file.
        content: Text content for the .kanon file.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content)
    return kanonenv.resolve()


def _valid_single_source_content(source_name: str = "primary") -> str:
    """Return minimal valid .kanon content for a single source.

    Args:
        source_name: Source name embedded in KANON_SOURCE_* keys.

    Returns:
        Content string for a minimal valid single-source .kanon file.
    """
    url = _SOURCE_URL_TEMPLATE.format(name=source_name)
    return (
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_name}_URL={url}\n"
        f"KANON_SOURCE_{source_name}_REVISION=main\n"
        f"KANON_SOURCE_{source_name}_PATH=repo-specs/manifest.xml\n"
    )


def _valid_two_source_content(source_alpha: str = "alpha", source_bravo: str = "bravo") -> str:
    """Return minimal valid .kanon content for two sources.

    Args:
        source_alpha: First source name (alphabetically earlier).
        source_bravo: Second source name (alphabetically later).

    Returns:
        Content string for a minimal valid two-source .kanon file.
    """
    url_alpha = _SOURCE_URL_TEMPLATE.format(name=source_alpha)
    url_bravo = _SOURCE_URL_TEMPLATE.format(name=source_bravo)
    return (
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_{source_alpha}_URL={url_alpha}\n"
        f"KANON_SOURCE_{source_alpha}_REVISION=main\n"
        f"KANON_SOURCE_{source_alpha}_PATH=repo-specs/manifest.xml\n"
        f"KANON_SOURCE_{source_bravo}_URL={url_bravo}\n"
        f"KANON_SOURCE_{source_bravo}_REVISION=main\n"
        f"KANON_SOURCE_{source_bravo}_PATH=repo-specs/manifest.xml\n"
    )


def _populate_source_package(
    base_dir: pathlib.Path,
    source_name: str,
    package_name: str,
) -> None:
    """Create a package directory under .kanon-data/sources/<name>/.packages/.

    Simulates what repo sync would place on disk so aggregate_symlinks
    has real directories to process.

    Args:
        base_dir: Project root directory.
        source_name: Name of the source that owns the package.
        package_name: Name of the package directory to create.
    """
    pkg_dir = base_dir / ".kanon-data" / "sources" / source_name / ".packages" / package_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "README.md").write_text(f"# {package_name}\n")


# ---------------------------------------------------------------------------
# AC-TEST-001: parse failure in .kanon exits 1 with parse error message
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestParseFailureExitsOne:
    """AC-TEST-001: parse failure in .kanon exits 1 with parse error message.

    Verifies that when the .kanon file is syntactically invalid or missing
    required source variables, the CLI exits with code 1 and writes a
    diagnostic message to stderr -- not stdout.
    """

    def test_no_sources_defined_exits_1_with_parse_error(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A .kanon file with no KANON_SOURCE_* variables causes exit code 1.

        When there are no source definitions in .kanon, the parser raises a
        ValueError ('No sources found'). The CLI must convert that to exit 1
        with an error on stderr.
        """
        kanonenv = _write_kanonenv(tmp_path, "KANON_MARKETPLACE_INSTALL=false\n")

        with pytest.raises(SystemExit) as exc_info:
            main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, (
            f"install must exit 1 when no sources are defined; got code {exc_info.value.code}"
        )
        captured = capsys.readouterr()
        assert "Error" in captured.err, f"stderr must contain 'Error' for a parse failure; got stderr={captured.err!r}"
        assert captured.out == "" or "Error" not in captured.out, (
            f"parse error must not appear on stdout; got stdout={captured.out!r}"
        )

    def test_missing_revision_variable_exits_1_with_parse_error(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A .kanon source missing KANON_SOURCE_<name>_REVISION causes exit code 1.

        An incomplete source definition (URL and PATH defined, REVISION absent)
        fails validation. The CLI must exit 1 with a clear error on stderr naming
        the missing variable.
        """
        content = (
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_broken_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_broken_PATH=repo-specs/manifest.xml\n"
        )
        kanonenv = _write_kanonenv(tmp_path, content)

        with pytest.raises(SystemExit) as exc_info:
            main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, (
            f"install must exit 1 when source REVISION is missing; got code {exc_info.value.code}"
        )
        captured = capsys.readouterr()
        assert "Error" in captured.err, (
            f"stderr must contain 'Error' for a missing REVISION; got stderr={captured.err!r}"
        )

    def test_missing_path_variable_exits_1_with_parse_error(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A .kanon source missing KANON_SOURCE_<name>_PATH causes exit code 1.

        An incomplete source definition (URL and REVISION defined, PATH absent)
        fails validation. The CLI must exit 1 with an error on stderr.
        """
        content = (
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_incomplete_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_incomplete_REVISION=main\n"
        )
        kanonenv = _write_kanonenv(tmp_path, content)

        with pytest.raises(SystemExit) as exc_info:
            main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, (
            f"install must exit 1 when source PATH is missing; got code {exc_info.value.code}"
        )
        captured = capsys.readouterr()
        assert "Error" in captured.err, f"stderr must contain 'Error' for a missing PATH; got stderr={captured.err!r}"

    @pytest.mark.parametrize(
        "missing_suffix,kept_suffixes",
        [
            ("_REVISION", ("_URL", "_PATH")),
            ("_PATH", ("_URL", "_REVISION")),
        ],
    )
    def test_parse_error_output_goes_to_stderr_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
        missing_suffix: str,
        kept_suffixes: tuple[str, ...],
    ) -> None:
        """Parse error from missing source variable is written to stderr, not stdout.

        AC-CHANNEL-001: The CLI must not leak error messages onto stdout.
        """
        lines = ["KANON_MARKETPLACE_INSTALL=false\n"]
        for suffix in kept_suffixes:
            var = f"KANON_SOURCE_src{suffix}"
            if suffix == "_URL":
                lines.append(f"{var}=https://example.com/repo.git\n")
            elif suffix == "_REVISION":
                lines.append(f"{var}=main\n")
            elif suffix == "_PATH":
                lines.append(f"{var}=repo-specs/manifest.xml\n")
        kanonenv = _write_kanonenv(tmp_path, "".join(lines))

        with pytest.raises(SystemExit) as exc_info:
            main(["install", str(kanonenv)])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err, f"Error must appear on stderr; got stderr={captured.err!r}"
        assert "Error" not in captured.out, (
            f"Error must not appear on stdout (AC-CHANNEL-001); got stdout={captured.out!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: git sync failure exits 1 with actionable message
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGitSyncFailureExitsOne:
    """AC-TEST-002: git sync failure exits 1 with actionable message.

    Verifies that when repo_sync raises a RepoCommandError (simulating a
    network or git failure), the CLI exits with code 1 and writes a
    descriptive message to stderr with enough context for the operator
    to diagnose the failure.
    """

    def test_repo_sync_failure_exits_1(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """repo_sync failure causes install to exit with code 1.

        When repo_sync raises RepoCommandError, the install command must
        exit 1 -- not 0, not crash with an unhandled exception.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_single_source_content("primary"))

        with pytest.raises(SystemExit) as exc_info:
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch(
                    "kanon_cli.repo.repo_sync",
                    side_effect=RepoCommandError("network timeout"),
                ),
            ):
                main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, f"install must exit 1 on repo_sync failure; got code {exc_info.value.code}"

    def test_repo_sync_failure_writes_error_to_stderr(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """repo_sync failure writes an actionable error message to stderr.

        The error message must contain 'Error' so operators can distinguish
        it from normal progress output and must not appear on stdout.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_single_source_content("primary"))

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch(
                    "kanon_cli.repo.repo_sync",
                    side_effect=RepoCommandError("remote: authentication required"),
                ),
            ):
                main(["install", str(kanonenv)])

        captured = capsys.readouterr()
        assert "Error" in captured.err, f"stderr must contain 'Error' when repo_sync fails; got stderr={captured.err!r}"

    def test_repo_sync_failure_error_not_on_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """repo_sync failure error is written to stderr, not stdout (AC-CHANNEL-001).

        The error message must not appear on stdout -- stdout is for progress
        messages only.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_single_source_content("primary"))

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch(
                    "kanon_cli.repo.repo_sync",
                    side_effect=RepoCommandError("connection refused"),
                ),
            ):
                main(["install", str(kanonenv)])

        captured = capsys.readouterr()
        assert "Error" not in captured.out, (
            f"repo_sync failure error must not appear on stdout (AC-CHANNEL-001); got stdout={captured.out!r}"
        )

    def test_repo_init_failure_exits_1_with_actionable_message(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """repo_init failure also causes exit code 1 with stderr diagnostics.

        Git-related failures are not limited to sync: repo_init can also fail
        (e.g., if the manifest URL is unreachable). The CLI must handle this
        consistently with the same fail-fast contract.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_single_source_content("primary"))

        with pytest.raises(SystemExit) as exc_info:
            with (
                patch(
                    "kanon_cli.repo.repo_init",
                    side_effect=RepoCommandError("could not resolve host"),
                ),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, f"install must exit 1 on repo_init failure; got code {exc_info.value.code}"
        captured = capsys.readouterr()
        assert "Error" in captured.err, f"stderr must contain 'Error' when repo_init fails; got stderr={captured.err!r}"
        assert "Error" not in captured.out, (
            f"repo_init failure error must not appear on stdout; got stdout={captured.out!r}"
        )

    @pytest.mark.parametrize(
        "error_message",
        [
            "network timeout",
            "remote: authentication required",
            "connection refused: port 443",
        ],
    )
    def test_repo_sync_failure_exits_1_for_various_error_messages(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
        error_message: str,
    ) -> None:
        """repo_sync failure exits 1 regardless of the underlying error message.

        The exit code must always be 1 for any RepoCommandError, not dependent
        on the specific error text.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_single_source_content("primary"))

        with pytest.raises(SystemExit) as exc_info:
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch(
                    "kanon_cli.repo.repo_sync",
                    side_effect=RepoCommandError(error_message),
                ),
            ):
                main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, (
            f"install must exit 1 for error {error_message!r}; got code {exc_info.value.code}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: duplicate path collision across sources exits 1 with diagnostic
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDuplicatePathCollisionExitsOne:
    """AC-TEST-003: duplicate path collision across sources exits 1 with diagnostic.

    Verifies that when two sources provide a package with the same name,
    the install command exits with code 1 and writes a diagnostic message
    to stderr identifying both the colliding package and the conflicting
    sources.
    """

    def test_collision_between_two_sources_exits_1(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A duplicate package name across two sources causes exit code 1.

        Both 'alpha' and 'bravo' provide 'shared-pkg'. The install must detect
        this collision and exit 1, not silently overwrite the first symlink.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_two_source_content("alpha", "bravo"))
        _populate_source_package(tmp_path, "alpha", "shared-pkg")
        _populate_source_package(tmp_path, "bravo", "shared-pkg")

        with pytest.raises(SystemExit) as exc_info:
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, f"install must exit 1 on package collision; got code {exc_info.value.code}"

    def test_collision_diagnostic_names_colliding_package(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """The collision diagnostic names the colliding package on stderr.

        The operator must be able to identify which package caused the collision
        from the error message alone.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_two_source_content("alpha", "bravo"))
        _populate_source_package(tmp_path, "alpha", "collision-pkg")
        _populate_source_package(tmp_path, "bravo", "collision-pkg")

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                main(["install", str(kanonenv)])

        captured = capsys.readouterr()
        assert "collision-pkg" in captured.err, (
            f"Diagnostic must name the colliding package 'collision-pkg'; got stderr={captured.err!r}"
        )

    def test_collision_diagnostic_names_both_conflicting_sources(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """The collision diagnostic names both conflicting sources on stderr.

        The operator must see which two sources conflict so they know which
        .kanon source definitions to reconcile.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_two_source_content("alpha", "bravo"))
        _populate_source_package(tmp_path, "alpha", "conflict-tool")
        _populate_source_package(tmp_path, "bravo", "conflict-tool")

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                main(["install", str(kanonenv)])

        captured = capsys.readouterr()
        assert "alpha" in captured.err, f"Diagnostic must name source 'alpha'; got stderr={captured.err!r}"
        assert "bravo" in captured.err, f"Diagnostic must name source 'bravo'; got stderr={captured.err!r}"

    def test_collision_diagnostic_written_to_stderr_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Collision diagnostic is written to stderr, not stdout (AC-CHANNEL-001).

        The error message must not appear on stdout -- stdout is for progress
        output only.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_two_source_content("alpha", "bravo"))
        _populate_source_package(tmp_path, "alpha", "channel-test-pkg")
        _populate_source_package(tmp_path, "bravo", "channel-test-pkg")

        with pytest.raises(SystemExit):
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                main(["install", str(kanonenv)])

        captured = capsys.readouterr()
        assert "channel-test-pkg" in captured.err, (
            f"Collision message must appear on stderr; got stderr={captured.err!r}"
        )
        assert "channel-test-pkg" not in captured.out, (
            f"Collision message must NOT appear on stdout (AC-CHANNEL-001); got stdout={captured.out!r}"
        )

    @pytest.mark.parametrize(
        "colliding_pkg",
        [
            "build-tools",
            "kanon-shared-utils",
            "platform-core",
        ],
    )
    def test_collision_detected_for_various_package_names(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
        colliding_pkg: str,
    ) -> None:
        """Collision detection works for any package name (parametrized).

        The collision check is name-based; any duplicate name triggers exit 1
        regardless of the specific package name.
        """
        kanonenv = _write_kanonenv(tmp_path, _valid_two_source_content("alpha", "bravo"))
        _populate_source_package(tmp_path, "alpha", colliding_pkg)
        _populate_source_package(tmp_path, "bravo", colliding_pkg)

        with pytest.raises(SystemExit) as exc_info:
            with (
                patch("kanon_cli.repo.repo_init"),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
            ):
                main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, (
            f"install must exit 1 for collision on '{colliding_pkg}'; got code {exc_info.value.code}"
        )
        captured = capsys.readouterr()
        assert colliding_pkg in captured.err, (
            f"Diagnostic must name the colliding package '{colliding_pkg}'; got stderr={captured.err!r}"
        )
