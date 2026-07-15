"""Integration tests for the ``kanon list`` command's ``--format json`` output.

Distinct from ``test_list_format_json.py`` (which covers ``kanon search`` -- the
catalog-discovery command formerly named ``list``). This module covers the NEW
declared-vs-installed inventory command: it invokes ``kanon list ... --format
json`` via subprocess and parses stdout with ``json.loads`` to pin the JSON
schema across flag combinations -- the top-level ``sources`` array, the
per-source keys and status tags, the ``--declared`` / ``--status`` filters, and
the nested transitive ``projects`` list under ``--tree``.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from kanon_cli.core.lockfile import (
    ContentPinEntry,
    Lockfile,
    ProjectEntry,
    SourceEntry,
    write_lockfile,
)
from kanon_cli.core.url import canonicalize_repo_url
from tests.scenarios.conftest import run_kanon


_ENV = {"NO_COLOR": "1", "KANON_TELEMETRY_DISABLED": "1", "KANON_SKIP_UPDATE_CHECK": "1"}
_SOURCE_KEYS = {"alias", "status", "name", "url", "ref_spec", "resolved_ref", "resolved_sha", "scope"}


@pytest.fixture()
def project(tmp_path: pathlib.Path) -> pathlib.Path:
    """A project where foo=installed (+1 transitive), bar=not-installed, baz=orphan."""
    (tmp_path / ".kanon").write_text(
        "GITBASE=https://github.com/acme\n"
        "KANON_SOURCE_foo_URL=https://github.com/acme/foo\n"
        "KANON_SOURCE_foo_REF=1.0.0\nKANON_SOURCE_foo_PATH=vendor/foo\nKANON_SOURCE_foo_NAME=foo\n"
        "KANON_SOURCE_bar_URL=https://github.com/acme/bar\n"
        "KANON_SOURCE_bar_REF=2.0.0\nKANON_SOURCE_bar_PATH=vendor/bar\nKANON_SOURCE_bar_NAME=bar\n"
    )
    libcore = "https://github.com/acme/libcore"
    write_lockfile(
        Lockfile(
            schema_version=5,
            generated_at="t",
            generator="g",
            kanon_hash="sha256:" + "0" * 64,
            sources=[
                SourceEntry(
                    alias="foo",
                    name="foo",
                    url="https://github.com/acme/foo",
                    ref_spec="1.0.0",
                    resolved_ref="refs/tags/1.0.0",
                    resolved_sha="a" * 40,
                    path="vendor/foo",
                    projects=[
                        ProjectEntry(
                            name="libcore",
                            url=libcore,
                            canonical_url=canonicalize_repo_url(libcore),
                            ref_spec="*",
                            resolved_ref="refs/heads/main",
                            resolved_sha="b" * 40,
                        )
                    ],
                ),
                SourceEntry(
                    alias="baz",
                    name="baz",
                    url="https://github.com/acme/baz",
                    ref_spec="0.9.0",
                    resolved_ref="refs/tags/0.9.0",
                    resolved_sha="c" * 40,
                    path="vendor/baz",
                    content_pins=[ContentPinEntry(name="baz-pin", path="p", resolved_sha="d" * 40)],
                ),
            ],
        ),
        tmp_path / ".kanon.lock",
    )
    return tmp_path


def _sources(project: pathlib.Path, *flags: str) -> list[dict]:
    """Run ``kanon list --format json`` with extra flags and return the sources array."""
    result = run_kanon("list", "--format", "json", *flags, cwd=project, extra_env=_ENV)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {"sources"}
    return payload["sources"]


@pytest.mark.integration
class TestListCommandJson:
    """The JSON schema is stable and correct across flag combinations."""

    def test_default_schema_and_statuses(self, project: pathlib.Path) -> None:
        """Every source object carries the canonical key set and correct status."""
        sources = _sources(project)
        by_alias = {source["alias"]: source for source in sources}
        assert set(by_alias) == {"foo", "bar", "baz"}
        for source in sources:
            assert _SOURCE_KEYS.issubset(source)
            assert source["scope"] == "direct"
        assert by_alias["foo"]["status"] == "installed"
        assert by_alias["bar"]["status"] == "not-installed"
        assert by_alias["baz"]["status"] == "orphan"

    def test_not_installed_has_empty_resolved_fields(self, project: pathlib.Path) -> None:
        """A not-installed source has empty resolved_ref / resolved_sha."""
        bar = next(source for source in _sources(project) if source["alias"] == "bar")
        assert bar["resolved_ref"] == ""
        assert bar["resolved_sha"] == ""
        assert bar["ref_spec"] == "2.0.0"

    def test_declared_filter(self, project: pathlib.Path) -> None:
        """--declared omits orphan sources from the JSON."""
        aliases = {source["alias"] for source in _sources(project, "--declared")}
        assert aliases == {"foo", "bar"}

    def test_status_filter(self, project: pathlib.Path) -> None:
        """--status installed returns only installed sources."""
        sources = _sources(project, "--status", "installed")
        assert [source["alias"] for source in sources] == ["foo"]

    def test_tree_nests_projects(self, project: pathlib.Path) -> None:
        """--tree nests a transitive projects array on each source."""
        by_alias = {source["alias"]: source for source in _sources(project, "--tree")}
        assert [entry["name"] for entry in by_alias["foo"]["projects"]] == ["libcore"]
        assert by_alias["foo"]["projects"][0]["scope"] == "transitive"
        assert [pin["name"] for pin in by_alias["baz"]["projects"]] == ["baz-pin"]
        assert by_alias["bar"]["projects"] == []

    def test_no_projects_key_without_tree(self, project: pathlib.Path) -> None:
        """Without --tree, sources carry no projects key."""
        for source in _sources(project):
            assert "projects" not in source
