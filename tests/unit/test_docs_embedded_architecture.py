"""Tests that verify docs/how-it-works.md and docs/lifecycle.md reflect
the embedded repo architecture and Python API calls.

AC-DOC-001: how-it-works.md shows embedded architecture
AC-DOC-002: how-it-works.md has no references to repo as a separate external tool
AC-DOC-003: how-it-works.md describes direct Python API calls instead of subprocess
AC-DOC-004: lifecycle.md "install repo tool" step removed
AC-DOC-005: lifecycle.md shows repo operations as direct Python API calls
AC-DOC-006: lifecycle.md has no references to pipx provisioning
"""

import pathlib

import pytest

DOCS_DIR = pathlib.Path(__file__).parent.parent.parent / "docs"
HOW_IT_WORKS = DOCS_DIR / "how-it-works.md"
LIFECYCLE = DOCS_DIR / "lifecycle.md"


@pytest.mark.unit
class TestHowItWorksEmbeddedArchitecture:
    """AC-DOC-001: how-it-works.md shows embedded architecture."""

    def test_doc_exists(self) -> None:
        assert HOW_IT_WORKS.exists(), f"Expected {HOW_IT_WORKS} to exist"

    def test_mentions_embedded_package(self) -> None:
        content = HOW_IT_WORKS.read_text()
        assert "kanon_cli.repo" in content, "how-it-works.md must describe the kanon_cli.repo package structure"

    def test_mentions_python_api(self) -> None:
        content = HOW_IT_WORKS.read_text()
        assert "Python API" in content or "Python api" in content.lower(), (
            "how-it-works.md must describe direct Python API calls"
        )


@pytest.mark.unit
class TestHowItWorksNoExternalTool:
    """AC-DOC-002: how-it-works.md has no references to repo as a separate external tool.
    AC-DOC-003: describes direct Python API calls instead of subprocess.
    """

    def test_no_pipx_reference(self) -> None:
        content = HOW_IT_WORKS.read_text()
        assert "pipx" not in content, "how-it-works.md must not reference pipx (repo is no longer a separate tool)"

    def test_no_subprocess_reference(self) -> None:
        content = HOW_IT_WORKS.read_text()
        assert "subprocess" not in content, "how-it-works.md must not reference subprocess calls"

    def test_no_install_repo_tool_reference(self) -> None:
        content = HOW_IT_WORKS.read_text()
        assert "install repo tool" not in content.lower(), (
            "how-it-works.md must not describe installing repo as a separate external tool"
        )

    def test_no_external_rpm_git_repo_install_reference(self) -> None:
        content = HOW_IT_WORKS.read_text()
        assert "rpm-git-repo" not in content, (
            "how-it-works.md must not reference rpm-git-repo as a separately-installed package"
        )


@pytest.mark.unit
class TestLifecycleNoInstallRepoStep:
    """AC-DOC-004: lifecycle.md 'install repo tool' step removed."""

    def test_doc_exists(self) -> None:
        assert LIFECYCLE.exists(), f"Expected {LIFECYCLE} to exist"

    def test_no_install_repo_tool_step(self) -> None:
        content = LIFECYCLE.read_text()
        assert "Install repo tool" not in content, "lifecycle.md must not contain an 'Install repo tool' step"

    def test_no_check_pipx_step(self) -> None:
        content = LIFECYCLE.read_text()
        assert "Check pipx on PATH" not in content, "lifecycle.md must not contain a 'Check pipx on PATH' step"


@pytest.mark.unit
class TestLifecyclePythonAPICalls:
    """AC-DOC-005: lifecycle.md shows repo operations as direct Python API calls."""

    def test_mentions_python_api_calls(self) -> None:
        content = LIFECYCLE.read_text()
        assert "Python API" in content or "kanon_cli.repo" in content, (
            "lifecycle.md must describe repo operations as Python API calls"
        )


@pytest.mark.unit
class TestLifecycleNoPipxReferences:
    """AC-DOC-006: lifecycle.md has no references to pipx provisioning."""

    def test_no_pipx_reference(self) -> None:
        content = LIFECYCLE.read_text()
        assert "pipx" not in content, "lifecycle.md must not reference pipx"

    def test_no_pipx_install_reference(self) -> None:
        content = LIFECYCLE.read_text()
        assert "pipx install" not in content, "lifecycle.md must not contain pipx install instructions"

    def test_no_pipx_list_reference(self) -> None:
        content = LIFECYCLE.read_text()
        assert "pipx list" not in content, "lifecycle.md must not reference pipx list"
