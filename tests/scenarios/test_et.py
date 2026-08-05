"""ET (Entry Type validation) scenarios from `docs/integration-testing.md` §12b.

Each test runs the real `kanon validate marketplace` against an on-disk catalog
and asserts the process exit code, so the whole path is exercised: manifest
discovery, the `<include>` chain walk, the linkfile rules, and the stdout/stderr
split.

Two rules are under test.

**Containment** applies to every entry regardless of type. A `<linkfile dest>`
names a symlink created relative to the top of the consumer tree, so it must
land inside that tree: an absolute path, a `..` component, and an empty dest are
rejected. A dest rooted at `${CLAUDE_MARKETPLACES_DIR}/`, at any other `${VAR}`,
or at a plain relative path is contained and accepted.

**The marketplace-dest rule** applies only to an entry whose
`<catalog-metadata><type>` is `claude-marketplace` AND which declares at least
one `<linkfile>`: one of those dests must sit under
`${CLAUDE_MARKETPLACES_DIR}/`. An entry declaring no `<linkfile>` at all is
exempt -- that is the direct-checkout shape that
`register_direct_checkout_marketplaces` registers from a checked-out
`.claude-plugin/marketplace.json` (see `test_marketplace_direct_checkout.py`).
Failing it there would reject an entry `kanon install` handles correctly.

Scenarios automated:
- ET-01: marketplace entry ships a plugin alongside repo-level standards
- ET-02: non-marketplace entry links only into the project root
- ET-03: direct-checkout marketplace entry declares no linkfiles
- ET-04: marketplace entry whose linkfiles all miss the marketplace directory
- ET-05: a dest that escapes the consumer workspace is rejected
- ET-06: a linkfile inside an `<include>` is validated like an inline one
- ET-07: a defect in a shared `<include>` is reported once
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from tests.scenarios.conftest import run_kanon


MARKETPLACE_DEST = "${CLAUDE_MARKETPLACES_DIR}/standards"
RULES_DEST = "${PROJECT_ROOT}/.claude/rules"
HOOKS_DEST = "${PROJECT_ROOT}/.githooks"
ROOT_DOTFILE_DEST = "${PROJECT_ROOT}/.gitleaks.toml"
RELATIVE_DEST = "config/lint.toml"

TYPE_MARKETPLACE = "claude-marketplace"
TYPE_LIBRARY = "library"

_REVISION = "refs/tags/ex/standards/1.0.0"


def _entry_xml(
    entry_type: str | None,
    dests: list[str],
    *,
    includes: list[str] | None = None,
    project_name: str = "standards",
) -> str:
    """Build a catalog entry manifest.

    Args:
        entry_type: Value for ``<catalog-metadata><type>``; omitted when None.
        dests: One ``<linkfile dest>`` per entry. An empty list declares no
            ``<linkfile>`` at all, which is the direct-checkout shape.
        includes: Optional ``<include name>`` targets, repo-root relative.
        project_name: ``<project name>``; also drives its checkout path. Entries
            sharing a catalog need distinct values, since duplicate project
            paths are themselves a validation error.

    Returns:
        The manifest XML as a string.
    """
    include_els = "".join(f'  <include name="{name}" />\n' for name in (includes or []))
    link_els = "".join(f'      <linkfile src="src" dest="{dest}" />\n' for dest in dests)
    type_el = f"    <type>{entry_type}</type>\n" if entry_type else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com" />\n'
        f"{include_els}"
        f'  <project name="{project_name}" path=".packages/{project_name}" remote="origin"'
        f' revision="{_REVISION}">\n'
        f"{link_els}"
        "  </project>\n"
        "  <catalog-metadata>\n"
        f"    <name>{project_name}</name>\n"
        "    <display-name>Engineering Standards</display-name>\n"
        "    <description>Plugin plus repo-level standards.</description>\n"
        "    <version>1.0.0</version>\n"
        f"{type_el}"
        "    <owner-name>Example Org</owner-name>\n"
        "    <owner-email>eng@example.com</owner-email>\n"
        "    <keywords>standards</keywords>\n"
        "  </catalog-metadata>\n"
        "</manifest>\n"
    )


def _shared_include_xml(dest: str, *, project_name: str = "shared") -> str:
    """Build an includable manifest carrying one project with one linkfile.

    Args:
        dest: The ``<linkfile dest>`` for the project.
        project_name: The ``<project name>``; also drives its checkout path.

    Returns:
        The manifest XML as a string.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <project name="{project_name}" path=".packages/{project_name}" remote="origin"'
        f' revision="refs/tags/ex/{project_name}/1.0.0">\n'
        f'    <linkfile src="src" dest="{dest}" />\n'
        "  </project>\n"
        "</manifest>\n"
    )


def _catalog(tmp_path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    """Write a catalog repo root containing *files* and return it.

    Args:
        tmp_path: Test-scoped temporary directory.
        files: Mapping of repo-root-relative path to file content.

    Returns:
        The catalog repo root.
    """
    repo_root = tmp_path / "catalog"
    for rel, content in files.items():
        target = repo_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return repo_root


def _validate(repo_root: pathlib.Path) -> subprocess.CompletedProcess:
    """Run `kanon validate marketplace` against *repo_root*.

    Args:
        repo_root: Catalog repo root to validate.

    Returns:
        The CompletedProcess from the CLI invocation.
    """
    return run_kanon("validate", "marketplace", "--repo-root", str(repo_root))


def _assert_no_validation_errors(result: subprocess.CompletedProcess, context: str) -> None:
    """Assert the CLI reported no validation errors.

    Emptiness of stderr is the wrong signal here: the fixture manifests point at
    an unreachable ``https://example.com`` remote, so the revision-existence
    check legitimately warns that it validated format only. That warning is not
    a validation error and must not fail these scenarios.

    Args:
        result: CompletedProcess from `kanon validate marketplace`.
        context: Scenario identifier used in the assertion message.

    Raises:
        AssertionError: If the CLI exited non-zero or reported any error.
    """
    assert result.returncode == 0, f"{context}: expected exit 0.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    assert "validation error" not in result.stderr, (
        f"{context}: expected no validation errors.\nstderr: {result.stderr!r}"
    )


@pytest.mark.scenario
class TestEntryTypeMatrix:
    """ET-01..ET-04: entry type crossed with every linkfile shape."""

    @pytest.mark.parametrize(
        ("entry_type", "dests", "expected_exit", "why"),
        [
            (TYPE_MARKETPLACE, [], 0, "ET-03 direct checkout: registered from marketplace.json"),
            (TYPE_MARKETPLACE, [MARKETPLACE_DEST], 0, "plugin only"),
            (TYPE_MARKETPLACE, [MARKETPLACE_DEST, RULES_DEST], 0, "ET-01 plugin plus non-plugin content"),
            (TYPE_MARKETPLACE, [RULES_DEST], 1, "ET-04 claims marketplace but registers none"),
            (TYPE_LIBRARY, [], 0, "library with no linkfiles"),
            (TYPE_LIBRARY, [MARKETPLACE_DEST], 0, "library may still link into the marketplace dir"),
            (TYPE_LIBRARY, [RULES_DEST], 0, "ET-02 issue #94: the case that used to be rejected"),
            (TYPE_LIBRARY, [MARKETPLACE_DEST, RULES_DEST], 0, "library with mixed dests"),
            (None, [], 0, "untyped, no linkfiles"),
            (None, [MARKETPLACE_DEST], 0, "untyped, marketplace dest"),
            (None, [RULES_DEST], 0, "untyped, project-root dest"),
            (None, [MARKETPLACE_DEST, RULES_DEST], 0, "untyped, mixed dests"),
        ],
        ids=[
            "ET-03-marketplace-no-linkfiles",
            "marketplace-plugin-only",
            "ET-01-marketplace-plugin-plus-rules",
            "ET-04-marketplace-only-non-marketplace-dest",
            "library-no-linkfiles",
            "library-marketplace-dest",
            "ET-02-library-project-root-dest",
            "library-mixed-dests",
            "untyped-no-linkfiles",
            "untyped-marketplace-dest",
            "untyped-project-root-dest",
            "untyped-mixed-dests",
        ],
    )
    def test_entry_type_and_linkfile_shape(
        self,
        tmp_path: pathlib.Path,
        entry_type: str | None,
        dests: list[str],
        expected_exit: int,
        why: str,
    ) -> None:
        """ET-01..ET-04: type and linkfile shape together decide the verdict.

        Exactly one of the twelve combinations fails: an entry declaring itself
        a ``claude-marketplace`` that declares linkfiles, none of which reach
        ``${CLAUDE_MARKETPLACES_DIR}/``.
        """
        repo_root = _catalog(tmp_path, {"repo-specs/standards.xml": _entry_xml(entry_type, dests)})

        result = _validate(repo_root)

        if expected_exit == 0:
            _assert_no_validation_errors(result, why)
        else:
            assert result.returncode == expected_exit, (
                f"[{why}]: expected exit {expected_exit} for type={entry_type!r} dests={dests!r}.\n"
                f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
            )
            assert "registers no marketplace" in result.stderr, (
                f"[{why}]: expected the marketplace-dest diagnostic.\nstderr: {result.stderr!r}"
            )


@pytest.mark.scenario
class TestRealWorldMixedPackage:
    """ET-01 / ET-04: the package shape issue #94 was filed to unblock."""

    def test_et_01_plugin_plus_rules_hooks_and_root_dotfile_validates(self, tmp_path: pathlib.Path) -> None:
        """ET-01: one entry shipping a plugin and every repo-level asset passes.

        A Claude plugin registered through ``${CLAUDE_MARKETPLACES_DIR}``, plus
        ``.claude/rules/``, ``.githooks/``, a root ``.gitleaks.toml``, and a
        plain workspace-relative config. Before the fix each of the four
        non-marketplace dests produced one error, so the entry could not be
        merged into a catalog whose CI gates on this validator.
        """
        repo_root = _catalog(
            tmp_path,
            {
                "repo-specs/standards.xml": _entry_xml(
                    TYPE_MARKETPLACE,
                    [MARKETPLACE_DEST, RULES_DEST, HOOKS_DEST, ROOT_DOTFILE_DEST, RELATIVE_DEST],
                )
            },
        )

        result = _validate(repo_root)

        _assert_no_validation_errors(result, "ET-01")

    def test_et_04_same_package_without_the_plugin_link_is_rejected(self, tmp_path: pathlib.Path) -> None:
        """ET-04: drop the marketplace link and the entry is caught.

        Same package, same ``<type>claude-marketplace</type>``, but nothing
        lands in ``${CLAUDE_MARKETPLACES_DIR}`` -- so it registers no
        marketplace, and the diagnostic names all three ways out.
        """
        repo_root = _catalog(
            tmp_path,
            {"repo-specs/standards.xml": _entry_xml(TYPE_MARKETPLACE, [RULES_DEST, HOOKS_DEST, ROOT_DOTFILE_DEST])},
        )

        result = _validate(repo_root)

        assert result.returncode == 1, (
            f"ET-04: expected exit 1 when no dest reaches the marketplace dir.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "registers no marketplace" in result.stderr, (
            f"ET-04: expected the marketplace-dest diagnostic.\nstderr: {result.stderr!r}"
        )
        assert "direct checkout" in result.stderr, (
            f"ET-04: the diagnostic must name the direct-checkout way out.\nstderr: {result.stderr!r}"
        )


@pytest.mark.scenario
class TestDirectCheckoutEntry:
    """ET-03: the shape `register_direct_checkout_marketplaces` handles."""

    def test_et_03_marketplace_entry_without_linkfiles_validates(self, tmp_path: pathlib.Path) -> None:
        """ET-03: a marketplace entry declaring no linkfiles passes.

        ``register_direct_checkout_marketplaces`` registers a project whose
        checkout carries ``.claude-plugin/marketplace.json`` and which has no
        ``<linkfile>`` children. The catalog XML alone cannot prove that file
        exists, so validation defers to install rather than rejecting an entry
        install handles correctly.
        """
        repo_root = _catalog(tmp_path, {"repo-specs/standards.xml": _entry_xml(TYPE_MARKETPLACE, [])})

        result = _validate(repo_root)

        _assert_no_validation_errors(result, "ET-03")


@pytest.mark.scenario
class TestContainment:
    """ET-05: a dest that escapes the consumer workspace is always rejected."""

    @pytest.mark.parametrize(
        "entry_type",
        [TYPE_MARKETPLACE, TYPE_LIBRARY, None],
        ids=["marketplace", "library", "untyped"],
    )
    @pytest.mark.parametrize(
        ("bad_dest", "fragment"),
        [
            ("/etc/kanon/rules", "absolute path"),
            ("../../outside/workspace", "'..' component"),
            ("", "dest is empty"),
        ],
        ids=["absolute", "dotdot", "empty"],
    )
    def test_et_05_escaping_dest_is_rejected(
        self,
        tmp_path: pathlib.Path,
        entry_type: str | None,
        bad_dest: str,
        fragment: str,
    ) -> None:
        """ET-05: containment holds for every entry type, with a specific reason.

        A marketplace-typed entry also carries a valid marketplace dest here, so
        the only thing that can fail is containment -- the assertion cannot be
        satisfied by the marketplace-dest rule firing instead.
        """
        dests = [MARKETPLACE_DEST, bad_dest] if entry_type == TYPE_MARKETPLACE else [bad_dest]
        repo_root = _catalog(tmp_path, {"repo-specs/standards.xml": _entry_xml(entry_type, dests)})

        result = _validate(repo_root)

        assert result.returncode == 1, (
            f"ET-05: expected exit 1 for type={entry_type!r} dest={bad_dest!r}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert fragment in result.stderr, (
            f"ET-05: expected reason {fragment!r} for dest={bad_dest!r}.\nstderr: {result.stderr!r}"
        )
        assert "error" not in result.stdout.lower(), (
            f"ET-05: errors must not leak to stdout.\nstdout: {result.stdout!r}"
        )


@pytest.mark.scenario
class TestIncludeChain:
    """ET-06 / ET-07: linkfiles reached through `<include>`."""

    def test_et_06_linkfile_inside_include_is_validated(self, tmp_path: pathlib.Path) -> None:
        """ET-06: a bad dest in an included manifest fails the entry.

        ``kanon install`` resolves the whole include chain, so a ``<project>``
        moved into a shared ``packages.xml`` must be validated exactly like an
        inline one. The entry itself is clean; only the include is not.
        """
        repo_root = _catalog(
            tmp_path,
            {
                "repo-specs/packages.xml": _shared_include_xml("../escapes"),
                "repo-specs/standards.xml": _entry_xml(
                    TYPE_MARKETPLACE, [MARKETPLACE_DEST], includes=["repo-specs/packages.xml"]
                ),
            },
        )

        result = _validate(repo_root)

        assert result.returncode == 1, (
            f"ET-06: expected exit 1 for a bad dest inside an include.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "'..' component" in result.stderr, f"ET-06: expected the containment reason.\nstderr: {result.stderr!r}"
        assert "packages.xml" in result.stderr, (
            f"ET-06: the error must name the including manifest.\nstderr: {result.stderr!r}"
        )

    def test_et_06_marketplace_dest_may_live_in_an_include(self, tmp_path: pathlib.Path) -> None:
        """ET-06: the dest satisfying the marketplace rule may come from an include.

        The entry declares only non-marketplace linkfiles inline; the include
        supplies the marketplace one. The rule is about the entry as install
        resolves it, not about one file in isolation.
        """
        repo_root = _catalog(
            tmp_path,
            {
                "repo-specs/packages.xml": _shared_include_xml(MARKETPLACE_DEST, project_name="plugin"),
                "repo-specs/standards.xml": _entry_xml(
                    TYPE_MARKETPLACE, [RULES_DEST], includes=["repo-specs/packages.xml"]
                ),
            },
        )

        result = _validate(repo_root)

        assert result.returncode == 0, (
            f"ET-06: expected exit 0 when the include supplies the marketplace dest.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_et_07_shared_include_defect_is_reported_once(self, tmp_path: pathlib.Path) -> None:
        """ET-07: one defect in a shared include yields one error, not one per entry.

        Three entries include the same broken ``packages.xml``. Without
        de-duplication the run reports the identical message three times,
        inflating the count and burying the distinct failures.
        """
        files = {"repo-specs/packages.xml": _shared_include_xml("../escapes")}
        for name in ("alpha", "bravo", "charlie"):
            files[f"repo-specs/{name}.xml"] = _entry_xml(
                TYPE_MARKETPLACE,
                [MARKETPLACE_DEST],
                includes=["repo-specs/packages.xml"],
                project_name=name,
            )
        repo_root = _catalog(tmp_path, files)

        result = _validate(repo_root)

        assert result.returncode == 1, f"ET-07: expected exit 1.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        occurrences = result.stderr.count("'..' component")
        assert occurrences == 1, (
            f"ET-07: the shared include's single defect must be reported once, "
            f"got {occurrences} occurrence(s) across 3 including entries.\nstderr: {result.stderr!r}"
        )
        assert "Found 1 validation error(s)" in result.stderr, (
            f"ET-07: the reported count must match the number of distinct defects.\nstderr: {result.stderr!r}"
        )
