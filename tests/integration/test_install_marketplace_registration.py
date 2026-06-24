"""Integration tests for install marketplace registration (DEFECT-004).

Asserts that ``kanon install`` with ``KANON_MARKETPLACE_INSTALL=true`` results
in ``claude plugin marketplace add`` being invoked for each marketplace
directory discovered under ``CLAUDE_MARKETPLACES_DIR``.

The tests use the claude-CLI mock pattern from spec section 3.3:
- Patch ``kanon_cli.core.marketplace.shutil.which`` to return ``/usr/bin/claude``
  so ``locate_claude_binary()`` succeeds without a real claude install.
- Patch ``kanon_cli.core.marketplace.subprocess.run`` to record argv on every
  invocation without actually executing the binary.

The 2-source fixture is built using ``_create_manifest_repo_with_tags`` from
``tests.integration.test_add_core`` (spec section 3.1). Each source repo
conceptually contains a ``<linkfile>`` element whose ``dest`` writes a fake
``.claude-plugin/marketplace.json`` into the tmp marketplace directory. The
``fake_repo_init`` side effect writes manifest XML that declares this linkfile.
The ``repo_sync`` mock does NOT process linkfiles (it is a no-op), which is
the DEFECT-004 scenario: ``install_marketplace_plugins`` finds an empty
directory and skips the registration path entirely.

These tests are RED against unfixed code: the mocked ``subprocess.run`` is
never invoked with the expected ``claude plugin marketplace add`` arguments
because ``prepare_marketplace_dir`` empties the marketplace directory and the
no-op ``repo_sync`` does not repopulate it via linkfiles.

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
Section 4 E35 Failing test + Verification + Edge cases.
"""

from __future__ import annotations

import pathlib
import subprocess
import textwrap
from unittest.mock import patch

import pytest

from kanon_cli.core.install import install
from tests.integration.test_add_core import _create_manifest_repo_with_tags


# ---------------------------------------------------------------------------
# XML template with linkfile element (for fake_repo_init side effects)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_kanonenv_two_sources(
    directory: pathlib.Path,
    marketplace_dir: pathlib.Path,
    source_alpha_url: str,
    source_bravo_url: str,
    *,
    marketplace_install: bool,
) -> pathlib.Path:
    """Write a .kanon file with two sources and a configurable marketplace flag.

    Args:
        directory: Directory in which to create the .kanon file (created if absent).
        marketplace_dir: Absolute path to CLAUDE_MARKETPLACES_DIR.
        source_alpha_url: Git URL for the first source (source-alpha).
        source_bravo_url: Git URL for the second source (source-bravo).
        marketplace_install: When True, both sources opt into the marketplace via
            their per-dependency KANON_SOURCE_<alias>_MARKETPLACE flags (the 3.0.0
            replacement for the removed global KANON_MARKETPLACE_INSTALL header).

    Returns:
        Absolute path to the written .kanon file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    kanonenv = directory / ".kanon"
    alpha_marketplace = "KANON_SOURCE_source_alpha_MARKETPLACE=true\n" if marketplace_install else ""
    bravo_marketplace = "KANON_SOURCE_source_bravo_MARKETPLACE=true\n" if marketplace_install else ""
    kanonenv.write_text(
        f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}\n"
        f"KANON_SOURCE_source_alpha_URL={source_alpha_url}\n"
        f"KANON_SOURCE_source_alpha_REF=main\n"
        f"KANON_SOURCE_source_alpha_PATH=repo-specs/source-alpha-marketplace.xml\n"
        f"KANON_SOURCE_source_alpha_NAME=source_alpha\n"
        f"KANON_SOURCE_source_alpha_GITBASE=https://example.com\n"
        f"{alpha_marketplace}"
        f"KANON_SOURCE_source_bravo_URL={source_bravo_url}\n"
        f"KANON_SOURCE_source_bravo_REF=main\n"
        f"KANON_SOURCE_source_bravo_PATH=repo-specs/source-bravo-marketplace.xml\n"
        f"KANON_SOURCE_source_bravo_NAME=source_bravo\n"
        f"KANON_SOURCE_source_bravo_GITBASE=https://example.com\n"
        f"{bravo_marketplace}"
    )
    return kanonenv.resolve()


def _make_repo_init_with_linkfiles(marketplace_dir: pathlib.Path) -> object:
    """Return a fake_repo_init side-effect that writes manifests with linkfile elements.

    Each call to ``repo_init`` writes a manifest XML at the path that
    ``install()`` expects after ``repo init`` + ``repo sync``. The manifest
    contains a ``<linkfile>`` element whose ``dest`` points to
    ``marketplace_dir/<source-name>/.claude-plugin/marketplace.json``.

    Also writes a minimal ``.claude-plugin/marketplace.json`` into the
    project's simulated checkout directory (``repo_dir/<source-name>/``).
    This file is the ``src`` side of the ``<linkfile>`` element and is
    required so that ``_process_manifest_linkfiles`` in ``install.py`` can
    copy it to the ``dest`` path after ``repo_sync`` completes.

    The manifest path is derived from the ``manifest_path`` argument that
    ``install()`` passes to ``repo_init``, so it matches the
    ``KANON_SOURCE_<name>_PATH`` value in the .kanon file.

    The source name is derived from the ``manifest_path`` stem using the
    convention ``<source-name>-marketplace.xml``.

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

        # Derive source name from manifest filename: "<name>-marketplace.xml" -> "<name>"
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

        # Write the linkfile src file into the project checkout directory.
        # ``_process_manifest_linkfiles`` (install.py) copies this file to
        # the dest path after ``repo_sync`` completes.  In production, the
        # repo tool checks out the project and the file is present; here we
        # write it explicitly so the test does not depend on a real repo sync.
        src_file = pathlib.Path(repo_dir) / source_name / ".claude-plugin" / "marketplace.json"
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_text(_MARKETPLACE_JSON_TEMPLATE.format(name=source_name))

    return fake_repo_init


def _extract_marketplace_add_argvs(call_args_list: list) -> list[tuple[str, ...]]:
    """Extract argv tuples for ``claude plugin marketplace add`` from a mock call list.

    Filters and returns only calls whose argv matches the
    ``<bin> plugin marketplace add <path>`` shape.

    Args:
        call_args_list: The ``call_args_list`` from a mock object.

    Returns:
        List of argv tuples, one per matching call, in call order.
    """
    result = []
    for recorded_call in call_args_list:
        if not recorded_call.args:
            continue
        argv = tuple(str(a) for a in recorded_call.args[0])
        if len(argv) >= 4 and argv[1:4] == ("plugin", "marketplace", "add"):
            result.append(argv)
    return result


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallMarketplaceRegistration:
    """Verify that kanon install invokes claude plugin marketplace add for each source."""

    def test_install_calls_claude_marketplace_add_for_each_kanon_source(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() must invoke subprocess.run with claude marketplace add for each entry.

        Builds a 2-source fixture using ``_create_manifest_repo_with_tags``
        (spec section 3.1). Each source bare repo is referenced as a
        KANON_SOURCE in .kanon. The ``fake_repo_init`` side effect writes a
        manifest XML containing a ``<linkfile>`` element whose ``dest`` points
        at ``tmp_path/marketplace/<source>/.claude-plugin/marketplace.json``.

        The ``repo_sync`` mock is a no-op: it does NOT process the linkfile
        elements. This is the DEFECT-004 scenario -- ``prepare_marketplace_dir``
        clears the marketplace directory and the no-op ``repo_sync`` does not
        repopulate it. ``install_marketplace_plugins`` therefore finds an empty
        directory and the mocked ``subprocess.run`` is never called with
        ``plugin marketplace add``.

        This test is RED against unfixed code.
        """
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)

        marketplace_dir = tmp_path / "marketplace"
        marketplace_dir.mkdir()

        # Build 2 synthetic source repos using the canonical fixture helper
        # (spec section 3.1). Each bare repo is referenced as a KANON_SOURCE.
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

        kanonenv = _write_kanonenv_two_sources(
            tmp_path / "workspace",
            marketplace_dir,
            source_alpha_url=f"file://{bare_alpha}",
            source_bravo_url=f"file://{bare_bravo}",
            marketplace_install=True,
        )

        # Expected marketplace entry directories -- these are where linkfile
        # processing would write .claude-plugin/marketplace.json if repo_sync
        # were real. They are looked up from tmp_path (not hard-coded).
        entry_alpha_path = marketplace_dir / "source-alpha"
        entry_bravo_path = marketplace_dir / "source-bravo"

        # locate_claude_binary() calls shutil.which("claude"); mock returns a
        # fixed path so the install does not short-circuit on missing binary.
        claude_bin = "/usr/bin/claude"

        expected_alpha = (claude_bin, "plugin", "marketplace", "add", str(entry_alpha_path))
        expected_bravo = (claude_bin, "plugin", "marketplace", "add", str(entry_bravo_path))

        mock_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        with (
            patch(
                "kanon_cli.repo.repo_init",
                side_effect=_make_repo_init_with_linkfiles(marketplace_dir),
            ),
            patch("kanon_cli.repo.repo_envsubst"),
            # repo_sync is a no-op mock: it does NOT process the <linkfile>
            # elements that fake_repo_init wrote into the manifest XML. This
            # is the DEFECT-004 scenario: in production, repo_sync should
            # deposit linkfile targets into CLAUDE_MARKETPLACES_DIR, but the
            # install flow never triggers that path correctly.
            patch("kanon_cli.repo.repo_sync"),
            patch(
                "kanon_cli.core.marketplace.shutil.which",
                return_value=claude_bin,
            ),
            patch(
                "kanon_cli.core.marketplace.subprocess.run",
                return_value=mock_completed,
            ) as mock_run,
        ):
            install(
                kanonenv,
                lock_file_path=kanonenv.parent / ".kanon.lock",
            )

        recorded_add_argvs = _extract_marketplace_add_argvs(mock_run.call_args_list)

        assert expected_alpha in recorded_add_argvs, (
            f"Expected subprocess.run to be called with argv {expected_alpha!r} "
            f"for marketplace entry 'source-alpha', but recorded "
            f"'claude plugin marketplace add' calls were: {recorded_add_argvs}. "
            f"DEFECT-004: prepare_marketplace_dir clears CLAUDE_MARKETPLACES_DIR "
            f"and the no-op repo_sync does not repopulate it via linkfiles; "
            f"install_marketplace_plugins finds an empty directory and skips "
            f"the registration path entirely."
        )
        assert expected_bravo in recorded_add_argvs, (
            f"Expected subprocess.run to be called with argv {expected_bravo!r} "
            f"for marketplace entry 'source-bravo', but recorded "
            f"'claude plugin marketplace add' calls were: {recorded_add_argvs}. "
            f"DEFECT-004: prepare_marketplace_dir clears CLAUDE_MARKETPLACES_DIR "
            f"and the no-op repo_sync does not repopulate it via linkfiles; "
            f"install_marketplace_plugins finds an empty directory and skips "
            f"the registration path entirely."
        )

    def test_install_does_not_call_claude_when_marketplace_install_disabled(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install() must not invoke claude plugin marketplace add when flag is false.

        With ``KANON_MARKETPLACE_INSTALL=false`` in .kanon, the marketplace
        registration path must be skipped entirely -- the mock subprocess.run
        must not be called with any ``claude plugin marketplace add`` arguments.

        Uses the same 2-source fixture built from ``_create_manifest_repo_with_tags``
        (spec section 3.1). With the flag disabled, ``prepare_marketplace_dir``
        is never called and ``install_marketplace_plugins`` is never reached.

        This negative-case assertion locks the skip-behaviour against regression
        from the upcoming T2 fix. Spec section 4 E35 Edge cases.
        """
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)

        marketplace_dir = tmp_path / "marketplace"
        marketplace_dir.mkdir()

        # Build 2 synthetic source repos using the canonical fixture helper
        # (spec section 3.1). With marketplace disabled, these sources are
        # synced but the marketplace registration step is skipped entirely.
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

        kanonenv = _write_kanonenv_two_sources(
            tmp_path / "workspace",
            marketplace_dir,
            source_alpha_url=f"file://{bare_alpha}",
            source_bravo_url=f"file://{bare_bravo}",
            marketplace_install=False,
        )

        mock_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        with (
            patch(
                "kanon_cli.repo.repo_init",
                side_effect=_make_repo_init_with_linkfiles(marketplace_dir),
            ),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch(
                "kanon_cli.core.marketplace.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "kanon_cli.core.marketplace.subprocess.run",
                return_value=mock_completed,
            ) as mock_run,
        ):
            install(
                kanonenv,
                lock_file_path=kanonenv.parent / ".kanon.lock",
            )

        add_calls = _extract_marketplace_add_argvs(mock_run.call_args_list)

        assert len(add_calls) == 0, (
            f"subprocess.run must NOT be called with 'claude plugin marketplace add' "
            f"when KANON_MARKETPLACE_INSTALL=false, but got {len(add_calls)} such "
            f"call(s): {add_calls}"
        )
