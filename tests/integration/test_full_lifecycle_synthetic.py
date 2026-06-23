"""End-to-end full-lifecycle integration test against a synthetic 6-entry catalog.

Exercises the complete add + install + clean chain for 6 synthetic catalog entries
in a single test method, covering:

- E22 (install-after-add without --catalog-source from the second entry onward)
- E28 (placeholder validator rejects .kanon files with literal <...> values)
- E35 (install records claude plugin marketplace add; clean records the reverse remove)

The test builds a synthetic 6-entry catalog via ``_create_manifest_repo_with_tags``
(spec section 3.1). Each entry's manifest carries a ``<linkfile>`` directive that
writes a fake ``.claude-plugin/marketplace.json`` into the per-entry tree. The
mocked claude CLI (spec section 3.3) records every ``subprocess.run`` invocation
so the test can assert per-entry argv content rather than just call counts.

Design: each entry runs in its own isolated workspace directory. The first entry
passes ``--catalog-source`` to ``kanon add`` (the CLI flag). Entries 2-6 omit the
``--catalog-source`` flag and instead supply the catalog via the
``KANON_CATALOG_SOURCES`` environment variable. Each workspace is isolated so that
each ``kanon install`` processes exactly one catalog entry, keeping the total
add and remove counts at exactly 6.

The install steps are driven via the in-process ``install()`` API with mocked
``repo_init``/``repo_sync`` and mocked ``subprocess.run`` for the claude CLI.
``parse_kanonenv`` applies environment overrides before shell-variable expansion
so setting ``CLAUDE_MARKETPLACES_DIR`` and ``KANON_MARKETPLACE_INSTALL`` in
``os.environ`` redirects both to the test-controlled paths.

Spec reference: spec/defect-resolution-and-fixture-automation-2026-06/spec.md
section 4 E47 (Failing test + Verification + Change + closure rows),
section 3.1 (synthetic-fixture helpers), section 3.2 (autouse fixtures),
section 3.3 (claude CLI mock pattern), section 10 (testing requirements).
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
from typing import Any
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import install
from tests.integration.test_add_core import (
    _create_manifest_repo_with_tags,
    _run_kanon,
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_ENTRY_NAMES: list[str] = [
    "entry-alpha",
    "entry-bravo",
    "entry-charlie",
    "entry-delta",
    "entry-echo",
    "entry-foxtrot",
]

_TAG_VERSION = "1.0.0"

_MANIFEST_WITH_LINKFILE_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <project name="{name}" path="{name}" remote="origin" revision="main">
    <linkfile src=".claude-plugin/marketplace.json"
              dest="{marketplace_dest}/.claude-plugin/marketplace.json" />
  </project>
</manifest>
"""

_MARKETPLACE_JSON_TEMPLATE = '{{"name": "{name}", "plugins": []}}'

_MOCK_CLAUDE_BIN = "/usr/bin/claude"

_PLACEHOLDER_PATTERN = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo_init_with_linkfiles(marketplace_dir: pathlib.Path) -> object:
    """Return a fake_repo_init side-effect that writes manifests with linkfile elements.

    Each call to ``repo_init`` writes a manifest XML at the path that
    ``install()`` expects after ``repo init`` + ``repo sync``. The manifest
    contains a ``<linkfile>`` element whose ``dest`` points to
    ``marketplace_dir/<source-name>/.claude-plugin/marketplace.json``.

    Also writes the linkfile src file so that ``_process_manifest_linkfiles``
    in ``install.py`` can copy it to the dest path after ``repo_sync`` completes.

    The source name is derived from the manifest filename stem using the
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
    recorded_argvs: list[list[Any]],
    subcommand_tokens: tuple[str, ...],
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


def _assert_no_placeholder_in_kanon(kanon_path: pathlib.Path, entry_name: str) -> None:
    """Assert that the .kanon file contains no unresolved ``<...>`` placeholder.

    Args:
        kanon_path: Absolute path to the .kanon file.
        entry_name: Entry name for which the assertion is being made (included
            in the failure message for diagnostic context).

    Raises:
        AssertionError: If any line in the file contains a ``<...>`` substring.
    """
    content = kanon_path.read_text(encoding="utf-8")
    for line_no, line in enumerate(content.splitlines(), start=1):
        match = _PLACEHOLDER_PATTERN.search(line)
        assert match is None, (
            f"E28: unresolved placeholder found in .kanon after 'kanon add {entry_name}'.\n"
            f"  Line {line_no}: {line!r}\n"
            f"  Matched: {match.group()!r}\n"
            f"  Full .kanon content:\n{content}"
        )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullLifecycleSynthetic:
    """End-to-end 6-entry add + install + clean lifecycle over a synthetic catalog.

    Validates the composition of:
    - E22 (install-after-add without re-passing --catalog-source)
    - E28 (no literal <...> placeholders survive in .kanon)
    - E35 (install records marketplace add; clean records the reverse remove)
    """

    def test_six_entry_add_install_clean_lifecycle(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Full add + install + clean lifecycle for 6 synthetic entries.

        Each entry runs in its own isolated workspace directory so that each
        ``kanon install`` call processes exactly one catalog entry. This keeps
        the total add and remove counts at exactly 6 (AC-FUNC-007).

        Steps:
        1. Build a single 6-entry synthetic catalog bare repo via
           ``_create_manifest_repo_with_tags``. Each entry has a
           ``<linkfile>`` that writes a fake ``.claude-plugin/marketplace.json``
           into the per-entry marketplace sub-tree.
        2. For each of the 6 entries:
           a. Create an isolated workspace directory with its own marketplace
              sub-directory and ``CLAUDE_MARKETPLACES_DIR`` override.
           b. Run ``kanon add <entry>`` -- first entry passes
              ``--catalog-source`` via the CLI flag; entries 2-6 omit the flag
              and supply the catalog via ``KANON_CATALOG_SOURCES`` env var
              instead (AC-FUNC-004 -- no ``--catalog-source`` flag for entries
              2-6, exercising the E22 install-reads-catalog-block path).
           c. Assert no ``<...>`` placeholder survives in ``.kanon`` (E28).
           d. Run ``install()`` with the per-entry mocked repo_init that
              writes linkfile manifests + src files; assert it completes
              without exception.
           e. Assert the mock recorded a ``claude plugin marketplace add``
              invocation whose argv contains the entry's marketplace path
              (E35 -- registration path).
           f. Run ``clean()``; assert it completes without exception.
           g. Assert the mock recorded a ``claude plugin marketplace remove``
              invocation whose argv contains the entry name (E35 reverse path).
        3. Post-loop: assert total recorded add count == 6 AND total recorded
           remove count == 6 (AC-FUNC-007).

        Args:
            tmp_path: Pytest-provided temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.delenv("KANON_MARKETPLACE_INSTALL", raising=False)
        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)

        # Step 1: build the synthetic 6-entry catalog bare repo.
        bare_catalog = _create_manifest_repo_with_tags(
            tmp_path / "catalog",
            entry_names=_ENTRY_NAMES,
            tags=[_TAG_VERSION],
        )
        catalog_source = f"file://{bare_catalog}@main"

        # Shared subprocess.run mock state across all 6 per-entry cycles.
        # Two separate recording lists keep install and clean calls independent.
        install_recorded_argvs: list[list[Any]] = []
        clean_recorded_argvs: list[list[Any]] = []

        mock_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        def recording_run_install(args: list[Any], **kwargs: Any) -> subprocess.CompletedProcess:
            install_recorded_argvs.append(list(args))
            return mock_completed

        def recording_run_clean(args: list[Any], **kwargs: Any) -> subprocess.CompletedProcess:
            clean_recorded_argvs.append(list(args))
            return mock_completed

        for idx, entry_name in enumerate(_ENTRY_NAMES):
            # Each entry gets its own isolated workspace + marketplace dir so
            # each kanon install processes exactly one catalog entry and the
            # total add/remove counts match the entry count (6 each).
            workspace_dir = tmp_path / f"workspace-{idx}"
            workspace_dir.mkdir()
            entry_marketplace_dir = tmp_path / f"marketplace-{idx}"
            entry_marketplace_dir.mkdir()
            kanon_path = workspace_dir / ".kanon"

            # Set CLAUDE_MARKETPLACES_DIR + KANON_MARKETPLACE_INSTALL in
            # os.environ so the in-process install() and clean() calls see the
            # entry-specific marketplace dir. parse_kanonenv applies env
            # overrides BEFORE ${HOME} shell-variable expansion, so the
            # template value in .kanon is replaced by our test path.
            monkeypatch.setenv("CLAUDE_MARKETPLACES_DIR", str(entry_marketplace_dir))
            monkeypatch.setenv("KANON_MARKETPLACE_INSTALL", "true")

            # ------------------------------------------------------------------
            # Step 2b: kanon add
            # ------------------------------------------------------------------
            add_args = ["add", entry_name]
            if idx == 0:
                # First entry: pass --catalog-source via the CLI flag so kanon
                # add can resolve the entry from the manifest repo. kanon install
                # is hermetic and does not re-read a catalog source (E22).
                add_args += ["--catalog-source", catalog_source]

            # For entries 2-6: no --catalog-source flag (AC-FUNC-004).
            # KANON_CATALOG_SOURCES env var is set in add_env instead.
            # KANON_MARKETPLACE_INSTALL and CLAUDE_MARKETPLACES_DIR are in
            # os.environ via monkeypatch and propagate via dict(os.environ).
            add_env = dict(os.environ)
            add_env.pop("KANON_CATALOG_SOURCES", None)
            if idx > 0:
                # Entries 2-6 omit the --catalog-source flag; the catalog
                # source is supplied via env var so kanon add can find the
                # manifest repo. The install step is hermetic (no catalog
                # source) and installs the sources kanon add wrote into .kanon.
                add_env["KANON_CATALOG_SOURCES"] = catalog_source

            add_result = _run_kanon(add_args, cwd=workspace_dir, extra_env=add_env)
            assert add_result.returncode == 0, (
                f"E22: 'kanon add {entry_name}' failed (expected 0, "
                f"got {add_result.returncode}).\n"
                f"stdout: {add_result.stdout!r}\nstderr: {add_result.stderr!r}"
            )

            # ------------------------------------------------------------------
            # Step 2c: assert no <...> placeholder survives in .kanon (E28)
            # ------------------------------------------------------------------
            assert kanon_path.exists(), f"E28: .kanon was not created at {kanon_path} after 'kanon add {entry_name}'."
            _assert_no_placeholder_in_kanon(kanon_path, entry_name)

            # ------------------------------------------------------------------
            # Step 2d: kanon install (with mocked repo + claude)
            # ------------------------------------------------------------------
            entry_marketplace_path = str(entry_marketplace_dir / entry_name)

            with (
                patch(
                    "kanon_cli.repo.repo_init",
                    side_effect=_make_repo_init_with_linkfiles(entry_marketplace_dir),
                ),
                patch("kanon_cli.repo.repo_envsubst"),
                patch("kanon_cli.repo.repo_sync"),
                patch(
                    "kanon_cli.core.marketplace.shutil.which",
                    return_value=_MOCK_CLAUDE_BIN,
                ),
                patch(
                    "kanon_cli.core.marketplace.subprocess.run",
                    side_effect=recording_run_install,
                ),
            ):
                # kanon install is hermetic: it installs the sources declared in
                # .kanon (written by kanon add) and pinned in .kanon.lock without
                # resolving a catalog source.  Passing a catalog source here would
                # raise HermeticInstallCatalogSourceError.
                install(
                    kanon_path,
                    lock_file_path=workspace_dir / ".kanon.lock",
                    catalog_source=None,
                )

            # ------------------------------------------------------------------
            # Step 2e: assert install recorded claude plugin marketplace add
            # with this entry's path (E35 -- registration path)
            # ------------------------------------------------------------------
            add_argvs_so_far = _filter_argvs_by_subcommand(
                install_recorded_argvs,
                ("plugin", "marketplace", "add"),
            )

            assert add_argvs_so_far, (
                f"E35: no 'claude plugin marketplace add' was recorded during "
                f"'kanon install' for entry '{entry_name}'.\n"
                f"All install subprocess.run args so far: {install_recorded_argvs!r}"
            )
            # The most-recently-recorded add argv must contain this entry's
            # marketplace path -- not just some arbitrary path from a prior run.
            latest_add_argv = add_argvs_so_far[-1]
            assert entry_marketplace_path in latest_add_argv, (
                f"E35: the most-recently-recorded 'claude plugin marketplace add' "
                f"argv does not contain the marketplace path for entry '{entry_name}'.\n"
                f"  Expected path in argv: {entry_marketplace_path!r}\n"
                f"  Latest add argv: {latest_add_argv!r}\n"
                f"  All recorded add argvs: {add_argvs_so_far!r}"
            )

            # ------------------------------------------------------------------
            # Step 2f: kanon clean (with mocked claude)
            # ------------------------------------------------------------------
            with (
                patch(
                    "kanon_cli.core.marketplace.shutil.which",
                    return_value=_MOCK_CLAUDE_BIN,
                ),
                patch(
                    "kanon_cli.core.marketplace.subprocess.run",
                    side_effect=recording_run_clean,
                ),
            ):
                clean(kanon_path)

            # ------------------------------------------------------------------
            # Step 2g: assert clean recorded claude plugin marketplace remove
            # with this entry's name (E35 reverse path)
            # ------------------------------------------------------------------
            remove_argvs_so_far = _filter_argvs_by_subcommand(
                clean_recorded_argvs,
                ("plugin", "marketplace", "remove"),
            )

            assert remove_argvs_so_far, (
                f"E35: no 'claude plugin marketplace remove' was recorded during "
                f"'kanon clean' for entry '{entry_name}'.\n"
                f"All clean subprocess.run args so far: {clean_recorded_argvs!r}"
            )
            # The most-recently-recorded remove argv must contain this entry's
            # name -- not just some name from a prior iteration.
            latest_remove_argv = remove_argvs_so_far[-1]
            assert entry_name in latest_remove_argv, (
                f"E35: the most-recently-recorded 'claude plugin marketplace remove' "
                f"argv does not contain the entry name '{entry_name}'.\n"
                f"  Latest remove argv: {latest_remove_argv!r}\n"
                f"  All recorded remove argvs: {remove_argvs_so_far!r}"
            )

        # Step 3: post-loop total count assertions (AC-FUNC-007).
        total_add_argvs = _filter_argvs_by_subcommand(
            install_recorded_argvs,
            ("plugin", "marketplace", "add"),
        )
        total_remove_argvs = _filter_argvs_by_subcommand(
            clean_recorded_argvs,
            ("plugin", "marketplace", "remove"),
        )

        expected_entry_count = len(_ENTRY_NAMES)

        assert len(total_add_argvs) == expected_entry_count, (
            f"E35/AC-FUNC-007: expected exactly {expected_entry_count} "
            f"'claude plugin marketplace add' calls across all {expected_entry_count} "
            f"install runs, but got {len(total_add_argvs)}.\n"
            f"Recorded add argvs: {total_add_argvs!r}"
        )
        assert len(total_remove_argvs) == expected_entry_count, (
            f"E35/AC-FUNC-007: expected exactly {expected_entry_count} "
            f"'claude plugin marketplace remove' calls across all {expected_entry_count} "
            f"clean runs, but got {len(total_remove_argvs)}.\n"
            f"Recorded remove argvs: {total_remove_argvs!r}"
        )
