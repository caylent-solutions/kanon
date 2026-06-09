"""Unit tests for kanon_cli.core.manifest.

Tests the public API of manifest.py:
  - walk_includes_collecting_remotes: depth-first <include> walker that
    accumulates <remote name="..." fetch="..."> mappings.
  - collect_remote_url_findings: end-to-end check producing RawFinding
    namedtuples covering R001, R002, and R003 codes.

These tests ensure 100% branch/line coverage on the new module per AC-FINAL-014.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from kanon_cli.core.manifest import (
    RawFinding,
    collect_remote_url_findings,
    walk_includes_collecting_remotes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_xml(path: pathlib.Path, content: str) -> None:
    """Write content to path, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _simple_manifest(remote_name: str, fetch_url: str) -> str:
    """Return a minimal manifest XML string with one <remote> and one <project>."""
    return textwrap.dedent(f"""\
        <?xml version="1.0"?>
        <manifest>
          <remote name="{remote_name}" fetch="{fetch_url}" />
          <project name="proj" remote="{remote_name}" path="src/proj" />
          <catalog-metadata>
            <name>proj</name>
            <display-name>Proj</display-name>
            <description>d</description>
            <version>1.0.0</version>
          </catalog-metadata>
        </manifest>
    """)


def _manifest_no_remotes() -> str:
    """Return a minimal manifest XML with no <remote> elements."""
    return textwrap.dedent("""\
        <?xml version="1.0"?>
        <manifest>
          <project name="proj" remote="origin" path="src/proj" />
          <catalog-metadata>
            <name>proj</name>
            <display-name>Proj</display-name>
            <description>d</description>
            <version>1.0.0</version>
          </catalog-metadata>
        </manifest>
    """)


# ---------------------------------------------------------------------------
# walk_includes_collecting_remotes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWalkIncludesCollectingRemotes:
    """Tests for walk_includes_collecting_remotes."""

    def test_single_file_no_remotes(self, tmp_path: pathlib.Path) -> None:
        """A file with no <remote> elements returns an empty dict."""
        xml = tmp_path / "manifest.xml"
        _write_xml(xml, '<?xml version="1.0"?><manifest></manifest>')
        result = walk_includes_collecting_remotes(xml, tmp_path)
        assert result == {}

    def test_single_file_one_remote(self, tmp_path: pathlib.Path) -> None:
        """A file with one <remote> returns a one-entry dict."""
        xml = tmp_path / "manifest.xml"
        _write_xml(xml, _simple_manifest("origin", "https://github.com/org"))
        result = walk_includes_collecting_remotes(xml, tmp_path)
        assert result == {"origin": "https://github.com/org"}

    def test_single_file_multiple_remotes(self, tmp_path: pathlib.Path) -> None:
        """A file with multiple <remote> elements returns all of them."""
        content = textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote name="origin" fetch="https://github.com/org" />
              <remote name="backup" fetch="https://backup.example.com/org" />
            </manifest>
        """)
        xml = tmp_path / "manifest.xml"
        _write_xml(xml, content)
        result = walk_includes_collecting_remotes(xml, tmp_path)
        assert result == {
            "origin": "https://github.com/org",
            "backup": "https://backup.example.com/org",
        }

    def test_included_file_remote_is_found(self, tmp_path: pathlib.Path) -> None:
        """A <remote> defined only in an included file is collected."""
        # Helper defines the remote.
        helper = tmp_path / "helpers.xml"
        _write_xml(
            helper,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote name="shared" fetch="https://shared.example.com" />
            </manifest>
        """),
        )
        # Root only has the include.
        root = tmp_path / "root.xml"
        _write_xml(
            root,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <include name="helpers.xml" />
            </manifest>
        """),
        )
        result = walk_includes_collecting_remotes(root, tmp_path)
        assert result == {"shared": "https://shared.example.com"}

    def test_diamond_include_visits_once(self, tmp_path: pathlib.Path) -> None:
        """A file included via two paths is visited only once (diamond deduplication)."""
        # common.xml defines one remote.
        common = tmp_path / "common.xml"
        _write_xml(
            common,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote name="common" fetch="https://common.example.com" />
            </manifest>
        """),
        )
        # left.xml includes common.
        left = tmp_path / "left.xml"
        _write_xml(
            left,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <include name="common.xml" />
            </manifest>
        """),
        )
        # right.xml also includes common.
        right = tmp_path / "right.xml"
        _write_xml(
            right,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <include name="common.xml" />
            </manifest>
        """),
        )
        # root includes both left and right.
        root = tmp_path / "root.xml"
        _write_xml(
            root,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <include name="left.xml" />
              <include name="right.xml" />
            </manifest>
        """),
        )
        result = walk_includes_collecting_remotes(root, tmp_path)
        # "common" appears exactly once even though it is reachable via two paths.
        assert result == {"common": "https://common.example.com"}

    def test_first_definition_wins_on_duplicate_name(self, tmp_path: pathlib.Path) -> None:
        """When the same remote name appears in two files, the first-visited definition wins."""
        helper = tmp_path / "helper.xml"
        _write_xml(
            helper,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote name="origin" fetch="https://second.example.com" />
            </manifest>
        """),
        )
        root = tmp_path / "root.xml"
        _write_xml(
            root,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote name="origin" fetch="https://first.example.com" />
              <include name="helper.xml" />
            </manifest>
        """),
        )
        result = walk_includes_collecting_remotes(root, tmp_path)
        assert result == {"origin": "https://first.example.com"}

    def test_malformed_include_name_attribute_is_skipped(self, tmp_path: pathlib.Path) -> None:
        """An <include> with no name attribute is skipped silently."""
        root = tmp_path / "root.xml"
        _write_xml(
            root,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote name="origin" fetch="https://github.com/org" />
              <include />
            </manifest>
        """),
        )
        result = walk_includes_collecting_remotes(root, tmp_path)
        assert result == {"origin": "https://github.com/org"}

    def test_remote_without_fetch_is_ignored(self, tmp_path: pathlib.Path) -> None:
        """A <remote> element missing the fetch attribute is not added to the map."""
        root = tmp_path / "root.xml"
        _write_xml(
            root,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote name="no-fetch" />
              <remote name="has-fetch" fetch="https://github.com/org" />
            </manifest>
        """),
        )
        result = walk_includes_collecting_remotes(root, tmp_path)
        assert "no-fetch" not in result
        assert result.get("has-fetch") == "https://github.com/org"

    def test_remote_without_name_is_ignored(self, tmp_path: pathlib.Path) -> None:
        """A <remote> element missing the name attribute is not added to the map."""
        root = tmp_path / "root.xml"
        _write_xml(
            root,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote fetch="https://nameless.example.com" />
              <remote name="named" fetch="https://named.example.com" />
            </manifest>
        """),
        )
        result = walk_includes_collecting_remotes(root, tmp_path)
        assert result == {"named": "https://named.example.com"}


# ---------------------------------------------------------------------------
# collect_remote_url_findings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCollectRemoteUrlFindings:
    """Tests for collect_remote_url_findings covering all RawFinding codes."""

    def test_returns_raw_finding_namedtuple(self, tmp_path: pathlib.Path) -> None:
        """Return value items are RawFinding namedtuples with expected attributes."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _manifest_no_remotes())
        result = collect_remote_url_findings(tmp_path, env={})
        # The file has a project referencing "origin" with no <remote name="origin">.
        assert len(result) == 1
        finding = result[0]
        assert isinstance(finding, RawFinding)
        assert finding.kind == "error"
        assert finding.code == "R001"
        assert hasattr(finding, "message")
        assert hasattr(finding, "remediation")

    def test_none_env_uses_empty_dict(self, tmp_path: pathlib.Path) -> None:
        """Passing env=None behaves the same as env={} for KANON_ALLOW_INSECURE_REMOTES."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("local", "file:///tmp/test"))
        # env=None means no override; file:// should be rejected.
        # But env=None uses {} not os.environ, so no KANON_ALLOW_INSECURE_REMOTES.
        result = collect_remote_url_findings(tmp_path, env=None)
        error_codes = [f.code for f in result if f.kind == "error"]
        assert "R002" in error_codes, f"Expected R002 with env=None, got codes: {error_codes}"

    def test_empty_repo_specs_returns_no_findings(self, tmp_path: pathlib.Path) -> None:
        """No marketplace XML files => no findings."""
        (tmp_path / "repo-specs").mkdir()
        result = collect_remote_url_findings(tmp_path, env={})
        assert result == []

    def test_malformed_xml_silently_skipped(self, tmp_path: pathlib.Path) -> None:
        """A malformed marketplace XML file produces no findings (skipped silently)."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        bad = repo_specs / "bad-marketplace.xml"
        bad.write_text("<unclosed", encoding="utf-8")
        result = collect_remote_url_findings(tmp_path, env={})
        assert result == []

    def test_project_with_no_remote_attr_skipped(self, tmp_path: pathlib.Path) -> None:
        """A <project> with no remote attribute produces no R001 finding."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(
            xml,
            textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <project name="proj" path="src/proj" />
            </manifest>
        """),
        )
        result = collect_remote_url_findings(tmp_path, env={})
        assert result == []

    def test_r001_finding_names_project_and_remote(self, tmp_path: pathlib.Path) -> None:
        """R001 message names the project name and unresolved remote attribute."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _manifest_no_remotes())
        result = collect_remote_url_findings(tmp_path, env={})
        assert len(result) == 1
        msg = result[0].message
        assert "origin" in msg, f"Expected 'origin' in R001 message, got: {msg}"

    def test_r002_finding_names_url(self, tmp_path: pathlib.Path) -> None:
        """R002 message names the offending fetch URL."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("local", "file:///srv/git"))
        result = collect_remote_url_findings(tmp_path, env={})
        assert len(result) == 1
        assert "file:///srv/git" in result[0].message

    def test_r003_finding_for_query_string(self, tmp_path: pathlib.Path) -> None:
        """R003 is emitted for a fetch URL containing a query string."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("cdn", "https://example.com/repos?token=abc"))
        result = collect_remote_url_findings(tmp_path, env={})
        assert len(result) == 1
        assert result[0].code == "R003"

    def test_r003_finding_for_fragment(self, tmp_path: pathlib.Path) -> None:
        """R003 is emitted for a fetch URL containing a fragment."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("cdn", "https://example.com/repos#section"))
        result = collect_remote_url_findings(tmp_path, env={})
        assert len(result) == 1
        assert result[0].code == "R003"

    def test_r003_not_suppressed_by_allow_insecure(self, tmp_path: pathlib.Path) -> None:
        """R003 is NOT suppressed by KANON_ALLOW_INSECURE_REMOTES=1."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("cdn", "https://example.com/repos?token=abc"))
        result = collect_remote_url_findings(tmp_path, env={"KANON_ALLOW_INSECURE_REMOTES": "1"})
        assert len(result) == 1
        assert result[0].code == "R003", "R003 (query string) must not be suppressed by KANON_ALLOW_INSECURE_REMOTES"

    def test_allow_insecure_suppresses_r002_only(self, tmp_path: pathlib.Path) -> None:
        """KANON_ALLOW_INSECURE_REMOTES=1 suppresses R002 but not R001 or R003."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        # file:// -> normally R002.
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("local", "file:///tmp/repos"))
        result = collect_remote_url_findings(tmp_path, env={"KANON_ALLOW_INSECURE_REMOTES": "1"})
        assert result == [], f"Expected zero findings with KANON_ALLOW_INSECURE_REMOTES=1, got: {result}"

    def test_https_url_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """An HTTPS fetch URL produces zero findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("origin", "https://github.com/org"))
        result = collect_remote_url_findings(tmp_path, env={})
        assert result == []

    def test_ssh_git_at_url_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """An SSH git@ fetch URL produces zero findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("origin", "git@github.com:org"))
        result = collect_remote_url_findings(tmp_path, env={})
        assert result == []

    def test_ssh_protocol_url_produces_no_findings(self, tmp_path: pathlib.Path) -> None:
        """An SSH ssh:// fetch URL produces zero findings."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("origin", "ssh://git@github.com/org"))
        result = collect_remote_url_findings(tmp_path, env={})
        assert result == []


# ---------------------------------------------------------------------------
# TestRemoteUrlPlaceholder -- AC-TEST-001
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "fetch_url,env,expect_r002,expect_info_or_warn",
    [
        # Unset variable -- no R002, an INFO/WARN finding instead.
        ("${GITBASE}", {}, False, True),
        # Variable set to HTTPS scheme -- no R002, no INFO/WARN (resolved OK).
        ("${GITBASE}", {"GITBASE": "https://github.com/org"}, False, False),
        # Variable set to non-HTTPS scheme -- R002 on resolved scheme.
        ("${GITBASE}", {"GITBASE": "http://github.com/org"}, True, False),
        # Literal http:// -- always R002.
        ("http://github.com/org", {}, True, False),
        # Mixed: literal insecure scheme with placeholder host -- R002 from literal scheme.
        ("http://${HOST}/org", {}, True, False),
    ],
)
class TestRemoteUrlPlaceholder:
    """AC-TEST-001: parametrised placeholder expansion tests for R002.

    Cases:
    - ${VAR} with VAR unset => no R002, one INFO/WARN finding (templated token).
    - ${VAR} with VAR=https://... => no R002, zero findings.
    - ${VAR} with VAR=http://... => R002 on resolved non-HTTPS scheme.
    - literal http:// => R002 (no expansion needed).
    - http://${HOST} => R002 from literal insecure scheme prefix.
    """

    def test_r002_and_info_warn_presence(
        self,
        tmp_path: pathlib.Path,
        fetch_url: str,
        env: dict[str, str],
        expect_r002: bool,
        expect_info_or_warn: bool,
    ) -> None:
        """Parametrised: check R002 and INFO/WARN presence per scenario."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        xml = repo_specs / "tool-marketplace.xml"
        _write_xml(xml, _simple_manifest("origin", fetch_url))

        result = collect_remote_url_findings(tmp_path, env=env)

        r002_findings = [f for f in result if f.code == "R002"]
        info_warn_findings = [f for f in result if f.kind in ("info", "warn")]

        if expect_r002:
            assert r002_findings, (
                f"Expected an R002 finding for fetch_url={fetch_url!r} env={env!r}, but got findings: {result}"
            )
        else:
            assert not r002_findings, (
                f"Expected NO R002 finding for fetch_url={fetch_url!r} env={env!r}, but got: {r002_findings}"
            )

        if expect_info_or_warn:
            assert info_warn_findings, (
                f"Expected an INFO/WARN finding for fetch_url={fetch_url!r} env={env!r}, but got findings: {result}"
            )
        else:
            assert not info_warn_findings, (
                f"Expected NO INFO/WARN finding for fetch_url={fetch_url!r} env={env!r}, but got: {info_warn_findings}"
            )
