"""Unit tests for the ``kanon list`` command (in-process ``run()``).

Exercises the declared-vs-installed reconciliation rendering across every flag
combination (default, --declared, --status, --tree, --format json), the graceful
empty and not-yet-installed states, and the clean-error paths (missing .kanon,
malformed lock, unrecognised env format, missing explicit lock) -- all without a
subprocess, by constructing an argparse.Namespace and calling ``list.run``
directly. Also asserts no path emits a Python traceback.
"""

from __future__ import annotations

import argparse
import json
import pathlib

import pytest

from kanon_cli import constants
from kanon_cli.cli import build_parser
from kanon_cli.commands import list as list_cmd
from kanon_cli.core.lockfile import (
    ContentPinEntry,
    Lockfile,
    ProjectEntry,
    SourceEntry,
    write_lockfile,
)
from kanon_cli.core.url import canonicalize_repo_url


def _write_kanon(directory: pathlib.Path, sources: list[tuple[str, str, str, str]]) -> pathlib.Path:
    """Write a ``.kanon`` declaring ``(alias, url, ref, name)`` sources; return its path."""
    lines = ["GITBASE=https://github.com/acme\n"]
    for alias, url, ref, name in sources:
        lines.append(f"KANON_SOURCE_{alias}_URL={url}\n")
        lines.append(f"KANON_SOURCE_{alias}_REF={ref}\n")
        lines.append(f"KANON_SOURCE_{alias}_PATH=vendor/{alias}\n")
        lines.append(f"KANON_SOURCE_{alias}_NAME={name}\n")
    path = directory / ".kanon"
    path.write_text("".join(lines))
    return path


def _write_lock(directory: pathlib.Path, entries: list[dict]) -> pathlib.Path:
    """Write a ``.kanon.lock`` from a list of source-entry spec dicts; return its path."""
    sources = []
    for entry in entries:
        projects = [
            ProjectEntry(
                name=project["name"],
                url=project["url"],
                canonical_url=canonicalize_repo_url(project["url"]),
                ref_spec=project.get("ref_spec", "*"),
                resolved_ref=project.get("resolved_ref", "refs/heads/main"),
                resolved_sha=project.get("sha", "b" * 40),
            )
            for project in entry.get("projects", [])
        ]
        pins = [
            ContentPinEntry(name=pin["name"], path=pin.get("path", "p"), resolved_sha=pin["sha"])
            for pin in entry.get("pins", [])
        ]
        sources.append(
            SourceEntry(
                alias=entry["alias"],
                name=entry.get("name", entry["alias"]),
                url=entry.get("url", f"https://github.com/acme/{entry['alias']}"),
                ref_spec=entry["ref"],
                resolved_ref=entry.get("resolved_ref", f"refs/tags/{entry['ref']}"),
                resolved_sha=entry.get("sha", "a" * 40),
                path=f"vendor/{entry['alias']}",
                projects=projects,
                content_pins=pins,
            )
        )
    lockfile = Lockfile(
        schema_version=5,
        generated_at="t",
        generator="g",
        kanon_hash="sha256:" + "0" * 64,
        sources=sources,
    )
    path = directory / ".kanon.lock"
    write_lockfile(lockfile, path)
    return path


def _args(
    kanon_file: pathlib.Path | None = None,
    lock_file: pathlib.Path | None = None,
    declared: bool = False,
    tree: bool = False,
    status: str | None = None,
    fmt: str = "table",
) -> argparse.Namespace:
    """Build a parsed-namespace stand-in for ``list.run``."""
    return argparse.Namespace(
        kanon_file=(str(kanon_file) if kanon_file else None),
        lock_file=(str(lock_file) if lock_file else None),
        declared=declared,
        tree=tree,
        status=status,
        format=fmt,
    )


@pytest.fixture(autouse=True)
def _clean_list_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure list-relevant env overrides do not leak into the in-process handler."""
    for key in ("KANON_LOCK_FILE", "KANON_KANON_FILE", constants.KANON_LIST_OUTPUT_FORMAT):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def mixed_project(tmp_path: pathlib.Path) -> pathlib.Path:
    """Project where foo=installed, bar=not-installed, baz=orphan."""
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


@pytest.mark.unit
class TestListRegistration:
    """The list subcommand is wired into the top-level parser."""

    def test_list_is_registered(self) -> None:
        """build_parser() exposes a 'list' subcommand whose handler is list.run."""
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"
        assert args.func is list_cmd.run


@pytest.mark.unit
class TestListTable:
    """Default table rendering and the reconciliation status tags."""

    def test_default_reconciled(self, mixed_project: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """The default view tags foo installed, bar not-installed, baz orphan."""
        rc = list_cmd.run(_args(kanon_file=mixed_project / ".kanon"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "SOURCE" in out and "STATUS" in out
        lines = {line.split("|")[0].strip(): line for line in out.splitlines() if "|" in line}
        assert constants.KANON_LIST_STATUS_INSTALLED in lines["foo"]
        assert constants.KANON_LIST_STATUS_NOT_INSTALLED in lines["bar"]
        assert constants.KANON_LIST_STATUS_ORPHAN in lines["baz"]

    def test_rows_sorted_by_alias(self, mixed_project: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Rows are alphabetical by alias regardless of status grouping."""
        list_cmd.run(_args(kanon_file=mixed_project / ".kanon"))
        out = capsys.readouterr().out
        data_aliases = [line.split("|")[0].strip() for line in out.splitlines()[2:] if "|" in line]
        assert data_aliases == sorted(data_aliases)

    def test_declared_filter_drops_orphan(self, mixed_project: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """--declared shows declared sources only (no orphan baz)."""
        rc = list_cmd.run(_args(kanon_file=mixed_project / ".kanon", declared=True))
        out = capsys.readouterr().out
        assert rc == 0
        assert "foo" in out and "bar" in out
        assert "baz" not in out

    @pytest.mark.parametrize(
        "status,present,absent",
        [
            (constants.KANON_LIST_STATUS_INSTALLED, "foo", ("bar", "baz")),
            (constants.KANON_LIST_STATUS_NOT_INSTALLED, "bar", ("foo", "baz")),
            (constants.KANON_LIST_STATUS_ORPHAN, "baz", ("foo", "bar")),
        ],
    )
    def test_status_filter(
        self,
        mixed_project: pathlib.Path,
        capsys: pytest.CaptureFixture,
        status: str,
        present: str,
        absent: tuple[str, ...],
    ) -> None:
        """--status filters the inventory to a single tag."""
        rc = list_cmd.run(_args(kanon_file=mixed_project / ".kanon", status=status))
        out = capsys.readouterr().out
        assert rc == 0
        data_aliases = [line.split("|")[0].strip() for line in out.splitlines()[2:] if "|" in line]
        assert present in data_aliases
        for alias in absent:
            assert alias not in data_aliases

    def test_tree_shows_transitive(self, mixed_project: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """--tree expands installed/orphan sources to their transitive packages."""
        rc = list_cmd.run(_args(kanon_file=mixed_project / ".kanon", tree=True))
        out = capsys.readouterr().out
        assert rc == 0
        assert "libcore" in out
        assert "baz-pin" in out


@pytest.mark.unit
class TestListJson:
    """JSON output is well-formed and carries the correct statuses."""

    def test_format_json_statuses(self, mixed_project: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """--format json emits a sources array with per-alias status tags."""
        rc = list_cmd.run(_args(kanon_file=mixed_project / ".kanon", fmt=constants.KANON_LIST_OUTPUT_FORMAT_JSON))
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        by_alias = {source["alias"]: source for source in payload["sources"]}
        assert by_alias["foo"]["status"] == constants.KANON_LIST_STATUS_INSTALLED
        assert by_alias["bar"]["status"] == constants.KANON_LIST_STATUS_NOT_INSTALLED
        assert by_alias["baz"]["status"] == constants.KANON_LIST_STATUS_ORPHAN
        assert by_alias["foo"]["scope"] == constants.KANON_LIST_SCOPE_DIRECT
        assert "projects" not in by_alias["foo"]

    def test_json_tree_includes_projects(self, mixed_project: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """--tree --format json nests a transitive projects list per source."""
        rc = list_cmd.run(
            _args(kanon_file=mixed_project / ".kanon", tree=True, fmt=constants.KANON_LIST_OUTPUT_FORMAT_JSON)
        )
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        foo = next(source for source in payload["sources"] if source["alias"] == "foo")
        assert [project["name"] for project in foo["projects"]] == ["libcore"]
        assert foo["projects"][0]["scope"] == constants.KANON_LIST_SCOPE_TRANSITIVE

    def test_declared_json_drops_orphan(self, mixed_project: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """--declared --format json omits orphan sources."""
        list_cmd.run(
            _args(kanon_file=mixed_project / ".kanon", declared=True, fmt=constants.KANON_LIST_OUTPUT_FORMAT_JSON)
        )
        payload = json.loads(capsys.readouterr().out)
        assert {source["alias"] for source in payload["sources"]} == {"foo", "bar"}


@pytest.mark.unit
class TestListEmptyAndNotInstalled:
    """Graceful handling of the empty and not-yet-installed states."""

    def test_no_lockfile_all_not_installed(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """With a .kanon but no lock, every source is not-installed (exit 0 + note)."""
        _write_kanon(tmp_path, [("foo", "https://github.com/acme/foo", "1.0.0", "foo")])
        rc = list_cmd.run(_args(kanon_file=tmp_path / ".kanon"))
        captured = capsys.readouterr()
        assert rc == 0
        assert constants.KANON_LIST_STATUS_NOT_INSTALLED in captured.out
        assert constants.KANON_LIST_NO_LOCKFILE_NOTE in captured.err

    def test_no_lockfile_json_empty_resolved_fields(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Not-installed sources have empty resolved fields in JSON."""
        _write_kanon(tmp_path, [("foo", "https://github.com/acme/foo", "1.0.0", "foo")])
        list_cmd.run(_args(kanon_file=tmp_path / ".kanon", fmt=constants.KANON_LIST_OUTPUT_FORMAT_JSON))
        payload = json.loads(capsys.readouterr().out)
        foo = payload["sources"][0]
        assert foo["status"] == constants.KANON_LIST_STATUS_NOT_INSTALLED
        assert foo["resolved_ref"] == ""
        assert foo["resolved_sha"] == ""
        assert foo["ref_spec"] == "1.0.0"

    def test_empty_kanon_note(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """A .kanon with zero sources prints the no-dependencies note (exit 0)."""
        (tmp_path / ".kanon").write_text("GITBASE=https://github.com/acme\n")
        rc = list_cmd.run(_args(kanon_file=tmp_path / ".kanon"))
        captured = capsys.readouterr()
        assert rc == 0
        assert constants.KANON_LIST_NO_SOURCES_NOTE in captured.err

    def test_empty_kanon_with_orphan_lock(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """A .kanon with zero sources but a populated lock shows all-orphan."""
        (tmp_path / ".kanon").write_text("GITBASE=https://github.com/acme\n")
        _write_lock(tmp_path, [{"alias": "ghost", "ref": "1.0.0"}])
        rc = list_cmd.run(_args(kanon_file=tmp_path / ".kanon"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "ghost" in out
        assert constants.KANON_LIST_STATUS_ORPHAN in out


@pytest.mark.unit
class TestListErrors:
    """Every failure path is a clean, actionable error -- never a traceback."""

    def test_missing_kanon(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """An explicit missing .kanon path yields a single-line ERROR and exit 1."""
        rc = list_cmd.run(_args(kanon_file=tmp_path / "nope" / ".kanon"))
        err = capsys.readouterr().err
        assert rc == 1
        assert err.startswith("ERROR:")
        assert "Traceback" not in err

    def test_malformed_lock_single_prefix(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """A malformed lock yields exactly one ERROR: prefix (no ERROR: ERROR:)."""
        _write_kanon(tmp_path, [("foo", "https://github.com/acme/foo", "1.0.0", "foo")])
        (tmp_path / ".kanon.lock").write_text("not valid = toml [[[\n")
        rc = list_cmd.run(_args(kanon_file=tmp_path / ".kanon"))
        err = capsys.readouterr().err
        assert rc == 1
        assert err.startswith("ERROR:")
        assert "ERROR: ERROR:" not in err
        assert "Traceback" not in err

    def test_bad_env_format(self, mixed_project: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """An unrecognised format value is rejected with a clean error."""
        rc = list_cmd.run(_args(kanon_file=mixed_project / ".kanon", fmt="xml"))
        err = capsys.readouterr().err
        assert rc == 1
        assert constants.KANON_LIST_OUTPUT_FORMAT in err
        assert "Traceback" not in err

    def test_explicit_missing_lock(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """An explicit --lock-file that does not exist is a clean error."""
        _write_kanon(tmp_path, [("foo", "https://github.com/acme/foo", "1.0.0", "foo")])
        rc = list_cmd.run(_args(kanon_file=tmp_path / ".kanon", lock_file=tmp_path / "absent.lock"))
        err = capsys.readouterr().err
        assert rc == 1
        assert "lock file not found" in err
        assert "Traceback" not in err

    def test_malformed_kanon(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """A .kanon that exists but fails to parse yields a clean error, not a traceback."""
        (tmp_path / ".kanon").write_text("KANON_SOURCES=foo\n")
        rc = list_cmd.run(_args(kanon_file=tmp_path / ".kanon"))
        err = capsys.readouterr().err
        assert rc == 1
        assert err.startswith("ERROR:")
        assert "Traceback" not in err

    def test_validation_error_not_double_prefixed(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """A lock that parses but fails validation (self-prefixed 'ERROR:') stays single-prefixed."""
        _write_kanon(tmp_path, [("foo", "https://github.com/acme/foo", "1.0.0", "foo")])
        (tmp_path / ".kanon.lock").write_text(
            'schema_version = 5\ngenerated_at = "t"\ngenerator = "g"\n'
            'kanon_hash = "sha256:' + "0" * 64 + '"\n'
            "[[sources]]\n"
            'alias = "foo"\nname = "foo"\nurl = "https://github.com/acme/foo"\n'
            'ref_spec = "1.0.0"\nresolved_ref = "refs/tags/1.0.0"\n'
            'resolved_sha = "not-a-valid-sha"\npath = "vendor/foo"\n'
        )
        rc = list_cmd.run(_args(kanon_file=tmp_path / ".kanon"))
        err = capsys.readouterr().err
        assert rc == 1
        assert err.startswith("ERROR:")
        assert "ERROR: ERROR:" not in err
        assert "Traceback" not in err


@pytest.mark.unit
class TestListDiscoveryAndFilters:
    """Auto-discovery of .kanon and empty-filter handling."""

    def test_walk_up_discovery(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """With no --kanon-file, the command walks up from cwd to find .kanon."""
        _write_kanon(tmp_path, [("foo", "https://github.com/acme/foo", "1.0.0", "foo")])
        subdir = tmp_path / "a" / "b"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        rc = list_cmd.run(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "foo" in out

    def test_status_filter_empty_result(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """Filtering to a status with no members yields no rows and exit 0."""
        _write_kanon(tmp_path, [("foo", "https://github.com/acme/foo", "1.0.0", "foo")])
        rc = list_cmd.run(_args(kanon_file=tmp_path / ".kanon", status=constants.KANON_LIST_STATUS_INSTALLED))
        out = capsys.readouterr().out
        assert rc == 0
        assert "foo" not in out


@pytest.mark.unit
class TestListHelpers:
    """Direct coverage of the pure rendering helpers, including edge branches."""

    def test_emit_error_single_prefix(self, capsys: pytest.CaptureFixture) -> None:
        """_emit_error normalises any leading ERROR:/Error: to exactly one prefix."""
        list_cmd._emit_error("plain message")
        list_cmd._emit_error("ERROR: already prefixed")
        list_cmd._emit_error("Error: mixed case")
        lines = capsys.readouterr().err.splitlines()
        assert lines == ["ERROR: plain message", "ERROR: already prefixed", "ERROR: mixed case"]

    def test_clean_ref_strips_and_passes_through(self) -> None:
        """_clean_ref strips known refs/ prefixes and leaves plain refs untouched."""
        assert list_cmd._clean_ref("refs/tags/1.0.0") == "1.0.0"
        assert list_cmd._clean_ref("refs/heads/main") == "main"
        assert list_cmd._clean_ref("main") == "main"

    def test_project_detail_with_and_without_sha(self) -> None:
        """_project_detail appends a short SHA when present, omits it otherwise."""
        with_sha = list_cmd._project_detail({"resolved_ref": "refs/heads/main", "resolved_sha": "a" * 40})
        without_sha = list_cmd._project_detail({"resolved_ref": "refs/heads/main", "resolved_sha": ""})
        assert with_sha == "main (aaaaaaaaaaaa)"
        assert without_sha == "main"

    def test_entry_projects_prefers_projects_then_pins(self) -> None:
        """_entry_projects uses projects when present, else falls back to content_pins."""
        from kanon_cli.core.lockfile import ContentPinEntry as _Pin
        from kanon_cli.core.lockfile import ProjectEntry as _Proj
        from kanon_cli.core.lockfile import SourceEntry as _Src

        with_projects = _Src(
            alias="s",
            name="s",
            url="https://github.com/acme/s",
            ref_spec="1.0.0",
            resolved_ref="refs/tags/1.0.0",
            resolved_sha="a" * 40,
            path="vendor/s",
            projects=[
                _Proj(
                    name="p",
                    url="https://github.com/acme/p",
                    canonical_url=canonicalize_repo_url("https://github.com/acme/p"),
                    ref_spec="*",
                    resolved_ref="refs/heads/main",
                    resolved_sha="b" * 40,
                )
            ],
            content_pins=[_Pin(name="pin", path="p", resolved_sha="c" * 40)],
        )
        only_pins = _Src(
            alias="s",
            name="s",
            url="https://github.com/acme/s",
            ref_spec="1.0.0",
            resolved_ref="refs/tags/1.0.0",
            resolved_sha="a" * 40,
            path="vendor/s",
            content_pins=[_Pin(name="pin", path="p", resolved_sha="c" * 40)],
        )
        empty = _Src(
            alias="s",
            name="s",
            url="https://github.com/acme/s",
            ref_spec="1.0.0",
            resolved_ref="refs/tags/1.0.0",
            resolved_sha="a" * 40,
            path="vendor/s",
        )
        assert [project["name"] for project in list_cmd._entry_projects(with_projects)] == ["p"]
        pin_projects = list_cmd._entry_projects(only_pins)
        assert [project["name"] for project in pin_projects] == ["pin"]
        assert pin_projects[0]["url"] == ""
        assert list_cmd._entry_projects(empty) == []
