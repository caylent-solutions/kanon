"""Integration tests for the core 'kanon add' path.

Builds a temporary local file:// manifest-repo fixture with PEP 440-valid
git tags and invokes 'kanon add <name> --catalog-source <file>@<ref>'
via subprocess.run.

Covers:
- Happy path: create .kanon with the per-dependency source block (no existing file).
- Append path: existing .kanon gets only the source block appended.
- Spec path: 'kanon add name@==1.0.0' writes _REF=refs/tags/1.0.0.
- Default-spec path: highest PEP 440 tag is selected when no @<spec> given.
- Multiple entries: two entries are written in argument order.
- Unknown entry: exits non-zero with an error message.
- AC-CYCLE-001 evidence.

AC-TEST-002, AC-CYCLE-001
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"


_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
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
    </manifest>
""")


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _create_manifest_repo_with_tags(
    base: pathlib.Path,
    entry_names: list[str],
    tags: list[str],
) -> pathlib.Path:
    """Create a bare manifest repo with marketplace XML files and git tags.

    Each entry in entry_names gets its own <name>-marketplace.xml under
    repo-specs/. Each string in tags is applied as an annotated tag on the
    same commit so that git ls-remote --tags returns them.

    Args:
        base: Parent directory under which work and bare dirs are created.
        entry_names: Catalog entry names.
        tags: PEP 440-valid tag names to apply to the initial commit.

    Returns:
        The absolute path to the bare repo directory.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    (repo_specs_dir / ".gitkeep").write_text("")

    for name in entry_names:
        xml_path = repo_specs_dir / f"{name}-marketplace.xml"
        xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name))

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entries"], cwd=work_dir)

    for tag in tags:
        _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / "manifest-bare.git")
    return bare_dir.resolve()


def _run_kanon(
    args: list[str],
    extra_env: dict[str, str] | None = None,
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the kanon entry point via the same Python interpreter.

    Args:
        args: Arguments to pass after 'kanon'.
        extra_env: Extra environment variables merged onto os.environ.
        cwd: Working directory for the subprocess.

    Returns:
        The completed subprocess result.
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


@pytest.mark.integration
class TestAddCoreCreateWithHeader:
    """kanon add creates .kanon with the per-dependency source block when file does not exist (AC-FUNC-004)."""

    def test_exit_0_on_happy_path(self, tmp_path: pathlib.Path) -> None:
        """kanon add exits 0 when entry exists and destination file is absent."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "1.1.0", "1.2.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_file_created_without_global_header(self, tmp_path: pathlib.Path) -> None:
        """Destination .kanon file is created with no global header (no [catalog], no header GITBASE/marketplace lines)."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "1.1.0", "1.2.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert kanon_file.exists(), "Expected .kanon file to be created"
        content = kanon_file.read_text()

        assert "[catalog]" not in content
        assert "KANON_MARKETPLACE_INSTALL=" not in content

        assert "\nGITBASE=" not in content
        assert not content.startswith("GITBASE=")
        assert "KANON_SOURCE_entry_a_GITBASE=" not in content, (
            "this entry's manifest references no ${GITBASE}, so add writes no env-var line"
        )

    def test_file_contains_source_block_lines(self, tmp_path: pathlib.Path) -> None:
        """Destination .kanon file contains the KANON_SOURCE_* structural block lines."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "1.1.0", "1.2.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        content = kanon_file.read_text()
        assert "KANON_SOURCE_entry_a_URL=" in content
        assert "KANON_SOURCE_entry_a_REF=" in content
        assert "KANON_SOURCE_entry_a_PATH=" in content
        assert "KANON_SOURCE_entry_a_NAME=" in content
        assert "KANON_SOURCE_entry_a_GITBASE=" not in content, (
            "this entry's manifest references no ${GITBASE}, so no env-var line is written"
        )

    def test_revision_is_highest_pep440_tag(self, tmp_path: pathlib.Path) -> None:
        """_REF line equals refs/tags/<highest tag> (AC-FUNC-009, AC-CYCLE-001)."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "1.1.0", "1.2.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        content = kanon_file.read_text()
        assert "KANON_SOURCE_entry_a_REF=refs/tags/1.2.0" in content

    def test_stdout_summary_line_printed(self, tmp_path: pathlib.Path) -> None:
        """stdout contains the summary line naming the source name (AC-FUNC-012, AC-CYCLE-001)."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0", "1.1.0", "1.2.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert "entry_a" in result.stdout


@pytest.mark.integration
class TestAddCoreAppendToExisting:
    """kanon add appends the source block to existing .kanon, preserving prior content (AC-FUNC-005, AC-CYCLE-001)."""

    def test_existing_content_preserved(self, tmp_path: pathlib.Path) -> None:
        """Running kanon add on an existing file appends the block and preserves prior lines."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-b"],
            tags=["1.0.0", "1.1.0", "1.2.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        kanon_file.write_text("EXISTING=value\n")

        result = _run_kanon(
            [
                "add",
                "entry-b@==1.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, f"Expected exit 0.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        content = kanon_file.read_text()

        assert "EXISTING=value" in content
        assert content.count("KANON_SOURCE_entry_b_URL=") == 1

    def test_block_appended_with_explicit_spec(self, tmp_path: pathlib.Path) -> None:
        """Explicit @==1.0.0 spec results in _REF=refs/tags/1.0.0 (AC-CYCLE-001)."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-b"],
            tags=["1.0.0", "1.1.0", "1.2.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"
        kanon_file.write_text("EXISTING=value\n")

        _run_kanon(
            [
                "add",
                "entry-b@==1.0.0",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        content = kanon_file.read_text()
        assert "EXISTING=value" in content
        assert "KANON_SOURCE_entry_b_REF=refs/tags/1.0.0" in content

    def test_no_catalog_dir_consulted(self, tmp_path: pathlib.Path) -> None:
        """Command succeeds even when manifest repo has no catalog/ directory (AC-FUNC-008)."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-b"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-b",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0


@pytest.mark.integration
class TestAddCoreMultipleEntries:
    """kanon add processes multiple entries in argument order (AC-FUNC-006)."""

    def test_two_entries_in_argument_order(self, tmp_path: pathlib.Path) -> None:
        """With entry-a and entry-b, both triples appear in argument order."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a", "entry-b"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "entry-b",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0
        content = kanon_file.read_text()
        assert "KANON_SOURCE_entry_a_URL=" in content
        assert "KANON_SOURCE_entry_b_URL=" in content
        pos_a = content.index("KANON_SOURCE_entry_a_URL=")
        pos_b = content.index("KANON_SOURCE_entry_b_URL=")
        assert pos_a < pos_b, "entry-a triple must appear before entry-b triple"


@pytest.mark.integration
class TestAddCoreUnknownEntry:
    """kanon add with an unknown entry name exits non-zero (AC-FUNC-010)."""

    def test_unknown_entry_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """An entry name not in the catalog causes non-zero exit."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            [
                "add",
                "does-not-exist",
                "--catalog-source",
                f"file://{bare}@main",
            ],
            cwd=workspace,
        )
        assert result.returncode != 0

    def test_unknown_entry_names_entry_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """Error message names the unknown entry."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _run_kanon(
            [
                "add",
                "does-not-exist",
                "--catalog-source",
                f"file://{bare}@main",
            ],
            cwd=workspace,
        )
        assert "does-not-exist" in result.stderr


@pytest.mark.integration
class TestAddCoreSourceNameDerivation:
    """Source name uses derive_source_name -- hyphens become underscores (AC-FUNC-007)."""

    def test_foo_bar_entry_yields_foo_bar_underscore_keys(self, tmp_path: pathlib.Path) -> None:
        """Entry named 'Foo-Bar' yields KANON_SOURCE_foo_bar_* keys."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["Foo-Bar"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "Foo-Bar",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        content = kanon_file.read_text()
        assert "KANON_SOURCE_foo_bar_URL=" in content
        assert "KANON_SOURCE_foo_bar_REF=" in content
        assert "KANON_SOURCE_foo_bar_PATH=" in content


@pytest.mark.integration
class TestAddCoreKanonFileEnvVar:
    """--kanon-file defaults from KANON_KANON_FILE env var when not supplied as a flag."""

    def test_kanon_kanon_file_env_used_when_flag_absent(self, tmp_path: pathlib.Path) -> None:
        """KANON_KANON_FILE env var is used when --kanon-file flag is not passed."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / "custom.kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
            ],
            extra_env={"KANON_KANON_FILE": str(kanon_file)},
            cwd=workspace,
        )
        assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        assert kanon_file.exists(), "Expected custom.kanon to be created via KANON_KANON_FILE"


@pytest.mark.integration
class TestAddCustomKanonFile:
    """--kanon-file flag writes the source triple to the specified custom path (E38 row 44)."""

    def test_kanon_file_flag_writes_to_custom_path(self, tmp_path: pathlib.Path) -> None:
        """--kanon-file <path> writes the source triple to that path and does not create the default .kanon."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = tmp_path / "custom.kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert kanon_file.exists(), "Expected custom.kanon to be created at the --kanon-file path"
        content = kanon_file.read_text()
        assert "KANON_SOURCE_entry_a_URL=" in content, f"Expected source URL line in custom.kanon; got:\n{content}"
        assert "KANON_SOURCE_entry_a_REF=" in content, f"Expected source REF line in custom.kanon; got:\n{content}"
        assert "KANON_SOURCE_entry_a_PATH=" in content, f"Expected source PATH line in custom.kanon; got:\n{content}"
        default_kanon = workspace / ".kanon"
        assert not default_kanon.exists(), "Default .kanon must NOT be created when --kanon-file overrides it"


_MARKETPLACE_TYPE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Integration test marketplace entry for {name}.</description>
        <version>1.0.0</version>
        <type>claude-marketplace</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")


def _create_marketplace_manifest_repo(
    base: pathlib.Path,
    entry_name: str,
    tags: list[str],
) -> pathlib.Path:
    """Create a bare manifest repo whose single entry is a claude-marketplace type.

    Mirrors _create_manifest_repo_with_tags but stamps the entry's
    <catalog-metadata><type> as claude-marketplace so 'kanon add' auto-detects a
    marketplace dependency.

    Args:
        base: Parent directory under which work and bare dirs are created.
        entry_name: The single catalog entry name.
        tags: PEP 440-valid tag names to apply to the initial commit.

    Returns:
        The absolute path to the bare repo directory.
    """
    work_dir = base / "manifest-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    repo_specs_dir = work_dir / "repo-specs"
    repo_specs_dir.mkdir()
    (repo_specs_dir / ".gitkeep").write_text("")

    xml_path = repo_specs_dir / f"{entry_name}-marketplace.xml"
    xml_path.write_text(_MARKETPLACE_TYPE_XML_TEMPLATE.format(name=entry_name))

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add marketplace entry"], cwd=work_dir)

    for tag in tags:
        _git(["tag", "-a", tag, "-m", f"Release {tag}"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, base / "manifest-bare.git")
    return bare_dir.resolve()


@pytest.mark.integration
class TestAddMarketplaceTypeWritesFlagAndNotice:
    """A claude-marketplace catalog entry add writes _MARKETPLACE=true plus the auto-detect notice (item 15)."""

    def test_marketplace_entry_writes_marketplace_true_line(self, tmp_path: pathlib.Path) -> None:
        """Adding a claude-marketplace entry writes KANON_SOURCE_<alias>_MARKETPLACE=true."""
        bare = _create_marketplace_manifest_repo(
            tmp_path / "repo",
            entry_name="mp-entry",
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "mp-entry",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        content = kanon_file.read_text()
        assert "KANON_SOURCE_mp_entry_MARKETPLACE=true" in content

    def test_marketplace_entry_prints_auto_detect_notice(self, tmp_path: pathlib.Path) -> None:
        """stdout carries the auto-detect notice naming the type and the override flag."""
        bare = _create_marketplace_manifest_repo(
            tmp_path / "repo",
            entry_name="mp-entry",
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "mp-entry",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert "claude-marketplace" in result.stdout
        assert "--no-marketplace-install" in result.stdout

    def test_regular_entry_writes_no_marketplace_line(self, tmp_path: pathlib.Path) -> None:
        """A regular (plugin) entry from the shared fixture writes no _MARKETPLACE line."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        content = kanon_file.read_text()
        assert "_MARKETPLACE" not in content


@pytest.mark.integration
class TestAddMarketplaceInstallOnNonMarketplaceType:
    """--marketplace-install on a non-marketplace type exits non-zero with a pretty error (item 15)."""

    def test_marketplace_install_on_plugin_type_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """The plugin-typed fixture entry forced with --marketplace-install exits non-zero."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--marketplace-install",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_marketplace_install_on_plugin_type_prints_pretty_error_not_traceback(self, tmp_path: pathlib.Path) -> None:
        """stderr carries the actionable 'requires catalog entry' message, with no Python traceback."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        result = _run_kanon(
            [
                "add",
                "entry-a",
                "--marketplace-install",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert "--marketplace-install requires catalog entry" in result.stderr
        assert "entry-a" in result.stderr
        assert "Traceback (most recent call last)" not in result.stderr
        assert "MarketplaceInstallError" not in result.stderr

    def test_marketplace_install_on_plugin_type_does_not_write_kanon(self, tmp_path: pathlib.Path) -> None:
        """A rejected --marketplace-install add leaves the destination .kanon untouched (absent)."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-a"],
            tags=["1.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanon_file = workspace / ".kanon"

        _run_kanon(
            [
                "add",
                "entry-a",
                "--marketplace-install",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(kanon_file),
            ],
            cwd=workspace,
        )
        assert not kanon_file.exists(), "The .kanon must not be created when the marketplace add is rejected"


@pytest.mark.integration
class TestAddEnvKanonFilePrecedence:
    """CLI --kanon-file flag takes precedence over KANON_KANON_FILE env var (E38 row 45)."""

    def test_cli_flag_overrides_env_var(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--kanon-file <flag_path> wins over KANON_KANON_FILE=<env_path>; env path is NOT written."""
        bare = _create_manifest_repo_with_tags(
            tmp_path / "repo",
            entry_names=["entry-b"],
            tags=["2.0.0"],
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        env_path = tmp_path / "env.kanon"
        flag_path = tmp_path / "flag.kanon"

        monkeypatch.setenv("KANON_KANON_FILE", str(env_path))

        result = _run_kanon(
            [
                "add",
                "entry-b",
                "--catalog-source",
                f"file://{bare}@main",
                "--kanon-file",
                str(flag_path),
            ],
            cwd=workspace,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert flag_path.exists(), "Expected flag.kanon to be created at the --kanon-file path"
        content = flag_path.read_text()
        assert "KANON_SOURCE_entry_b_URL=" in content, f"Expected source URL line in flag.kanon; got:\n{content}"
        assert "KANON_SOURCE_entry_b_REF=" in content, f"Expected source REF line in flag.kanon; got:\n{content}"
        assert "KANON_SOURCE_entry_b_PATH=" in content, f"Expected source PATH line in flag.kanon; got:\n{content}"
        assert not env_path.exists(), "env.kanon must NOT be written when --kanon-file flag overrides KANON_KANON_FILE"
