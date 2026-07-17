"""Functional tests for ``kanon list`` over a real subprocess.

Drives ``python -m kanon_cli list`` against hand-built ``.kanon`` / ``.kanon.lock``
fixtures and asserts the externally observable contract: real exit codes, the
status-tagged table / JSON on stdout, the informational notes on stderr, and --
critically -- that every failure mode produces a clean, actionable error with no
Python traceback.
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


def _write_kanon(directory: pathlib.Path, sources: list[tuple[str, str, str, str]]) -> None:
    """Write a ``.kanon`` declaring ``(alias, url, ref, name)`` sources."""
    lines = ["GITBASE=https://github.com/acme\n"]
    for alias, url, ref, name in sources:
        lines.append(f"KANON_SOURCE_{alias}_URL={url}\n")
        lines.append(f"KANON_SOURCE_{alias}_REF={ref}\n")
        lines.append(f"KANON_SOURCE_{alias}_PATH=vendor/{alias}\n")
        lines.append(f"KANON_SOURCE_{alias}_NAME={name}\n")
    (directory / ".kanon").write_text("".join(lines))


def _write_lock(directory: pathlib.Path, entries: list[dict]) -> None:
    """Write a ``.kanon.lock`` from a list of source-entry spec dicts."""
    sources = []
    for entry in entries:
        projects = [
            ProjectEntry(
                name=project["name"],
                url=project["url"],
                canonical_url=canonicalize_repo_url(project["url"]),
                ref_spec="*",
                resolved_ref="refs/heads/main",
                resolved_sha="b" * 40,
            )
            for project in entry.get("projects", [])
        ]
        pins = [ContentPinEntry(name=pin["name"], path="p", resolved_sha=pin["sha"]) for pin in entry.get("pins", [])]
        sources.append(
            SourceEntry(
                alias=entry["alias"],
                name=entry["alias"],
                url=f"https://github.com/acme/{entry['alias']}",
                ref_spec=entry["ref"],
                resolved_ref=f"refs/tags/{entry['ref']}",
                resolved_sha="a" * 40,
                path=f"vendor/{entry['alias']}",
                projects=projects,
                content_pins=pins,
            )
        )
    write_lockfile(
        Lockfile(
            schema_version=5,
            generated_at="t",
            generator="g",
            kanon_hash="sha256:" + "0" * 64,
            sources=sources,
        ),
        directory / ".kanon.lock",
    )


@pytest.fixture()
def project(tmp_path: pathlib.Path) -> pathlib.Path:
    """A project where foo=installed, bar=not-installed, baz=orphan."""
    _write_kanon(
        tmp_path,
        [
            ("foo", "https://github.com/acme/foo", "1.0.0", "foo"),
            ("bar", "https://github.com/acme/bar", "2.0.0", "bar"),
        ],
    )
    _write_lock(
        tmp_path,
        [
            {
                "alias": "foo",
                "ref": "1.0.0",
                "projects": [{"name": "libcore", "url": "https://github.com/acme/libcore"}],
            },
            {"alias": "baz", "ref": "0.9.0", "pins": [{"name": "baz-pin", "sha": "d" * 40}]},
        ],
    )
    return tmp_path


@pytest.mark.functional
class TestListFunctional:
    """Subprocess-level behaviour of every flag combination."""

    def test_default(self, project: pathlib.Path) -> None:
        """The default view exits 0 and tags all three sources."""
        result = run_kanon("list", cwd=project, extra_env=_ENV)
        assert result.returncode == 0
        assert "installed" in result.stdout
        assert "not-installed" in result.stdout
        assert "orphan" in result.stdout

    def test_declared(self, project: pathlib.Path) -> None:
        """--declared drops the orphan source."""
        result = run_kanon("list", "--declared", cwd=project, extra_env=_ENV)
        assert result.returncode == 0
        assert "foo" in result.stdout and "bar" in result.stdout
        assert "baz" not in result.stdout

    def test_status_orphan(self, project: pathlib.Path) -> None:
        """--status orphan shows only the orphan source."""
        result = run_kanon("list", "--status", "orphan", cwd=project, extra_env=_ENV)
        assert result.returncode == 0
        assert "baz" in result.stdout
        assert "foo" not in result.stdout

    def test_tree(self, project: pathlib.Path) -> None:
        """--tree lists transitive packages under their sources."""
        result = run_kanon("list", "--tree", cwd=project, extra_env=_ENV)
        assert result.returncode == 0
        assert "libcore" in result.stdout
        assert "baz-pin" in result.stdout

    def test_format_json(self, project: pathlib.Path) -> None:
        """--format json emits parseable JSON on stdout only."""
        result = run_kanon("list", "--format", "json", cwd=project, extra_env=_ENV)
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert {source["alias"] for source in payload["sources"]} == {"foo", "bar", "baz"}

    def test_no_lockfile_note_and_not_installed(self, tmp_path: pathlib.Path) -> None:
        """A project with no lock shows not-installed rows and the note on stderr."""
        _write_kanon(tmp_path, [("foo", "https://github.com/acme/foo", "1.0.0", "foo")])
        result = run_kanon("list", cwd=tmp_path, extra_env=_ENV)
        assert result.returncode == 0
        assert "not-installed" in result.stdout
        assert "not installed yet" in result.stderr


@pytest.mark.functional
class TestListErrorsAreClean:
    """Every failure mode is a clean, actionable error -- never a traceback."""

    def test_missing_kanon(self, tmp_path: pathlib.Path) -> None:
        """Running with no .kanon anywhere is a clean error, exit 1."""
        result = run_kanon("list", cwd=tmp_path, extra_env=_ENV)
        assert result.returncode == 1
        assert result.stderr.startswith("ERROR:")
        assert "Traceback" not in result.stderr

    def test_bad_status_value(self, project: pathlib.Path) -> None:
        """An invalid --status value is an argparse usage error (exit 2), no traceback."""
        result = run_kanon("list", "--status", "bogus", cwd=project, extra_env=_ENV)
        assert result.returncode == 2
        assert "invalid choice" in result.stderr
        assert "Traceback" not in result.stderr

    def test_bad_format_value(self, project: pathlib.Path) -> None:
        """An invalid --format value is an argparse usage error (exit 2), no traceback."""
        result = run_kanon("list", "--format", "yaml", cwd=project, extra_env=_ENV)
        assert result.returncode == 2
        assert "invalid choice" in result.stderr
        assert "Traceback" not in result.stderr

    def test_malformed_lock(self, tmp_path: pathlib.Path) -> None:
        """A malformed lock is a single-prefixed clean error, no traceback."""
        _write_kanon(tmp_path, [("foo", "https://github.com/acme/foo", "1.0.0", "foo")])
        (tmp_path / ".kanon.lock").write_text("not = valid toml [[[\n")
        result = run_kanon("list", cwd=tmp_path, extra_env=_ENV)
        assert result.returncode == 1
        assert result.stderr.startswith("ERROR:")
        assert "ERROR: ERROR:" not in result.stderr
        assert "Traceback" not in result.stderr

    def test_bad_env_format(self, project: pathlib.Path) -> None:
        """An unrecognised KANON_LIST_OUTPUT_FORMAT env value is a clean error, no traceback."""
        result = run_kanon("list", cwd=project, extra_env={**_ENV, "KANON_LIST_OUTPUT_FORMAT": "xml"})
        assert result.returncode == 1
        assert "KANON_LIST_OUTPUT_FORMAT" in result.stderr
        assert "Traceback" not in result.stderr
