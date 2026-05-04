"""Tests for E2-F3-S2-T2: PEP 440 fallback in `kanon repo manifest --revision-as-tag`.

When `git describe --exact-match HEAD` fails for a project (e.g. the
manifest's `<project revision>` is a constraint like `refs/tags/latest`,
`refs/tags/~=1.0.0`, `refs/tags/<=1.1.0`, etc., and the synced commit
isn't pointed at by a fetched tag), `_apply_revision_as_tag` now falls
back to resolving the constraint against the project's locally-known
tags via `version_constraints.resolve_version_constraint`. The
manifest output then carries the concrete `refs/tags/<name>` form
instead of the raw constraint.

Affected scenarios (II-004 + II-008): RX-01..07, RX-10, RX-11, RX-13,
RX-14, RX-17..20, RX-23, RX-24, PK-02, PK-07, PK-10. Implements
E2-F3-S2-T2.
"""

from __future__ import annotations

import xml.dom.minidom

import pytest

from kanon_cli.repo.git_command import GitCommandError
from kanon_cli.repo.subcmds.manifest import (
    _apply_revision_as_tag,
    _resolve_pep440_revision,
)


class _FakeWorkGit:
    """Stand-in for ``project.work_git`` returning a fixed tag list."""

    def __init__(self, tag_list_output: str) -> None:
        self._tag_list_output = tag_list_output

    def tag(self, *args: str) -> str:
        # `_resolve_pep440_revision` calls work_git.tag("--list").
        return self._tag_list_output


class _FakeProject:
    def __init__(self, tag_list_output: str = "1.0.0\n1.0.1\n1.1.0\n2.0.0\n3.0.0\n") -> None:
        self.work_git = _FakeWorkGit(tag_list_output)


def _make_doc(revision: str) -> xml.dom.minidom.Document:
    """Build a minimal manifest XML doc with one <project>."""
    doc = xml.dom.minidom.Document()
    root = doc.createElement("manifest")
    project = doc.createElement("project")
    project.setAttribute("name", "demo")
    project.setAttribute("path", "demo")
    if revision:
        project.setAttribute("revision", revision)
    root.appendChild(project)
    doc.appendChild(root)
    return doc


@pytest.mark.unit
class TestResolvePep440Revision:
    @pytest.mark.parametrize(
        "rev_in,expected",
        [
            ("refs/tags/latest", "refs/tags/3.0.0"),
            ("refs/tags/*", "refs/tags/3.0.0"),
            ("refs/tags/~=1.0.0", "refs/tags/1.0.1"),
            ("refs/tags/>=1.0.0", "refs/tags/3.0.0"),
            ("refs/tags/<=1.1.0", "refs/tags/1.1.0"),
            ("refs/tags/<2.0.0", "refs/tags/1.1.0"),
            ("refs/tags/==1.0.1", "refs/tags/1.0.1"),
            ("refs/tags/!=3.0.0", "refs/tags/2.0.0"),
            ("refs/tags/>=1.0.0,<2.0.0", "refs/tags/1.1.0"),
        ],
    )
    def test_resolves_constraint_to_concrete_tag(self, rev_in: str, expected: str) -> None:
        proj = _FakeProject()
        assert _resolve_pep440_revision(proj, rev_in) == expected

    def test_returns_none_for_non_constraint(self) -> None:
        proj = _FakeProject()
        # Plain branch / SHA / unprefixed-tag -- not a constraint.
        assert _resolve_pep440_revision(proj, "main") is None
        assert _resolve_pep440_revision(proj, "refs/tags/1.0.0") is None
        # Plain `refs/tags/1.0.0` is NOT recognised by is_version_constraint
        # (the last component "1.0.0" has no operator and is not "*"/"latest").

    def test_returns_none_for_empty_revision(self) -> None:
        proj = _FakeProject()
        assert _resolve_pep440_revision(proj, "") is None

    def test_returns_none_when_tag_list_empty(self) -> None:
        proj = _FakeProject(tag_list_output="")
        assert _resolve_pep440_revision(proj, "refs/tags/latest") is None

    def test_returns_none_for_unmatchable_constraint(self) -> None:
        proj = _FakeProject()
        # Tags only go up to 3.0.0; >=4.0 has no match.
        assert _resolve_pep440_revision(proj, "refs/tags/>=4.0") is None


@pytest.mark.unit
class TestApplyRevisionAsTagPep440Fallback:
    def test_git_describe_success_takes_precedence(self) -> None:
        """When `git describe` succeeds, the constraint fallback is NOT invoked."""
        doc = _make_doc("refs/tags/latest")
        proj = _FakeProject()

        def lookup_fn() -> str:
            return "refs/tags/exact-via-describe"

        _apply_revision_as_tag(doc, "demo", lookup_fn, proj)
        elem = doc.getElementsByTagName("project")[0]
        assert elem.getAttribute("revision") == "refs/tags/exact-via-describe"

    def test_git_describe_failure_triggers_pep440_fallback(self) -> None:
        """When `git describe` raises, the PEP 440 resolver fills in the tag."""
        doc = _make_doc("refs/tags/latest")
        proj = _FakeProject()

        def lookup_fn() -> str:
            raise GitCommandError("no tag at HEAD", git_rc=128, git_stderr="fatal: no tag at HEAD")

        _apply_revision_as_tag(doc, "demo", lookup_fn, proj)
        elem = doc.getElementsByTagName("project")[0]
        assert elem.getAttribute("revision") == "refs/tags/3.0.0"

    def test_failure_with_no_constraint_warns_unchanged(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When `git describe` fails AND the revision isn't a constraint, the
        manifest entry is left unchanged and a warning is emitted."""
        doc = _make_doc("main")
        proj = _FakeProject()

        def lookup_fn() -> str:
            raise GitCommandError("no tag at HEAD", git_rc=128, git_stderr="fatal: no tag at HEAD")

        _apply_revision_as_tag(doc, "demo", lookup_fn, proj)
        elem = doc.getElementsByTagName("project")[0]
        assert elem.getAttribute("revision") == "main"
        captured = capsys.readouterr()
        assert "no exact tag at HEAD; revision unchanged" in captured.err

    def test_no_project_argument_disables_fallback(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Backward compat: when project=None, the fallback is skipped."""
        doc = _make_doc("refs/tags/latest")

        def lookup_fn() -> str:
            raise GitCommandError("no tag at HEAD", git_rc=128, git_stderr="fatal: no tag at HEAD")

        _apply_revision_as_tag(doc, "demo", lookup_fn, None)
        elem = doc.getElementsByTagName("project")[0]
        assert elem.getAttribute("revision") == "refs/tags/latest"
        captured = capsys.readouterr()
        assert "no exact tag at HEAD; revision unchanged" in captured.err
