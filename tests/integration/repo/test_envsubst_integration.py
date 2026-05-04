"""Integration tests for repo_envsubst() variable substitution.

Covers all variable substitution patterns, XML entity handling, backup file
creation, and edge cases for the repo_envsubst function.

All tests use real manifest files on disk (no in-memory mocks). Each test
creates a minimal .repo/manifests/ structure, calls repo_envsubst(), and
verifies the resulting file state.

All tests are marked @pytest.mark.integration.
"""

import os
import pathlib
import subprocess

import pytest

import kanon_cli.repo as repo_pkg
from kanon_cli.repo import RepoCommandError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Envsubst Test User"
_GIT_USER_EMAIL = "envsubst-test@example.com"
_MANIFEST_FILENAME = "default.xml"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _init_git_repo(work_dir: pathlib.Path) -> None:
    """Initialise a fresh git working directory with user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _make_bare_clone(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> None:
    """Clone work_dir into a bare repository at bare_dir."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)


def _write_manifest_repo(
    base: pathlib.Path,
    name: str,
    manifest_xml: str,
    extra_files: dict[str, str] | None = None,
) -> pathlib.Path:
    """Write manifest_xml into a fresh bare git repo.

    Args:
        base: Parent directory for the repositories.
        name: Logical name used as directory prefix.
        manifest_xml: Full XML content for the default.xml manifest.
        extra_files: Optional mapping of filename -> content for additional
            XML files to include in the manifest repo.

    Returns:
        Absolute path to the bare manifest repository.
    """
    work_dir = base / f"{name}-work"
    work_dir.mkdir(parents=True)
    _init_git_repo(work_dir)

    (work_dir / _MANIFEST_FILENAME).write_text(manifest_xml, encoding="utf-8")
    _git(["add", _MANIFEST_FILENAME], cwd=work_dir)

    if extra_files:
        for filename, content in extra_files.items():
            (work_dir / filename).write_text(content, encoding="utf-8")
            _git(["add", filename], cwd=work_dir)

    _git(["commit", "-m", "Add manifest"], cwd=work_dir)

    bare_dir = base / f"{name}-bare"
    _make_bare_clone(work_dir, bare_dir)
    return bare_dir


def _repo_init_workspace(workspace: pathlib.Path, manifest_url: str) -> None:
    """Run repo init in workspace using manifest_url.

    Args:
        workspace: Directory in which to run repo init.
        manifest_url: file:// URL of the bare manifest repository.
    """
    from kanon_cli.repo.main import run_from_args

    repo_dot_dir = str(workspace / ".repo")
    run_from_args(
        [
            "init",
            "--no-repo-verify",
            "-u",
            manifest_url,
            "-b",
            "main",
            "-m",
            _MANIFEST_FILENAME,
        ],
        repo_dir=repo_dot_dir,
    )


def _make_workspace_with_manifest(
    tmp_path: pathlib.Path,
    manifest_xml: str,
    extra_files: dict[str, str] | None = None,
) -> pathlib.Path:
    """Create a workspace directory with .repo/manifests/ populated via repo init.

    Args:
        tmp_path: Pytest tmp_path for isolation.
        manifest_xml: XML content for the manifest file.
        extra_files: Optional additional XML files to include in the manifest repo.

    Returns:
        Path to the workspace directory (contains .repo/ subdirectory).
    """
    repos_base = tmp_path / "repos"
    repos_base.mkdir()

    manifest_bare = _write_manifest_repo(
        repos_base,
        "manifest",
        manifest_xml,
        extra_files=extra_files,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _repo_init_workspace(workspace, f"file://{manifest_bare}")
    return workspace


def _read_manifest(workspace: pathlib.Path, filename: str = _MANIFEST_FILENAME) -> str:
    """Read a manifest file from the workspace's .repo/manifests/ directory.

    Args:
        workspace: Root of the repo workspace.
        filename: Name of the manifest file to read.

    Returns:
        File contents as a string.
    """
    return (workspace / ".repo" / "manifests" / filename).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dollar_brace_var_substituted_in_attribute(tmp_path: pathlib.Path) -> None:
    """${VAR} pattern in an attribute value is replaced with the variable value.

    Creates a manifest with a ${KANON_FETCH_URL} placeholder in the remote
    fetch attribute. After repo_envsubst() with the variable injected, verifies
    the placeholder is gone and the real value is present.

    AC-FUNC-003, AC-FUNC-008
    """
    expected_url = f"file://{tmp_path}/content"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${KANON_FETCH_URL}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_FETCH_URL": expected_url})

    content = _read_manifest(workspace)
    assert "${KANON_FETCH_URL}" not in content, (
        f"Expected placeholder to be resolved after envsubst, but it is still present. Manifest content: {content!r}"
    )
    assert expected_url in content, (
        f"Expected {expected_url!r} in manifest after envsubst, but it was not found. Manifest content: {content!r}"
    )


@pytest.mark.integration
def test_bare_dollar_var_substituted_in_attribute(tmp_path: pathlib.Path) -> None:
    """$VAR pattern in an attribute value is replaced with the variable value.

    Creates a manifest with a $KANON_BARE_URL placeholder (no braces) in the
    remote fetch attribute. After repo_envsubst(), verifies the placeholder is
    resolved to the injected value.

    AC-FUNC-003, AC-FUNC-008
    """
    expected_url = f"file://{tmp_path}/bare-content"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="$KANON_BARE_URL" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_BARE_URL": expected_url})

    content = _read_manifest(workspace)
    assert "$KANON_BARE_URL" not in content, (
        f"Expected bare-dollar placeholder to be resolved, but it is still present. Manifest content: {content!r}"
    )
    assert expected_url in content, (
        f"Expected {expected_url!r} in manifest after envsubst, but it was not found. Manifest content: {content!r}"
    )


@pytest.mark.integration
def test_nested_variable_in_attribute(tmp_path: pathlib.Path) -> None:
    """${VAR_${INNER}} nested pattern resolves the outer variable via os.path.expandvars.

    os.path.expandvars does not recursively resolve nested variables (the inner
    ${INNER} is not resolved inside the outer braces), but the outer variable is
    resolved if it is set. This test verifies the substitution behavior matches
    os.path.expandvars semantics for a variable whose name contains a literal
    dollar sign pattern.

    Since os.path.expandvars resolves from left to right and does not recurse,
    a variable like ${KANON_OUTER} set to a URL is fully resolved even if its
    name does not contain nested references.

    AC-FUNC-003, AC-FUNC-008
    """
    outer_url = f"file://{tmp_path}/nested-content"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${KANON_OUTER}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_OUTER": outer_url})

    content = _read_manifest(workspace)
    assert "${KANON_OUTER}" not in content, (
        f"Expected outer placeholder to be resolved after envsubst. Manifest content: {content!r}"
    )
    assert outer_url in content, f"Expected {outer_url!r} in manifest after envsubst. Manifest content: {content!r}"


@pytest.mark.integration
def test_multiple_variables_substituted_in_manifest(tmp_path: pathlib.Path) -> None:
    """Multiple different ${VAR} placeholders in one manifest are all resolved.

    Creates a manifest with two distinct placeholders in different attributes.
    After repo_envsubst() with both variables injected, verifies that both
    placeholders are replaced with their respective values.

    AC-FUNC-003, AC-FUNC-008
    """
    fetch_url = f"file://{tmp_path}/multi-content"
    revision_name = "feature-branch"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${KANON_MULTI_FETCH}" />\n'
        '  <default revision="${KANON_MULTI_REV}" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(
        str(workspace),
        {"KANON_MULTI_FETCH": fetch_url, "KANON_MULTI_REV": revision_name},
    )

    content = _read_manifest(workspace)
    assert "${KANON_MULTI_FETCH}" not in content, (
        f"Expected KANON_MULTI_FETCH placeholder to be resolved. Manifest content: {content!r}"
    )
    assert "${KANON_MULTI_REV}" not in content, (
        f"Expected KANON_MULTI_REV placeholder to be resolved. Manifest content: {content!r}"
    )
    assert fetch_url in content, f"Expected {fetch_url!r} in manifest after envsubst. Manifest content: {content!r}"
    assert revision_name in content, (
        f"Expected {revision_name!r} in manifest after envsubst. Manifest content: {content!r}"
    )


@pytest.mark.integration
def test_xml_amp_entity_preserved_during_substitution(tmp_path: pathlib.Path) -> None:
    """&amp; XML entity in an attribute is preserved after envsubst.

    The XML DOM parser decodes &amp; to & when reading, and re-encodes it back
    to &amp; when serialising. A variable substitution on a different attribute
    must not corrupt pre-existing &amp; entities in other attributes.

    AC-FUNC-004, AC-FUNC-008
    """
    fetch_url = f"file://{tmp_path}/entity-content"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${KANON_ENTITY_FETCH}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj" extra="a&amp;b" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_ENTITY_FETCH": fetch_url})

    content = _read_manifest(workspace)
    assert fetch_url in content, f"Expected {fetch_url!r} in manifest after envsubst. Manifest content: {content!r}"
    assert "&amp;" in content, (
        f"Expected &amp; entity to be preserved in the manifest after envsubst, "
        f"but it was not found. Manifest content: {content!r}"
    )


@pytest.mark.integration
def test_xml_lt_gt_entities_preserved_during_substitution(tmp_path: pathlib.Path) -> None:
    """&lt; and &gt; XML entities in text content are preserved after envsubst.

    When the XML DOM serialises text nodes containing < and >, it encodes them
    as &lt; and &gt;. Envsubst must not corrupt these entities.

    AC-FUNC-004, AC-FUNC-008
    """
    fetch_url = f"file://{tmp_path}/ltgt-content"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${KANON_LTGT_FETCH}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj">\n'
        '    <annotation name="condition" value="a&lt;b&gt;c" />\n'
        "  </project>\n"
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_LTGT_FETCH": fetch_url})

    content = _read_manifest(workspace)
    assert fetch_url in content, f"Expected {fetch_url!r} in manifest after envsubst. Manifest content: {content!r}"
    assert "&lt;" in content and "&gt;" in content, (
        f"Expected both &lt; and &gt; XML entities to be preserved in the manifest after envsubst, "
        f"but at least one was missing. Manifest content: {content!r}"
    )
    assert "${KANON_LTGT_FETCH}" not in content, (
        f"Expected placeholder to be resolved after envsubst. Manifest content: {content!r}"
    )


@pytest.mark.integration
def test_backup_file_created_alongside_original(tmp_path: pathlib.Path) -> None:
    """EnvSubst creates a .bak file next to the processed manifest file.

    After repo_envsubst() processes a manifest with a placeholder, a file
    named default.xml.bak must exist in .repo/manifests/ alongside default.xml.

    AC-FUNC-005, AC-FUNC-008
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${KANON_BACKUP_FETCH}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_BACKUP_FETCH": "file:///tmp/backup-content"})

    bak_path = workspace / ".repo" / "manifests" / (_MANIFEST_FILENAME + ".bak")
    assert bak_path.is_file(), (
        f"Expected backup file at {bak_path} after envsubst, "
        f"but it was not found. "
        f"Manifests dir contents: {sorted(str(p) for p in (workspace / '.repo' / 'manifests').iterdir())!r}"
    )


@pytest.mark.integration
def test_backup_file_contains_original_content(tmp_path: pathlib.Path) -> None:
    """The .bak file created by envsubst contains the original pre-substitution XML.

    After repo_envsubst(), the .bak file must contain the original placeholder
    text, and the processed manifest must contain the substituted value.

    AC-FUNC-005, AC-FUNC-008
    """
    original_placeholder = "${KANON_ORIG_FETCH}"
    substituted_url = "file:///tmp/original-content"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{original_placeholder}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_ORIG_FETCH": substituted_url})

    bak_path = workspace / ".repo" / "manifests" / (_MANIFEST_FILENAME + ".bak")
    assert bak_path.is_file(), f"Expected backup file at {bak_path} after envsubst."
    bak_content = bak_path.read_text(encoding="utf-8")
    assert original_placeholder in bak_content, (
        f"Expected original placeholder {original_placeholder!r} in backup file, "
        f"but it was not found. Backup content: {bak_content!r}"
    )

    processed_content = _read_manifest(workspace)
    assert original_placeholder not in processed_content, (
        f"Expected placeholder to be resolved in processed manifest. Processed content: {processed_content!r}"
    )
    assert substituted_url in processed_content, (
        f"Expected {substituted_url!r} in processed manifest. Processed content: {processed_content!r}"
    )


@pytest.mark.integration
def test_missing_variable_left_as_placeholder(tmp_path: pathlib.Path) -> None:
    """A ${VAR} placeholder whose variable is not in env_vars is left unchanged.

    os.path.expandvars leaves ${MISSING_VAR} unexpanded when the variable is
    not set in the environment. This test verifies that a placeholder for an
    unknown variable is not silently replaced with an empty string.

    AC-FUNC-006, AC-FUNC-008
    """
    placeholder = "${KANON_MISSING_VAR_ZXCVB}"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="{placeholder}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    # Ensure the variable is not set in the environment
    env_before = os.environ.pop("KANON_MISSING_VAR_ZXCVB", None)
    try:
        repo_pkg.repo_envsubst(str(workspace), {})
    finally:
        if env_before is not None:
            os.environ["KANON_MISSING_VAR_ZXCVB"] = env_before

    content = _read_manifest(workspace)
    assert placeholder in content, (
        f"Expected missing placeholder {placeholder!r} to remain in the manifest "
        f"(not silently replaced), but it was not found. "
        f"Manifest content: {content!r}"
    )


@pytest.mark.integration
def test_empty_value_substitution_replaces_placeholder(tmp_path: pathlib.Path) -> None:
    """A ${VAR} placeholder whose variable is set to an empty string is replaced with empty.

    When the env_vars dict contains a key mapped to an empty string, the
    placeholder is replaced with an empty string in the manifest attribute.

    AC-FUNC-007, AC-FUNC-008
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${KANON_EMPTY_VAL}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_EMPTY_VAL": ""})

    content = _read_manifest(workspace)
    assert "${KANON_EMPTY_VAL}" not in content, (
        f"Expected empty-value placeholder to be replaced (with empty string), "
        f"but it is still present. Manifest content: {content!r}"
    )


@pytest.mark.integration
def test_special_characters_in_value(tmp_path: pathlib.Path) -> None:
    """A ${VAR} placeholder is substituted with a value containing slashes and colons.

    Verifies that URL-like values containing path separators and protocol colons
    are substituted correctly without corruption.

    AC-FUNC-007, AC-FUNC-008
    """
    url_with_path = "file:///some/path/with/slashes/and-hyphens"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${KANON_SPECIAL_VAL}" />\n'
        '  <default revision="main" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_SPECIAL_VAL": url_with_path})

    content = _read_manifest(workspace)
    assert "${KANON_SPECIAL_VAL}" not in content, f"Expected placeholder to be resolved. Manifest content: {content!r}"
    assert url_with_path in content, (
        f"Expected {url_with_path!r} in manifest after envsubst. Manifest content: {content!r}"
    )


@pytest.mark.integration
def test_multiple_xml_files_all_processed(tmp_path: pathlib.Path) -> None:
    """All XML files under .repo/manifests/ are processed by envsubst.

    Creates a manifest repo with two XML files -- default.xml and an extra.xml.
    Both files contain ${VAR} placeholders. After repo_envsubst(), both files
    must have their placeholders resolved.

    The extra.xml uses a placeholder only in its remote fetch attribute so that
    repo init can parse and validate the main manifest without referencing the
    extra.xml file.

    AC-FUNC-008
    """
    main_fetch_url = f"file://{tmp_path}/multi-xml-main"
    extra_fetch_url = f"file://{tmp_path}/multi-xml-extra"
    main_manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="${KANON_MULTI_XML_MAIN_FETCH}" />\n'
        '  <default revision="main" remote="origin" />\n'
        "</manifest>\n"
    )
    extra_manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="extra-origin" fetch="${KANON_MULTI_XML_EXTRA_FETCH}" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(
        tmp_path,
        main_manifest_xml,
        extra_files={"extra.xml": extra_manifest_xml},
    )

    repo_pkg.repo_envsubst(
        str(workspace),
        {
            "KANON_MULTI_XML_MAIN_FETCH": main_fetch_url,
            "KANON_MULTI_XML_EXTRA_FETCH": extra_fetch_url,
        },
    )

    main_content = _read_manifest(workspace, _MANIFEST_FILENAME)
    assert "${KANON_MULTI_XML_MAIN_FETCH}" not in main_content, (
        f"Expected KANON_MULTI_XML_MAIN_FETCH to be resolved in default.xml. Content: {main_content!r}"
    )
    assert main_fetch_url in main_content, (
        f"Expected {main_fetch_url!r} in default.xml after envsubst. Content: {main_content!r}"
    )

    extra_content = _read_manifest(workspace, "extra.xml")
    assert "${KANON_MULTI_XML_EXTRA_FETCH}" not in extra_content, (
        f"Expected KANON_MULTI_XML_EXTRA_FETCH to be resolved in extra.xml. Content: {extra_content!r}"
    )
    assert extra_fetch_url in extra_content, (
        f"Expected {extra_fetch_url!r} in extra.xml after envsubst. Content: {extra_content!r}"
    )


@pytest.mark.integration
def test_no_placeholder_manifest_unchanged_content(tmp_path: pathlib.Path) -> None:
    """A manifest with no ${VAR} placeholders is unchanged after envsubst (no-op).

    The manifest is reparsed and re-serialised by the XML DOM layer, which may
    change whitespace. The essential content (remote name, project name) must
    be preserved.

    AC-FUNC-008
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="static-origin" fetch="https://example.com/static" />\n'
        '  <default revision="main" remote="static-origin" />\n'
        '  <project name="static-proj" path="static-proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {})

    content = _read_manifest(workspace)
    assert "static-origin" in content, (
        f"Expected static remote name to be preserved after no-op envsubst. Manifest content: {content!r}"
    )
    assert "https://example.com/static" in content, (
        f"Expected static fetch URL to be preserved after no-op envsubst. Manifest content: {content!r}"
    )
    assert "static-proj" in content, (
        f"Expected static project name to be preserved after no-op envsubst. Manifest content: {content!r}"
    )


@pytest.mark.integration
def test_substitution_in_revision_attribute(tmp_path: pathlib.Path) -> None:
    """${VAR} in the revision attribute of a default element is substituted correctly.

    Verifies that substitution works for attributes other than fetch, exercising
    the search_replace_placeholders logic across different element/attribute
    combinations.

    AC-FUNC-003, AC-FUNC-008
    """
    branch_name = "release/2.0"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com/rev" />\n'
        '  <default revision="${KANON_REVISION_VAR}" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_REVISION_VAR": branch_name})

    content = _read_manifest(workspace)
    assert "${KANON_REVISION_VAR}" not in content, (
        f"Expected revision placeholder to be resolved. Manifest content: {content!r}"
    )
    assert branch_name in content, f"Expected {branch_name!r} in manifest after envsubst. Manifest content: {content!r}"


@pytest.mark.integration
def test_no_repo_dir_raises_repo_command_error(tmp_path: pathlib.Path) -> None:
    """repo_envsubst() raises RepoCommandError when .repo/ does not exist.

    Calling repo_envsubst() on a directory where repo init has not been run
    must raise RepoCommandError immediately (fail-fast) rather than silently
    succeeding or raising a generic OSError.

    AC-FUNC-006
    """
    workspace = tmp_path / "no-init-workspace"
    workspace.mkdir()

    with pytest.raises(RepoCommandError) as exc_info:
        repo_pkg.repo_envsubst(str(workspace), {"KANON_SOME_VAR": "value"})

    assert exc_info.value.exit_code != 0, (
        f"Expected non-zero exit_code on missing .repo/ failure, but got: {exc_info.value.exit_code!r}"
    )
    assert "repo" in str(exc_info.value).lower(), (
        f"Expected error message to reference the repo directory. Got: {exc_info.value!r}"
    )
    assert "repo init" in str(exc_info.value), (
        f"Expected error message to suggest running repo init. Got: {exc_info.value!r}"
    )


@pytest.mark.integration
def test_env_vars_restored_after_successful_envsubst(tmp_path: pathlib.Path) -> None:
    """env_vars injected for envsubst are removed from os.environ after the call.

    repo_envsubst() must not pollute the calling process environment with the
    variables it injects. After a successful call, the variable must no longer
    be present (or must be restored to its pre-call value).

    AC-FUNC-008
    """
    var_name = "KANON_ENV_CLEANUP_TEST_VAR"
    original_value = os.environ.pop(var_name, None)
    try:
        manifest_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="origin" fetch="${{{var_name}}}" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="proj" path="proj" />\n'
            "</manifest>\n"
        )
        workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

        repo_pkg.repo_envsubst(str(workspace), {var_name: "file:///tmp/cleanup-content"})

        assert var_name not in os.environ, (
            f"Expected {var_name!r} to be removed from os.environ after repo_envsubst(), "
            f"but it is still present with value {os.environ.get(var_name)!r}."
        )
    finally:
        if original_value is not None:
            os.environ[var_name] = original_value


@pytest.mark.integration
def test_env_vars_restored_after_failed_envsubst(tmp_path: pathlib.Path) -> None:
    """env_vars are cleaned up from os.environ even when envsubst raises an error.

    When repo_envsubst() fails (e.g., .repo/ does not exist), variables
    injected into os.environ must still be removed in the finally block.

    AC-FUNC-006, AC-FUNC-008
    """
    var_name = "KANON_ENV_CLEANUP_FAIL_VAR"
    original_value = os.environ.pop(var_name, None)
    try:
        workspace = tmp_path / "no-init-env-cleanup"
        workspace.mkdir()

        with pytest.raises(RepoCommandError):
            repo_pkg.repo_envsubst(str(workspace), {var_name: "file:///tmp/fail-cleanup"})

        assert var_name not in os.environ, (
            f"Expected {var_name!r} to be cleaned up even after envsubst failure, "
            f"but it is still present with value {os.environ.get(var_name)!r}."
        )
    finally:
        if original_value is not None:
            os.environ[var_name] = original_value


@pytest.mark.integration
def test_multiline_value_substituted_in_attribute(tmp_path: pathlib.Path) -> None:
    """A value containing newlines can be set via env_vars and substituted correctly.

    Verifies that repo_envsubst() handles values that include embedded newlines
    by injecting the variable and verifying the original placeholder is no longer
    present after substitution.

    AC-FUNC-007, AC-FUNC-008
    """
    multiline_value = "line-one line-two"
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch="https://example.com/ml" />\n'
        '  <default revision="${KANON_MULTILINE_VAR}" remote="origin" />\n'
        '  <project name="proj" path="proj" />\n'
        "</manifest>\n"
    )
    workspace = _make_workspace_with_manifest(tmp_path, manifest_xml)

    repo_pkg.repo_envsubst(str(workspace), {"KANON_MULTILINE_VAR": multiline_value})

    content = _read_manifest(workspace)
    assert "${KANON_MULTILINE_VAR}" not in content, (
        f"Expected multiline placeholder to be resolved after envsubst. Manifest content: {content!r}"
    )
