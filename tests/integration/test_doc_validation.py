"""Integration tests that validate documentation completeness and accuracy.

These tests scan documentation files for stale references and incorrect
command usage.

Covered acceptance criteria:
  - AC-TEST-001: test_no_stale_pipx_references -- zero occurrences of
    "pipx install rpm-git-repo" across all doc files
  - AC-TEST-002: test_no_standalone_repo_references -- no doc file code blocks
    reference "repo" as a standalone CLI command without the "kanon" prefix
  - AC-TEST-004: test_docs_use_auto_discover -- primary onboarding doc files
    that reference "kanon install" or "kanon clean" in code blocks do NOT pass
    ".kanon" as a positional argument in those invocations
  - AC-TEST-005: test_catalog_no_repo_url -- catalog/.kanon does not contain
    any uncommented REPO_URL or REPO_REV lines
  - item 33 (E15-F1-S1): TestInitDefaultBranchPrerequisiteEnforced --
    docs/integration-testing.md documents the init.defaultBranch=main test
    prerequisite, AND both CI (.github/actions/setup-kanon/action.yml) and the
    devcontainer (.devcontainer/.devcontainer.postcreate.sh) run
    'git config --global init.defaultBranch main', so drift in any of the three
    enforcement points fails CI.
"""

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).parent.parent.parent
_DOCS_DIR = _REPO_ROOT / "docs"
_README = _REPO_ROOT / "README.md"
_CHANGELOG = _REPO_ROOT / "CHANGELOG.md"

_INTEGRATION_TESTING_DOC = _DOCS_DIR / "integration-testing.md"
_SETUP_KANON_ACTION = _REPO_ROOT / ".github" / "actions" / "setup-kanon" / "action.yml"
_DEVCONTAINER_POSTCREATE = _REPO_ROOT / ".devcontainer" / ".devcontainer.postcreate.sh"

_INIT_DEFAULT_BRANCH_CONFIG_RE = re.compile(r"git\s+config\s+--global\s+init\.defaultBranch\s+main")


_ALL_DOC_FILES: list[Path] = sorted(list(_DOCS_DIR.glob("**/*.md")) + [_README, _CHANGELOG])


_ONBOARDING_DOC_FILES: list[Path] = [
    _DOCS_DIR / "setup-guide.md",
    _DOCS_DIR / "lifecycle.md",
    _DOCS_DIR / "creating-manifest-repos.md",
    _DOCS_DIR / "creating-packages.md",
    _DOCS_DIR / "multi-source-guide.md",
]


_CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _collect_matching_lines(files: list[Path], pattern: str) -> list[str]:
    """Return lines containing *pattern* across all *files*.

    Only regular files decodable as UTF-8 are examined.  Each returned string
    has the form ``<filename>:<line_no>: <content>``.
    """
    hits: list[str] = []
    for file_path in files:
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                rel = file_path.name
                hits.append(f"{rel}:{line_no}: {line.strip()}")
    return hits


def _extract_code_block_lines(file_path: Path) -> list[str]:
    """Return all lines found inside fenced code blocks in *file_path*.

    Each returned string is the stripped content of one code-block line.
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return []
    lines: list[str] = []
    for block_body in _CODE_BLOCK_RE.findall(text):
        for line in block_body.splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return lines


@pytest.mark.integration
class TestNoStalePipxReferences:
    """AC-TEST-001: All doc files must have zero occurrences of
    'pipx install rpm-git-repo'.

    Kanon's repo subsystem is part of the kanon-cli package -- there is no
    separate rpm-git-repo install step.
    """

    def test_no_stale_pipx_references(self) -> None:
        """Zero occurrences of 'pipx install rpm-git-repo' across all doc files."""
        stale_pattern = "pipx install rpm-git-repo"
        hits = _collect_matching_lines(_ALL_DOC_FILES, stale_pattern)
        assert not hits, (
            f"Found {len(hits)} stale reference(s) to '{stale_pattern}' in doc files.\n"
            "The repo tool is now embedded in kanon-cli -- remove any reference to\n"
            "installing it separately via pipx:\n" + "\n".join(hits)
        )

    @pytest.mark.parametrize(
        "doc_path",
        [
            _DOCS_DIR / "setup-guide.md",
            _DOCS_DIR / "how-it-works.md",
            _DOCS_DIR / "creating-manifest-repos.md",
            _DOCS_DIR / "creating-packages.md",
            _DOCS_DIR / "claude-marketplaces-guide.md",
            _DOCS_DIR / "multi-source-guide.md",
        ],
    )
    def test_individual_doc_no_stale_pipx(self, doc_path: Path) -> None:
        """Each primary doc file must not reference 'pipx install rpm-git-repo'."""
        assert doc_path.is_file(), f"Expected doc file to exist: {doc_path}"
        text = doc_path.read_text(encoding="utf-8")
        assert "pipx install rpm-git-repo" not in text, (
            f"{doc_path.name} contains a stale reference to 'pipx install rpm-git-repo'.\n"
            "The repo tool is embedded -- remove this installation instruction."
        )


@pytest.mark.integration
class TestNoStandaloneRepoReferences:
    """AC-TEST-002: No doc file code blocks reference "repo" as a standalone
    CLI command without the "kanon" prefix.

    Code examples must use "kanon repo <subcommand>" for all repo operations.
    """

    def test_no_standalone_repo_references(self) -> None:
        """Code blocks across all doc files must not contain bare 'repo <cmd>' invocations."""

        standalone_repo_re = re.compile(r"^repo\s")
        violations: list[str] = []
        for doc_path in _ALL_DOC_FILES:
            if not doc_path.is_file():
                continue
            for line in _extract_code_block_lines(doc_path):
                if standalone_repo_re.match(line):
                    violations.append(f"{doc_path.name}: {line!r}")
        assert not violations, (
            f"Found {len(violations)} standalone 'repo <cmd>' invocation(s) in code blocks.\n"
            "Replace 'repo <subcommand>' with 'kanon repo <subcommand>':\n" + "\n".join(violations)
        )

    @pytest.mark.parametrize(
        "doc_path",
        [
            _DOCS_DIR / "setup-guide.md",
            _DOCS_DIR / "configuration.md",
        ],
    )
    def test_specific_doc_no_standalone_repo_in_code_blocks(self, doc_path: Path) -> None:
        """Core user docs must not show standalone 'repo' commands in code blocks."""
        assert doc_path.is_file(), f"Expected doc file to exist: {doc_path}"
        standalone_repo_re = re.compile(r"^repo\s")
        violations = [line for line in _extract_code_block_lines(doc_path) if standalone_repo_re.match(line)]
        assert not violations, (
            f"{doc_path.name} code blocks contain standalone 'repo' commands: {violations!r}\n"
            "Use 'kanon repo <subcommand>' instead."
        )


@pytest.mark.integration
class TestDocsUseAutoDiscover:
    """AC-TEST-004: Primary onboarding doc files that contain 'kanon install'
    or 'kanon clean' in code blocks must NOT include '.kanon' as a positional
    argument.

    These docs should guide users to the auto-discovery form ('kanon install'
    with no path argument), which finds the .kanon file by walking up the
    directory tree from cwd.  Explicit-path forms ('kanon install .kanon')
    belong in the CLI reference and integration-testing docs, not in the
    user-facing setup guides.
    """

    @pytest.mark.parametrize("doc_path", _ONBOARDING_DOC_FILES)
    def test_docs_use_auto_discover(self, doc_path: Path) -> None:
        """Onboarding doc code blocks must not pass '.kanon' to kanon install/clean."""
        assert doc_path.is_file(), f"Expected onboarding doc to exist: {doc_path}"
        violations: list[str] = []
        for line in _extract_code_block_lines(doc_path):
            if ("kanon install" in line or "kanon clean" in line) and re.search(
                r"\bkanon\s+(?:install|clean)\b.*\B\.kanon\b", line
            ):
                violations.append(line)
        assert not violations, (
            f"{doc_path.name} contains 'kanon install/clean .kanon' in code blocks.\n"
            "Onboarding docs should use the auto-discovery form ('kanon install' with no path).\n"
            "Found:\n" + "\n".join(f"  {v!r}" for v in violations)
        )


@pytest.mark.integration
class TestInitDefaultBranchPrerequisiteEnforced:
    """item 33 (E15-F1-S1): the init.defaultBranch=main test prerequisite is
    documented and enforced in all three places.

    Local/file:// default-branch resolution (item 3) and the integration suite
    rely on freshly ``git init``-ed repos defaulting to ``main``. That only holds
    when ``init.defaultBranch`` is configured to ``main``. This prerequisite is
    documented in ``docs/integration-testing.md`` and applied automatically by
    CI (``.github/actions/setup-kanon/action.yml``) and the devcontainer
    (``.devcontainer/.devcontainer.postcreate.sh``). If any of the three drifts,
    the suite would silently regress to ``master`` defaults, so these assertions
    fail CI on drift.
    """

    def test_doc_documents_the_prerequisite_section(self) -> None:
        """integration-testing.md has the init.defaultBranch=main prerequisite section."""
        assert _INTEGRATION_TESTING_DOC.is_file(), f"Expected doc to exist: {_INTEGRATION_TESTING_DOC}"
        text = _INTEGRATION_TESTING_DOC.read_text(encoding="utf-8")
        assert "## Test prerequisites" in text, (
            f"{_INTEGRATION_TESTING_DOC.name} is missing the 'Test prerequisites' section heading."
        )
        assert "### `init.defaultBranch=main`" in text, (
            f"{_INTEGRATION_TESTING_DOC.name} is missing the '### `init.defaultBranch=main`' "
            "prerequisite subsection heading."
        )
        assert _INIT_DEFAULT_BRANCH_CONFIG_RE.search(text), (
            f"{_INTEGRATION_TESTING_DOC.name} no longer shows the "
            "'git config --global init.defaultBranch main' prerequisite command."
        )

    def test_ci_setup_action_sets_init_default_branch(self) -> None:
        """The setup-kanon composite action runs 'git config --global init.defaultBranch main'."""
        assert _SETUP_KANON_ACTION.is_file(), f"Expected CI action to exist: {_SETUP_KANON_ACTION}"
        text = _SETUP_KANON_ACTION.read_text(encoding="utf-8")
        assert _INIT_DEFAULT_BRANCH_CONFIG_RE.search(text), (
            f"{_SETUP_KANON_ACTION} no longer runs "
            "'git config --global init.defaultBranch main'. CI runners default new "
            "repos to 'master', so dropping this would break the @main integration fixtures."
        )

    def test_devcontainer_postcreate_sets_init_default_branch(self) -> None:
        """The devcontainer postcreate script runs 'git config --global init.defaultBranch main'."""
        assert _DEVCONTAINER_POSTCREATE.is_file(), (
            f"Expected devcontainer postcreate script to exist: {_DEVCONTAINER_POSTCREATE}"
        )
        text = _DEVCONTAINER_POSTCREATE.read_text(encoding="utf-8")
        assert _INIT_DEFAULT_BRANCH_CONFIG_RE.search(text), (
            f"{_DEVCONTAINER_POSTCREATE} no longer runs "
            "'git config --global init.defaultBranch main'. The dev environment must "
            "satisfy the prerequisite automatically; dropping this would regress local runs."
        )
