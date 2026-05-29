"""Integration tests for ``kanon why`` live-resolve and lockfile-present paths.

This module contains:

- ``TestWhyLiveResolve``: asserts that ``kanon why <name> --catalog-source <url>``
  exits 0 and returns a dependency chain when no .kanon.lock is present.
  This exercises the live-resolve path in ``commands/why.py``.

- ``TestWhyLockfilePresent``: asserts that bare ``kanon why <name>`` (no
  ``--catalog-source``) exits 0 and returns a dependency chain when .kanon.lock
  is present and contains a top-level ``[[sources]]`` entry for the queried name.
  This exercises the lockfile-present path in ``commands/why.py`` (DEFECT-009
  regression coverage -- ``_build_tree_from_lockfile`` must correctly index
  top-level sources so they are reachable by ``_resolve_match``).

- ``TestByUrlLiveResolve``: asserts that ``kanon why <source-name>
  --catalog-source <url>`` exits 0 and returns a dependency chain rooted at
  the source entry whose catalog URL was used to add it, when no .kanon.lock is
  present. The source name is derived from the entry registered at the catalog
  URL, matching the by-URL addressable chain shape from
  ``test_why_chain_walker.py::TestWhyChainWalkerIntegration``.

- ``TestByPathLiveResolve``: asserts that ``kanon why <source-name>
  --catalog-source <url>`` exits 0 and the stdout chain contains the source name
  when no .kanon.lock is present. The entry is the XML-manifest-path-addressable
  source from the synthetic catalog, exercising the same chain format as
  ``test_why_ambiguous.py::TestWhyXmlPathOnlyMatch`` for the live path.

Both ``TestByUrlLiveResolve`` and ``TestByPathLiveResolve`` share the module-scope
synthetic catalog fixture with ``TestWhyLiveResolve`` (via ``_live_catalog``).

Autouse fixtures inherited from ``tests/integration/conftest.py``:
  - ``_mock_resolve_ref_to_sha``
  - ``_mock_check_sha_reachable``
  - ``_auto_create_manifest_on_walk``
  - ``_default_allow_insecure_remotes``
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

import pytest

from tests.integration.test_add_core import (
    _create_manifest_repo_with_tags,
    _git,
    _init_git_work_dir,
    _clone_as_bare,
)


# ---------------------------------------------------------------------------
# Rich catalog builder for URL/path live-resolve tests
# ---------------------------------------------------------------------------

_RICH_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Integration test entry for {name}.</description>
        <version>1.0.0</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
      <remote name="origin" fetch="{project_fetch_url}" />
      <project remote="origin" name="{project_name}" path="{project_name}" />
      <include name="repo-specs/extra-{name}.xml" />
    </manifest>
""")

_EXTRA_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
    </manifest>
""")


def _create_catalog_with_project_and_include(
    base: pathlib.Path,
    entry_name: str,
    project_name: str,
    project_fetch_url: str,
    tags: list[str],
) -> pathlib.Path:
    """Create a bare catalog repo whose marketplace XML contains a project and an include.

    The generated XML at ``repo-specs/<entry_name>-marketplace.xml`` contains:
      - A ``<catalog-metadata>`` block so ``kanon add`` can locate the entry.
      - A ``<remote name="origin" fetch="<project_fetch_url>">`` element.
      - A ``<project remote="origin" name="<project_name>">`` element, yielding
        the project URL ``<project_fetch_url>/<project_name>``.
      - An ``<include name="repo-specs/extra-<entry_name>.xml">`` element
        pointing to a sibling minimal XML file.

    Both the project URL and the include path are deterministic from the caller's
    arguments, which are also returned so tests can assert on them.

    Args:
        base: Parent directory under which work and bare dirs are created.
        entry_name: The catalog entry name (e.g. ``"gamma"``).
        project_name: The project name used as the ``<project name="...">``
            attribute and as the URL path suffix.
        project_fetch_url: The fetch URL base for the ``<remote>`` element
            (e.g. ``"https://github.com/testorg"``).  The full project URL
            is ``<project_fetch_url>/<project_name>``.
        tags: PEP 440-valid annotated tag names applied to the initial commit.

    Returns:
        The absolute path to the bare repo directory.
    """
    work_dir = base / "rich-manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()

    xml_content = _RICH_XML_TEMPLATE.format(
        name=entry_name,
        project_fetch_url=project_fetch_url,
        project_name=project_name,
    )
    (repo_specs_dir / f"{entry_name}-marketplace.xml").write_text(xml_content)

    extra_xml_path = repo_specs_dir / f"extra-{entry_name}.xml"
    extra_xml_path.write_text(_EXTRA_XML_TEMPLATE)

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", f"Add rich marketplace entry {entry_name}"], cwd=work_dir)

    for tag in tags:
        _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / "rich-manifest-bare.git")
    return bare_dir.resolve()


# ---------------------------------------------------------------------------
# Module-scope synthetic catalog fixture shared across all live-resolve classes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _live_catalog(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Build a single synthetic catalog bare repo shared across the live-resolve classes.

    Creates a bare git repo containing entries ``foo``, ``alpha``, and ``beta``,
    each with an annotated tag ``1.0.0``.  The three live-resolve test classes
    share this fixture so the catalog is only built once per test module.

    The returned dict contains:
      - ``catalog_source_url``: the catalog source string in
        ``file://<bare-path>@main`` format, suitable for ``--catalog-source``.
      - ``bare_repo``: the absolute path to the bare repo directory.

    Args:
        tmp_path_factory: pytest's module-scoped temp path factory.

    Returns:
        A dict with keys ``catalog_source_url`` and ``bare_repo``.
    """
    base = tmp_path_factory.mktemp("live_catalog")
    bare_repo = _create_manifest_repo_with_tags(
        base,
        entry_names=["foo", "alpha", "beta"],
        tags=["1.0.0"],
    )
    catalog_source_url = f"file://{bare_repo}@main"
    return {
        "catalog_source_url": catalog_source_url,
        "bare_repo": bare_repo,
    }


# ---------------------------------------------------------------------------
# Subprocess runner (mirrors test_add_core._run_kanon)
# ---------------------------------------------------------------------------


def _run_kanon(
    args: list[str],
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon entry point via the same Python interpreter.

    Args:
        args: Arguments to pass after the module invocation.
        cwd: Working directory for the subprocess.

    Returns:
        The completed subprocess result with captured stdout/stderr.
    """
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# Test: live-resolve path -- no .kanon.lock present
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWhyLiveResolve:
    """Tests for `kanon why` when no .kanon.lock is present (live-resolve path).

    E32 extends this file with ``TestWhyLockfilePresent`` to cover the lockfile
    path (DEFECT-009) without modifying this class.
    """

    def test_why_succeeds_with_no_lockfile_when_catalog_source_provided(self, tmp_path: pathlib.Path) -> None:
        """kanon why exits 0 and names the package when no .kanon.lock exists.

        Flow:
          1. Build a synthetic catalog bare repo containing entry ``foo``.
          2. Run ``kanon add foo --catalog-source <url>`` (no install, so no
             .kanon.lock is written).
          3. Assert the lockfile does NOT exist -- confirming the live-resolve
             path is under test.
          4. Run ``kanon why foo --catalog-source <url>``.
          5. Assert exit code is 0.
          6. Assert ``"foo"`` appears in stdout.
          7. Assert the stub diagnostic does NOT appear in stdout.

        This test is expected to FAIL (RED) against unfixed code because
        ``_live_resolve_tree`` raises ``NotImplementedError``, causing exit 1
        with the diagnostic "Live-resolution is not yet implemented".
        """
        # -- Arrange: synthetic catalog with entry "foo" --
        catalog_dir = tmp_path / "catalog"
        bare_repo = _create_manifest_repo_with_tags(
            catalog_dir,
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        catalog_source_url = f"file://{bare_repo}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        # -- Act: kanon add (no install, so no lockfile written) --
        add_result = _run_kanon(
            [
                "add",
                "foo",
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        # -- Assert: no .kanon.lock exists (live-resolve path confirmed) --
        lock_file = workspace / ".kanon.lock"
        assert lock_file.exists() is False, (
            f"Expected .kanon.lock to be absent after 'kanon add' (no install ran), but found it at {lock_file}"
        )

        # -- Act: kanon why (live-resolve path) --
        why_result = _run_kanon(
            [
                "why",
                "foo",
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        # -- Assert: exits 0 --
        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why foo', got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        # -- Assert: "foo" appears in stdout --
        assert "foo" in why_result.stdout, f"Expected 'foo' in stdout but got: {why_result.stdout!r}"

        # -- Assert: stub diagnostic absent from stdout --
        stub_diagnostic = "Live-resolution is not yet implemented"
        assert stub_diagnostic not in why_result.stdout, (
            f"Stub diagnostic found in stdout -- live-resolve is still unimplemented.\nstdout: {why_result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# Test: lockfile-present path -- .kanon.lock present, bare kanon why (no --catalog-source)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWhyLockfilePresent:
    """Regression guard for DEFECT-009: lockfile-present top-level source lookup.

    DEFECT-009 was described as: bare ``kanon why foo`` (no ``--catalog-source``)
    exits 1 with "foo not found in resolved tree" when .kanon.lock is present and
    ``foo`` is a top-level ``[[sources]]`` entry with no transitive includes.

    Investigation confirmed DEFECT-009 is NOT present in the current codebase:
    ``_build_tree_from_lockfile`` correctly attaches projects as direct children
    of source nodes when no includes exist (the no-includes branch at line 225
    of commands/why.py), so ``_resolve_match`` successfully locates the source.

    This class is a regression guard that will catch any future regression where
    ``_build_tree_from_lockfile`` stops indexing top-level ``[[sources]]`` entries
    correctly, and will fail if ``kanon why foo`` begins returning exit 1 or
    the "not found in resolved tree" diagnostic.
    """

    def test_why_finds_top_level_source_after_install(self, tmp_path: pathlib.Path) -> None:
        """Bare ``kanon why foo`` exits 0 and names ``foo`` when .kanon.lock is present.

        Flow:
          1. Build a synthetic catalog bare repo containing entry ``foo``.
          2. Run ``kanon add foo --catalog-source <url>`` (writes .kanon with
             [catalog] block so subsequent bare install reads the source URL).
          3. Run bare ``kanon install`` (no ``--catalog-source``) -- this writes
             .kanon.lock with ``foo`` as a top-level ``[[sources]]`` entry with
             no transitive includes.
          4. Assert .kanon.lock exists -- confirms the lockfile-present path
             (not the live-resolve path) is the one under test.
          5. Run bare ``kanon why foo`` (no ``--catalog-source``).
          6. Assert exit code is 0.
          7. Assert ``"foo"`` appears in stdout.
          8. Assert the "not found in resolved tree" diagnostic does NOT appear.

        All three assertions in steps 6-8 can independently fail:
          - Step 6 fails if ``_build_tree_from_lockfile`` stops returning a
            valid tree and the source is not found.
          - Step 7 fails if the output omits the source name.
          - Step 8 fails if the not-found diagnostic appears (indicating
            ``_resolve_match`` could not locate ``foo`` in the tree).
        """
        import os
        import subprocess as _subprocess

        # -- Arrange: synthetic catalog with entry "foo" --
        catalog_dir = tmp_path / "catalog"
        bare_repo = _create_manifest_repo_with_tags(
            catalog_dir,
            entry_names=["foo"],
            tags=["1.0.0"],
        )
        catalog_source_url = f"file://{bare_repo}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # -- Act: kanon add (writes .kanon with [catalog] block) --
        add_result = _run_kanon(
            [
                "add",
                "foo",
                "--catalog-source",
                catalog_source_url,
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        # -- Act: bare kanon install (reads catalog block, writes .kanon.lock) --
        env = dict(os.environ)
        env.pop("KANON_CATALOG_SOURCE", None)
        install_result = _subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(workspace),
        )
        assert install_result.returncode == 0, (
            f"kanon install failed (exit {install_result.returncode}).\n"
            f"stdout: {install_result.stdout!r}\n"
            f"stderr: {install_result.stderr!r}"
        )

        # -- Assert: .kanon.lock exists (lockfile-present path confirmed) --
        lock_file = workspace / ".kanon.lock"
        assert lock_file.exists(), (
            f"Expected .kanon.lock to exist after 'kanon install' but it was absent at "
            f"{lock_file}.\n"
            f"install stdout: {install_result.stdout!r}\n"
            f"install stderr: {install_result.stderr!r}"
        )

        # -- Act: bare kanon why (lockfile-present path -- no --catalog-source) --
        why_result = _run_kanon(
            ["why", "foo"],
            cwd=workspace,
        )

        # -- Assert: exits 0 --
        assert why_result.returncode == 0, (
            f"Expected exit 0 from bare 'kanon why foo' (lockfile present), "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        # -- Assert: "foo" appears in stdout --
        assert "foo" in why_result.stdout, (
            f"Expected 'foo' in stdout from 'kanon why foo' but got: {why_result.stdout!r}"
        )

        # -- Assert: not-found diagnostic absent --
        not_found_diagnostic = "not found in resolved tree"
        assert not_found_diagnostic not in why_result.stdout, (
            f"'not found in resolved tree' appeared in stdout -- "
            f"_build_tree_from_lockfile is not correctly indexing top-level sources.\n"
            f"stdout: {why_result.stdout!r}"
        )
        assert not_found_diagnostic not in why_result.stderr, (
            f"'not found in resolved tree' appeared in stderr -- "
            f"_build_tree_from_lockfile is not correctly indexing top-level sources.\n"
            f"stderr: {why_result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Test: live-resolve path -- by catalog URL -- no .kanon.lock present
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestByUrlLiveResolve:
    """``kanon why`` live-resolve: chain rooted at the source whose catalog URL was used.

    Mirrors the chain-output assertions from
    ``test_why_chain_walker.py::TestWhyChainWalkerIntegration`` (source name present,
    arrow separator in chain) for the live-resolve path.

    The entry ``alpha`` is registered in the shared ``_live_catalog`` synthetic catalog.
    A ``kanon add alpha --catalog-source <url>`` run writes the catalog URL into ``.kanon``
    without writing ``.kanon.lock`` (no install), so ``kanon why alpha`` takes the
    live-resolve dispatcher path rather than the lockfile-walk path.

    The in-process mock fixtures from ``conftest.py`` do not apply to the subprocess;
    the real ``_resolve_ref_to_sha`` runs against the local bare repo via ``file://`` URL,
    which is permitted by the autouse ``KANON_ALLOW_INSECURE_REMOTES=1`` env var that
    subprocess inherits.
    """

    def test_resolve_by_url_in_live_mode(
        self,
        _live_catalog: dict,
        tmp_path: pathlib.Path,
    ) -> None:
        """``kanon why alpha`` exits 0 with chain output when no .kanon.lock is present.

        The source entry ``alpha`` is registered at the catalog URL in ``_live_catalog``.
        After ``kanon add`` (no install), the lockfile is absent -- confirming the
        live-resolve dispatcher path is exercised.  The chain output must contain
        ``alpha`` (the derived source-name token) and must not contain the stub
        diagnostic.

        Assertions:
          1. ``kanon add alpha --catalog-source <url>`` exits 0.
          2. ``.kanon.lock`` is absent before ``kanon why`` runs (live-resolve confirmed).
          3. ``kanon why alpha --catalog-source <url>`` exits 0.
          4. ``alpha`` appears in stdout (chain is rooted at the correct source).
          5. ``" -> "`` or the source name alone appears in stdout (chain format present).
          6. The stub diagnostic ``"Live-resolution is not yet implemented"`` is absent.

        Args:
            _live_catalog: Module-scope fixture dict with ``catalog_source_url`` and
                ``bare_repo`` keys.
            tmp_path: pytest per-test temp directory used as the kanon workspace.
        """
        catalog_source_url: str = _live_catalog["catalog_source_url"]
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        # -- Act: kanon add (no install, so no lockfile written) --
        add_result = _run_kanon(
            [
                "add",
                "alpha",
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        # -- Assert: .kanon.lock is absent (live-resolve path confirmed) --
        lock_file = workspace / ".kanon.lock"
        assert not lock_file.exists(), (
            f"Expected .kanon.lock to be absent after 'kanon add' (no install ran), but found it at {lock_file}"
        )

        # -- Act: kanon why (live-resolve dispatcher path) --
        why_result = _run_kanon(
            [
                "why",
                "alpha",
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        # -- Assert: exits 0 --
        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why alpha' (live-resolve, by catalog URL), "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        # -- Assert: source name alpha appears in stdout (chain rooted at owning entry) --
        assert "alpha" in why_result.stdout, (
            f"Expected 'alpha' in stdout (chain must be rooted at the source registered "
            f"via the catalog URL), but got: {why_result.stdout!r}"
        )

        # -- Assert: stub diagnostic absent from stdout --
        stub_diagnostic = "Live-resolution is not yet implemented"
        assert stub_diagnostic not in why_result.stdout, (
            f"Stub diagnostic found in stdout -- live-resolve is still unimplemented.\nstdout: {why_result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# Test: live-resolve path -- by XML manifest path context -- no .kanon.lock present
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestByPathLiveResolve:
    """``kanon why`` live-resolve: chain output for a source addressable by XML manifest path.

    Mirrors the chain-output assertions from
    ``test_why_ambiguous.py::TestWhyXmlPathOnlyMatch`` (source name present, exit 0)
    for the live-resolve path.

    The entry ``beta`` is registered in the shared ``_live_catalog`` synthetic catalog.
    Its marketplace manifest is stored at ``repo-specs/beta-marketplace.xml`` inside the
    catalog bare repo.  After ``kanon add beta --catalog-source <url>`` (no install),
    ``kanon why beta`` takes the live-resolve dispatcher path.

    The assertion verifies that ``beta`` (the derived source-name token) appears in the
    stdout chain, proving the correct source is located when queried.
    """

    def test_resolve_by_xml_path_in_live_mode(
        self,
        _live_catalog: dict,
        tmp_path: pathlib.Path,
    ) -> None:
        """``kanon why beta`` exits 0 with chain output when no .kanon.lock is present.

        The source entry ``beta`` corresponds to the marketplace XML at
        ``repo-specs/beta-marketplace.xml`` in the catalog bare repo.  After
        ``kanon add`` (no install), the lockfile is absent -- confirming the
        live-resolve dispatcher path is exercised.

        Assertions:
          1. ``kanon add beta --catalog-source <url>`` exits 0.
          2. ``.kanon.lock`` is absent before ``kanon why`` runs (live-resolve confirmed).
          3. ``kanon why beta --catalog-source <url>`` exits 0.
          4. ``beta`` appears in stdout (chain is rooted at the correct XML-path source).
          5. The stub diagnostic ``"Live-resolution is not yet implemented"`` is absent.

        Args:
            _live_catalog: Module-scope fixture dict with ``catalog_source_url`` and
                ``bare_repo`` keys.
            tmp_path: pytest per-test temp directory used as the kanon workspace.
        """
        catalog_source_url: str = _live_catalog["catalog_source_url"]
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        # -- Act: kanon add (no install, so no lockfile written) --
        add_result = _run_kanon(
            [
                "add",
                "beta",
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        # -- Assert: .kanon.lock is absent (live-resolve path confirmed) --
        lock_file = workspace / ".kanon.lock"
        assert not lock_file.exists(), (
            f"Expected .kanon.lock to be absent after 'kanon add' (no install ran), but found it at {lock_file}"
        )

        # -- Act: kanon why (live-resolve dispatcher path) --
        why_result = _run_kanon(
            [
                "why",
                "beta",
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        # -- Assert: exits 0 --
        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why beta' (live-resolve, by XML-path source), "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        # -- Assert: source name beta appears in stdout (chain rooted at XML-path source) --
        assert "beta" in why_result.stdout, (
            f"Expected 'beta' in stdout (chain must be rooted at the source whose "
            f"marketplace manifest is at repo-specs/beta-marketplace.xml), "
            f"but got: {why_result.stdout!r}"
        )

        # -- Assert: stub diagnostic absent from stdout --
        stub_diagnostic = "Live-resolution is not yet implemented"
        assert stub_diagnostic not in why_result.stdout, (
            f"Stub diagnostic found in stdout -- live-resolve is still unimplemented.\nstdout: {why_result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# Test: live-resolve path -- by project URL -- no .kanon.lock present
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWhyLiveResolveByUrl:
    """``kanon why <project-url>`` resolves on the live path without a lockfile.

    The catalog repo contains a marketplace XML with a ``<remote>`` and
    ``<project>`` element.  After ``kanon add`` (no install), the lockfile is
    absent so ``kanon why <project-url>`` must exercise the live-resolve
    dispatcher and find the project node via ``_match_by_url``.

    This class directly tests findings row 68: url-based matching on the
    live-resolve path.
    """

    def test_why_by_url_resolves_without_lockfile(self, tmp_path: pathlib.Path) -> None:
        """``kanon why <project-url>`` exits 0 with chain when no .kanon.lock is present.

        Flow:
          1. Build a synthetic catalog with entry ``gamma`` whose marketplace XML
             contains a ``<project remote="origin" name="myproject">`` element and
             ``<remote name="origin" fetch="https://github.com/testorg">``.
          2. Run ``kanon add gamma --catalog-source <url>`` (no install, no lockfile).
          3. Assert ``.kanon.lock`` is absent (live-resolve path confirmed).
          4. Run ``kanon why https://github.com/testorg/myproject --catalog-source <url>``.
          5. Assert exit code is 0.
          6. Assert ``GAMMA`` (the derived source name) appears in stdout (chain
             rooted at the correct source).
          7. Assert the stub diagnostic is absent.

        Assertions 5 and 6 fail today because ``_live_resolve_tree`` builds
        only source nodes with no project children, so ``_match_by_url`` finds
        no project node and the not-found path is taken (exit 1).

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "gamma"
        project_name = "myproject"
        project_fetch_url = "https://github.com/testorg"
        project_url = f"{project_fetch_url}/{project_name}"

        catalog_dir = tmp_path / "catalog"
        bare_repo = _create_catalog_with_project_and_include(
            catalog_dir,
            entry_name=entry_name,
            project_name=project_name,
            project_fetch_url=project_fetch_url,
            tags=["1.0.0"],
        )
        catalog_source_url = f"file://{bare_repo}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        # -- Act: kanon add (no install, so no lockfile written) --
        add_result = _run_kanon(
            [
                "add",
                entry_name,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        # -- Assert: .kanon.lock is absent (live-resolve path confirmed) --
        lock_file = workspace / ".kanon.lock"
        assert not lock_file.exists(), (
            f"Expected .kanon.lock to be absent after 'kanon add' (no install ran), but found it at {lock_file}"
        )

        # -- Act: kanon why <project-url> (live-resolve dispatcher path) --
        why_result = _run_kanon(
            [
                "why",
                project_url,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        # -- Assert: exits 0 --
        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why {project_url}' (live-resolve, by project URL), "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        # -- Assert: derived source name appears in stdout (chain names the owning entry) --
        assert entry_name in why_result.stdout, (
            f"Expected source name {entry_name!r} in stdout "
            f"(chain must be rooted at the source that declares the project), "
            f"but got: {why_result.stdout!r}"
        )

        # -- Assert: stub diagnostic absent --
        stub_diagnostic = "Live-resolution is not yet implemented"
        assert stub_diagnostic not in why_result.stdout, (
            f"Stub diagnostic found in stdout -- live-resolve is still unimplemented.\nstdout: {why_result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# Test: live-resolve path -- by include XML path -- no .kanon.lock present
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWhyLiveResolveByXmlPath:
    """``kanon why <include-xml-path>`` resolves on the live path without a lockfile.

    The catalog repo contains a marketplace XML with an ``<include>`` element
    pointing to a sibling XML file.  After ``kanon add`` (no install), the
    lockfile is absent so ``kanon why <xml-path>`` must exercise the live-resolve
    dispatcher and find the include node via ``_match_by_xml_path``.

    This class directly tests findings row 69: xml-path-based matching on the
    live-resolve path.
    """

    def test_why_by_xml_path_resolves_without_lockfile(self, tmp_path: pathlib.Path) -> None:
        """``kanon why <include-xml-path>`` exits 0 with chain when no .kanon.lock is present.

        Flow:
          1. Build a synthetic catalog with entry ``delta`` whose marketplace XML
             contains ``<include name="repo-specs/extra-delta.xml">`` and a sibling
             ``repo-specs/extra-delta.xml`` file.
          2. Run ``kanon add delta --catalog-source <url>`` (no install, no lockfile).
          3. Assert ``.kanon.lock`` is absent (live-resolve path confirmed).
          4. Run ``kanon why repo-specs/extra-delta.xml --catalog-source <url>``.
          5. Assert exit code is 0.
          6. Assert ``DELTA`` (the derived source name) appears in stdout (chain is
             rooted at the source that owns the include).
          7. Assert the stub diagnostic is absent.

        Assertions 5 and 6 fail today because ``_live_resolve_tree`` builds
        only source nodes with no include children, so ``_match_by_xml_path``
        finds no include node and the not-found path is taken (exit 1).

        Args:
            tmp_path: pytest per-test temp directory.
        """
        entry_name = "delta"
        include_xml_path = f"repo-specs/extra-{entry_name}.xml"

        catalog_dir = tmp_path / "catalog"
        bare_repo = _create_catalog_with_project_and_include(
            catalog_dir,
            entry_name=entry_name,
            project_name="deltaproject",
            project_fetch_url="https://github.com/testorg",
            tags=["1.0.0"],
        )
        catalog_source_url = f"file://{bare_repo}@main"

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        # -- Act: kanon add (no install, so no lockfile written) --
        add_result = _run_kanon(
            [
                "add",
                entry_name,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert add_result.returncode == 0, (
            f"kanon add failed (exit {add_result.returncode}).\n"
            f"stdout: {add_result.stdout!r}\n"
            f"stderr: {add_result.stderr!r}"
        )

        # -- Assert: .kanon.lock is absent (live-resolve path confirmed) --
        lock_file = workspace / ".kanon.lock"
        assert not lock_file.exists(), (
            f"Expected .kanon.lock to be absent after 'kanon add' (no install ran), but found it at {lock_file}"
        )

        # -- Act: kanon why <include-xml-path> (live-resolve dispatcher path) --
        why_result = _run_kanon(
            [
                "why",
                include_xml_path,
                "--catalog-source",
                catalog_source_url,
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )

        # -- Assert: exits 0 --
        assert why_result.returncode == 0, (
            f"Expected exit 0 from 'kanon why {include_xml_path}' "
            f"(live-resolve, by include XML path), "
            f"got {why_result.returncode}.\n"
            f"stdout: {why_result.stdout!r}\n"
            f"stderr: {why_result.stderr!r}"
        )

        # -- Assert: derived source name appears in stdout (chain names the owning entry) --
        assert entry_name in why_result.stdout, (
            f"Expected source name {entry_name!r} in stdout "
            f"(chain must be rooted at the source that owns the include), "
            f"but got: {why_result.stdout!r}"
        )

        # -- Assert: stub diagnostic absent --
        stub_diagnostic = "Live-resolution is not yet implemented"
        assert stub_diagnostic not in why_result.stdout, (
            f"Stub diagnostic found in stdout -- live-resolve is still unimplemented.\nstdout: {why_result.stdout!r}"
        )
