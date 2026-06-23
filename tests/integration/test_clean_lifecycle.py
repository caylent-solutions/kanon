"""Integration tests for kanon clean lifecycle via CLI entry point (9 tests).

Covers the clean command lifecycle from the CLI boundary:
  - AC-TEST-001: kanon clean removes .packages/ and .kanon-data/
  - AC-TEST-002: kanon clean with KANON_MARKETPLACE_INSTALL=true also removes marketplace directory
  - AC-TEST-003: kanon clean is idempotent (clean of already-clean state succeeds)
  - AC-FUNC-001: clean removes every artifact install created, nothing else
  - AC-CHANNEL-001: stdout vs stderr discipline verified (no cross-channel leakage)
  - AC-FUNC-004 / AC-FUNC-005: install records claude marketplace add, clean records reverse remove
"""

import json as _json
import pathlib
import subprocess
import textwrap
from unittest.mock import patch

import pytest

from kanon_cli.cli import main
from kanon_cli.core.clean import clean
from kanon_cli.core.install import install
from tests.integration.test_add_core import _create_manifest_repo_with_tags


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_kanonenv(directory: pathlib.Path, extra_lines: str = "") -> pathlib.Path:
    """Write a minimal valid .kanon file in directory and return its path.

    Args:
        directory: Directory in which to create the .kanon file.
        extra_lines: Additional KEY=VALUE lines to append.

    Returns:
        Absolute path to the written .kanon file.
    """
    base = (
        "KANON_SOURCE_primary_URL=https://example.com/primary.git\n"
        "KANON_SOURCE_primary_REVISION=main\n"
        "KANON_SOURCE_primary_PATH=meta.xml\n"
    )
    kanonenv = directory / ".kanon"
    kanonenv.write_text(base + extra_lines)
    return kanonenv.resolve()


def _create_install_artifacts(base_dir: pathlib.Path, packages: list[str]) -> None:
    """Create .packages/ and .kanon-data/ artifacts as install would.

    Args:
        base_dir: Project root directory.
        packages: List of package names to create under .packages/.
    """
    packages_dir = base_dir / ".packages"
    for pkg in packages:
        pkg_dir = packages_dir / pkg
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / f"{pkg}.sh").write_text(f"#!/bin/sh\necho {pkg}\n")

    kanon_data = base_dir / ".kanon-data" / "sources" / "primary"
    kanon_data.mkdir(parents=True, exist_ok=True)
    (kanon_data / "metadata.txt").write_text("source=primary\n")


# ---------------------------------------------------------------------------
# AC-TEST-001: kanon clean removes .packages/ and .kanon-data/
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanRemovesArtifacts:
    """AC-TEST-001: kanon clean removes .packages/ and .kanon-data/ via CLI."""

    def test_clean_removes_packages_and_kanon_data(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: invoking 'kanon clean' removes .packages/ and .kanon-data/."""
        kanonenv = _write_kanonenv(tmp_path)
        _create_install_artifacts(tmp_path, ["tool-a", "tool-b"])

        assert (tmp_path / ".packages").exists(), "precondition: .packages/ must exist before clean"
        assert (tmp_path / ".kanon-data").exists(), "precondition: .kanon-data/ must exist before clean"

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "kanon clean must remove .packages/"
        assert not (tmp_path / ".kanon-data").exists(), "kanon clean must remove .kanon-data/"

    def test_clean_removes_nested_packages_content(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-001: clean removes all nested content inside .packages/."""
        kanonenv = _write_kanonenv(tmp_path)
        nested = tmp_path / ".packages" / "tool-a" / "subdir"
        nested.mkdir(parents=True)
        (nested / "file.txt").write_text("content")
        (tmp_path / ".kanon-data").mkdir()

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "kanon clean must remove .packages/ including nested content"


# ---------------------------------------------------------------------------
# AC-TEST-002: kanon clean with KANON_MARKETPLACE_INSTALL=true removes marketplace dir
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanWithMarketplace:
    """AC-TEST-002: kanon clean with marketplace enabled removes marketplace directory."""

    def test_clean_marketplace_true_removes_marketplace_directory(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-002: KANON_MARKETPLACE_INSTALL=true causes clean to remove marketplace dir."""
        marketplace_dir = tmp_path / "marketplaces"
        marketplace_dir.mkdir()
        (marketplace_dir / "some-marketplace-plugin.txt").write_text("plugin data")

        kanonenv = _write_kanonenv(
            tmp_path,
            (f"KANON_MARKETPLACE_INSTALL=true\nCLAUDE_MARKETPLACES_DIR={marketplace_dir}\n"),
        )
        _create_install_artifacts(tmp_path, ["tool-a"])

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins"):
            main(["clean", str(kanonenv)])

        assert not marketplace_dir.exists(), (
            "kanon clean with KANON_MARKETPLACE_INSTALL=true must remove CLAUDE_MARKETPLACES_DIR"
        )
        assert not (tmp_path / ".packages").exists(), "kanon clean with marketplace=true must also remove .packages/"
        assert not (tmp_path / ".kanon-data").exists(), (
            "kanon clean with marketplace=true must also remove .kanon-data/"
        )

    def test_clean_marketplace_false_does_not_touch_unrelated_dirs(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-FUNC-001: clean with marketplace disabled does not remove unrelated directories."""
        other_dir = tmp_path / "other-data"
        other_dir.mkdir()
        (other_dir / "keep.txt").write_text("user data")

        kanonenv = _write_kanonenv(tmp_path)
        _create_install_artifacts(tmp_path, ["tool-a"])

        main(["clean", str(kanonenv)])

        assert other_dir.exists(), "clean must not remove directories it does not own"
        assert (other_dir / "keep.txt").exists(), "clean must not remove user files"


# ---------------------------------------------------------------------------
# AC-TEST-003: kanon clean is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanIdempotent:
    """AC-TEST-003: kanon clean is idempotent when run on an already-clean directory."""

    def test_clean_on_already_clean_dir_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: 'kanon clean' on a directory without artifacts exits zero."""
        kanonenv = _write_kanonenv(tmp_path)

        assert not (tmp_path / ".packages").exists(), "precondition: .packages/ must not exist"
        assert not (tmp_path / ".kanon-data").exists(), "precondition: .kanon-data/ must not exist"

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "idempotent clean: .packages/ must remain absent"
        assert not (tmp_path / ".kanon-data").exists(), "idempotent clean: .kanon-data/ must remain absent"

    def test_clean_twice_in_succession_both_succeed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-003: running 'kanon clean' twice on the same directory succeeds both times."""
        kanonenv = _write_kanonenv(tmp_path)
        _create_install_artifacts(tmp_path, ["tool-a"])

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "first clean must remove .packages/"
        assert not (tmp_path / ".kanon-data").exists(), "first clean must remove .kanon-data/"

        main(["clean", str(kanonenv)])

        assert not (tmp_path / ".packages").exists(), "second clean must not fail when .packages/ absent"
        assert not (tmp_path / ".kanon-data").exists(), "second clean must not fail when .kanon-data/ absent"


# ---------------------------------------------------------------------------
# AC-FUNC-001 and AC-CHANNEL-001: preservation of non-managed files and channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanPreservesNonManagedFiles:
    """AC-FUNC-001 and AC-CHANNEL-001: clean removes only managed artifacts."""

    def test_clean_preserves_kanonenv_and_user_files(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-FUNC-001: clean does not remove .kanon, .gitignore, or user source files."""
        kanonenv = _write_kanonenv(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".packages/\n.kanon-data/\n")
        user_file = tmp_path / "src" / "app.py"
        user_file.parent.mkdir(parents=True)
        user_file.write_text("# user code\n")

        _create_install_artifacts(tmp_path, ["tool-a"])

        main(["clean", str(kanonenv)])

        assert kanonenv.exists(), "AC-FUNC-001: clean must not remove the .kanon file"
        assert gitignore.exists(), "AC-FUNC-001: clean must not remove .gitignore"
        assert user_file.exists(), "AC-FUNC-001: clean must not remove user source files"

    def test_clean_success_output_goes_to_stdout_not_stderr(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """AC-CHANNEL-001: progress messages from clean go to stdout; stderr must be empty on success."""
        kanonenv = _write_kanonenv(tmp_path)
        _create_install_artifacts(tmp_path, ["tool-a"])

        main(["clean", str(kanonenv)])

        captured = capsys.readouterr()
        assert captured.err == "", (
            f"AC-CHANNEL-001: no output expected on stderr during clean success; stderr={captured.err!r}"
        )
        assert "clean" in captured.out.lower() or ".packages" in captured.out, (
            f"AC-CHANNEL-001: progress output expected on stdout during clean; stdout={captured.out!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-004 / AC-FUNC-005: marketplace-true lifecycle -- install registers,
# clean unregisters
# ---------------------------------------------------------------------------

_MANIFEST_WITH_LINKFILE_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <project name="{name}" path="{name}" remote="origin" revision="main">
        <linkfile src=".claude-plugin/marketplace.json"
                  dest="{marketplace_dest}/.claude-plugin/marketplace.json" />
      </project>
    </manifest>
""")

_MARKETPLACE_JSON_TEMPLATE = '{{"name": "{name}", "plugins": []}}'


def _make_repo_init_with_linkfiles(marketplace_dir: pathlib.Path) -> object:
    """Return a fake_repo_init side-effect that writes manifests with linkfile elements.

    Each call to ``repo_init`` writes a manifest XML at the path that
    ``install()`` expects after ``repo init + repo sync``. The manifest
    contains a ``<linkfile>`` element whose ``dest`` points into
    ``marketplace_dir/<source-name>/``. Also writes the corresponding
    ``.claude-plugin/marketplace.json`` src file so that
    ``_process_manifest_linkfiles`` in ``install.py`` can copy it to the
    dest path (the E35 fix path).

    Args:
        marketplace_dir: Root marketplace directory (CLAUDE_MARKETPLACES_DIR).

    Returns:
        A callable suitable for use as ``side_effect`` on a mock.
    """

    def fake_repo_init(
        repo_dir: str,
        url: str,
        revision: str,
        manifest_path: str,
        repo_rev: str = "",
    ) -> None:
        manifest_file = pathlib.Path(repo_dir) / ".repo" / "manifests" / manifest_path
        manifest_file.parent.mkdir(parents=True, exist_ok=True)

        stem = pathlib.Path(manifest_path).name
        if stem.endswith("-marketplace.xml"):
            source_name = stem[: -len("-marketplace.xml")]
        else:
            source_name = stem.replace(".xml", "")

        marketplace_dest = marketplace_dir / source_name
        manifest_file.write_text(
            _MANIFEST_WITH_LINKFILE_TEMPLATE.format(
                name=source_name,
                marketplace_dest=str(marketplace_dest),
            )
        )

        src_file = pathlib.Path(repo_dir) / source_name / ".claude-plugin" / "marketplace.json"
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_text(_MARKETPLACE_JSON_TEMPLATE.format(name=source_name))

    return fake_repo_init


def _filter_argvs_by_subcommand(
    recorded_argvs: list[list], subcommand_tokens: tuple[str, ...]
) -> list[tuple[str, ...]]:
    """Filter recorded argv lists matching the given subcommand prefix.

    Filters calls whose argv tokens after the binary name start with
    ``subcommand_tokens``.

    Args:
        recorded_argvs: List of raw argv lists as passed to subprocess.run.
        subcommand_tokens: Tuple of expected argv tokens after the binary name,
            e.g. ``("plugin", "marketplace", "add")`` or
            ``("plugin", "marketplace", "remove")``.

    Returns:
        List of full argv tuples, one per matching call, in call order.
    """
    result = []
    token_count = len(subcommand_tokens)
    for argv_list in recorded_argvs:
        argv = tuple(str(a) for a in argv_list)
        if len(argv) >= token_count + 1 and argv[1 : token_count + 1] == subcommand_tokens:
            result.append(argv)
    return result


@pytest.mark.integration
class TestCleanMarketplaceTrue:
    """AC-FUNC-004 / AC-FUNC-005: install registers, clean deregisters marketplace plugins."""

    def test_clean_removes_registered_marketplace(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() records marketplace add calls; clean() records the reverse remove calls.

        Builds a 2-source synthetic catalog using ``_create_manifest_repo_with_tags``
        (spec section 3.1). The ``fake_repo_init`` side effect writes manifest XML
        with ``<linkfile>`` elements and creates the corresponding
        ``.claude-plugin/marketplace.json`` src files so that
        ``_process_manifest_linkfiles`` in ``install.py`` deposits them under
        ``CLAUDE_MARKETPLACES_DIR`` (the E35 fix path).

        Both install and clean use the same subprocess.run mock so all invocations
        are recorded in a single list. After install, the recorded
        ``claude plugin marketplace add`` calls are extracted and validated.
        After clean, the recorded ``claude plugin marketplace remove`` calls are
        extracted and validated: one remove per prior add, with the marketplace
        name matching the name field from each marketplace.json, with no extra
        calls in either direction.

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)

        marketplace_dir = tmp_path / "marketplace"
        marketplace_dir.mkdir()

        bare_alpha = _create_manifest_repo_with_tags(
            tmp_path / "repo-alpha",
            entry_names=["source-alpha"],
            tags=["1.0.0"],
        )
        bare_bravo = _create_manifest_repo_with_tags(
            tmp_path / "repo-bravo",
            entry_names=["source-bravo"],
            tags=["1.0.0"],
        )

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        kanonenv = workspace_dir / ".kanon"
        kanonenv.write_text(
            f"KANON_MARKETPLACE_INSTALL=true\n"
            f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}\n"
            f"KANON_SOURCE_source_alpha_URL=file://{bare_alpha}\n"
            f"KANON_SOURCE_source_alpha_REVISION=main\n"
            f"KANON_SOURCE_source_alpha_PATH=repo-specs/source-alpha-marketplace.xml\n"
            f"KANON_SOURCE_source_bravo_URL=file://{bare_bravo}\n"
            f"KANON_SOURCE_source_bravo_REVISION=main\n"
            f"KANON_SOURCE_source_bravo_PATH=repo-specs/source-bravo-marketplace.xml\n"
        )
        kanonenv = kanonenv.resolve()

        claude_bin = "/usr/bin/claude"
        mock_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        install_call_args: list = []
        clean_call_args: list = []

        def recording_run_install(args, **kwargs):
            install_call_args.append(args)
            return mock_completed

        def recording_run_clean(args, **kwargs):
            clean_call_args.append(args)
            return mock_completed

        with (
            patch(
                "kanon_cli.repo.repo_init",
                side_effect=_make_repo_init_with_linkfiles(marketplace_dir),
            ),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch(
                "kanon_cli.core.marketplace.shutil.which",
                return_value=claude_bin,
            ),
            patch(
                "kanon_cli.core.marketplace.subprocess.run",
                side_effect=recording_run_install,
            ),
        ):
            install(
                kanonenv,
                lock_file_path=kanonenv.parent / ".kanon.lock",
            )

        add_argvs = _filter_argvs_by_subcommand(
            install_call_args,
            ("plugin", "marketplace", "add"),
        )

        assert len(add_argvs) >= 1, (
            f"AC-FUNC-004: install() must invoke 'claude plugin marketplace add' at least once "
            f"when KANON_MARKETPLACE_INSTALL=true, but no such calls were recorded. "
            f"All install subprocess.run args: {install_call_args!r}"
        )

        add_names_in_order: list[str] = []
        for argv in add_argvs:
            # argv shape: (bin, "plugin", "marketplace", "add", <path>)
            # the name comes from marketplace.json inside <path>
            entry_path = pathlib.Path(argv[4])
            json_path = entry_path / ".claude-plugin" / "marketplace.json"
            assert json_path.exists(), (
                f"AC-FUNC-004: marketplace.json must exist at {json_path} "
                f"for entry path {entry_path!r} from recorded add call {argv!r}"
            )
            marketplace_data = _json.loads(json_path.read_text())
            add_names_in_order.append(marketplace_data["name"])

        assert len(add_names_in_order) >= 1, (
            f"AC-FUNC-004: expected at least one marketplace name from add calls, but add_argvs={add_argvs!r}"
        )

        with (
            patch(
                "kanon_cli.core.marketplace.shutil.which",
                return_value=claude_bin,
            ),
            patch(
                "kanon_cli.core.marketplace.subprocess.run",
                side_effect=recording_run_clean,
            ),
        ):
            clean(kanonenv)

        remove_argvs = _filter_argvs_by_subcommand(
            clean_call_args,
            ("plugin", "marketplace", "remove"),
        )

        remove_names: list[str] = [argv[4] for argv in remove_argvs]

        assert len(remove_names) == len(add_names_in_order), (
            f"AC-FUNC-005: clean() must invoke 'claude plugin marketplace remove' exactly "
            f"once per prior 'add' call. Expected {len(add_names_in_order)} remove call(s) "
            f"(names={add_names_in_order!r}) but got {len(remove_names)} (names={remove_names!r}). "
            f"All clean subprocess.run args: {clean_call_args!r}"
        )

        for expected_name in add_names_in_order:
            assert expected_name in remove_names, (
                f"AC-FUNC-005: marketplace name {expected_name!r} was registered via "
                f"'claude plugin marketplace add' during install but no matching "
                f"'claude plugin marketplace remove {expected_name}' was recorded during clean. "
                f"Recorded remove names: {remove_names!r}"
            )
