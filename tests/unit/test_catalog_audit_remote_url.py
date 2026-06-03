"""Unit tests for kanon catalog audit --check remote-url (soft-spot rule 4).

Covers _check_remote_url via the AUDIT_CHECK_REGISTRY and directly. Tests
parametrize across:
  - Resolvable HTTPS remote: zero findings.
  - Resolvable SSH remote (git@ and ssh://): zero findings.
  - Unresolvable <remote name="X"> anywhere in the include chain: one R001 ERROR.
  - file:// URL without KANON_ALLOW_INSECURE_REMOTES: one R002 ERROR.
  - file:// URL with KANON_ALLOW_INSECURE_REMOTES=1: zero findings.
  - URL with query string: one R003 ERROR.
  - URL with fragment: one R003 ERROR.
  - Include-chain resolution through a parent XML: zero findings when remote
    defined in parent, one R001 ERROR when chain dead-ends.

AC-TEST-001: Parametrized unit tests covering every scenario above.
AC-FUNC-001 through AC-FUNC-009.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from kanon_cli.commands.catalog import AUDIT_CHECK_REGISTRY, AuditFinding
from kanon_cli.core.manifest import RawFinding, collect_remote_url_findings


# ---------------------------------------------------------------------------
# Fixture-writing helpers
# ---------------------------------------------------------------------------


def _make_repo_specs(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create and return the repo-specs/ directory under tmp_path."""
    repo_specs = tmp_path / "repo-specs"
    repo_specs.mkdir(parents=True, exist_ok=True)
    return repo_specs


def _write_marketplace_xml(
    repo_specs: pathlib.Path,
    filename: str,
    content: str,
) -> pathlib.Path:
    """Write content to filename under repo_specs and return the path."""
    xml_file = repo_specs / filename
    xml_file.write_text(content, encoding="utf-8")
    return xml_file


def _marketplace_with_remote(
    remote_name: str,
    fetch_url: str,
    entry_name: str = "test-tool",
) -> str:
    """Build a minimal *-marketplace.xml that defines one <remote> and one <project>."""
    return textwrap.dedent(f"""\
        <?xml version="1.0"?>
        <manifest>
          <catalog-metadata>
            <name>{entry_name}</name>
            <display-name>Test Tool</display-name>
            <description>A test tool.</description>
            <version>1.0.0</version>
          </catalog-metadata>
          <remote name="{remote_name}" fetch="{fetch_url}" />
          <project name="proj" remote="{remote_name}" path="src/proj" />
        </manifest>
    """)


def _marketplace_with_unresolvable_remote(
    project_remote: str = "missing",
    entry_name: str = "test-tool",
) -> str:
    """Build a *-marketplace.xml with a <project> that references a non-existent remote."""
    return textwrap.dedent(f"""\
        <?xml version="1.0"?>
        <manifest>
          <catalog-metadata>
            <name>{entry_name}</name>
            <display-name>Test Tool</display-name>
            <description>A test tool.</description>
            <version>1.0.0</version>
          </catalog-metadata>
          <project name="proj" remote="{project_remote}" path="src/proj" />
        </manifest>
    """)


def _marketplace_no_projects(entry_name: str = "test-tool") -> str:
    """Build a minimal *-marketplace.xml with no <project> elements."""
    return textwrap.dedent(f"""\
        <?xml version="1.0"?>
        <manifest>
          <catalog-metadata>
            <name>{entry_name}</name>
            <display-name>Test Tool</display-name>
            <description>A test tool.</description>
            <version>1.0.0</version>
          </catalog-metadata>
        </manifest>
    """)


# ---------------------------------------------------------------------------
# Helper to call the check function with an injected env
# ---------------------------------------------------------------------------


def _run_check(tmp_path: pathlib.Path, env: dict[str, str] | None = None) -> list[RawFinding]:
    """Call collect_remote_url_findings directly with env injection."""
    return collect_remote_url_findings(tmp_path, env=env or {})


def _run_registered_check(tmp_path: pathlib.Path) -> list[AuditFinding]:
    """Call the check registered under 'remote-url' in AUDIT_CHECK_REGISTRY."""
    check_fn = AUDIT_CHECK_REGISTRY["remote-url"]
    return check_fn(tmp_path)


# ---------------------------------------------------------------------------
# Registry registration (AC-FUNC-007)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoteUrlCheckRegistered:
    """'remote-url' is registered in AUDIT_CHECK_REGISTRY (AC-FUNC-007)."""

    def test_remote_url_key_present(self) -> None:
        assert "remote-url" in AUDIT_CHECK_REGISTRY

    def test_remote_url_value_is_callable(self) -> None:
        assert callable(AUDIT_CHECK_REGISTRY["remote-url"])

    def test_registered_check_returns_audit_findings(self, tmp_path: pathlib.Path) -> None:
        """The registered 'remote-url' check returns AuditFinding objects (AC-FUNC-007)."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("origin", "https://github.com/org"),
        )
        findings = _run_registered_check(tmp_path)
        assert findings == [], f"Expected zero findings from registered check for HTTPS URL, got: {findings}"
        assert isinstance(findings, list)

    def test_registered_check_returns_audit_finding_type(self, tmp_path: pathlib.Path) -> None:
        """The registered check returns AuditFinding instances for errors (AC-FUNC-007)."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_unresolvable_remote("missing"),
        )
        findings = _run_registered_check(tmp_path)
        assert len(findings) == 1
        finding = findings[0]
        assert isinstance(finding, AuditFinding), f"Expected AuditFinding instance, got: {type(finding)}"
        assert finding.code == "R001"


# ---------------------------------------------------------------------------
# Resolvable HTTPS remote: zero findings (AC-FUNC-001)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolvableHttpsRemoteZeroFindings:
    """A <project> whose <remote> fetches via HTTPS produces zero findings (AC-FUNC-001)."""

    @pytest.mark.parametrize(
        "fetch_url",
        [
            "https://github.com/org",
            "https://gitlab.com/org",
            "https://bitbucket.org/org",
        ],
    )
    def test_https_remote_produces_zero_findings(self, tmp_path: pathlib.Path, fetch_url: str) -> None:
        """HTTPS fetch URL produces zero findings."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("origin", fetch_url),
        )
        findings = _run_check(tmp_path)
        assert findings == [], f"Expected zero findings for HTTPS URL {fetch_url!r}, got: {findings}"


# ---------------------------------------------------------------------------
# Resolvable SSH remote: zero findings (AC-FUNC-006)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolvableSshRemoteZeroFindings:
    """A <project> whose <remote> fetches via SSH produces zero findings (AC-FUNC-006)."""

    @pytest.mark.parametrize(
        "fetch_url",
        [
            "git@github.com:org",
            "git@gitlab.com:org",
            "ssh://git@github.com/org",
            "ssh://git@gitlab.com:2222/org",
        ],
    )
    def test_ssh_remote_produces_zero_findings(self, tmp_path: pathlib.Path, fetch_url: str) -> None:
        """SSH fetch URL is treated as HTTPS-equivalent and produces zero findings."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("origin", fetch_url),
        )
        findings = _run_check(tmp_path)
        assert findings == [], f"Expected zero findings for SSH URL {fetch_url!r}, got: {findings}"


# ---------------------------------------------------------------------------
# Unresolvable remote: one R001 ERROR (AC-FUNC-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnresolvableRemoteOneError:
    """A <project remote="X"> with no matching <remote name="X"> produces one R001 ERROR (AC-FUNC-002)."""

    def test_unresolvable_remote_produces_one_error(self, tmp_path: pathlib.Path) -> None:
        """An unresolvable remote produces exactly one R001 ERROR finding."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_unresolvable_remote("missing"),
        )
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, f"Expected exactly one ERROR for unresolvable remote, got: {error_findings}"

    def test_unresolvable_remote_finding_code_is_r001(self, tmp_path: pathlib.Path) -> None:
        """The ERROR finding for an unresolvable remote has code R001."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_unresolvable_remote("missing"),
        )
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1
        assert error_findings[0].code == "R001", f"Expected code R001, got: {error_findings[0].code}"

    def test_unresolvable_remote_names_project_and_remote_attr(self, tmp_path: pathlib.Path) -> None:
        """The R001 finding names the project element and the unresolved remote attribute."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_unresolvable_remote("does-not-exist"),
        )
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1
        msg = error_findings[0].message
        assert "does-not-exist" in msg, f"Expected unresolved remote name in message, got: {msg}"

    def test_unresolvable_remote_remediation_mentions_validate(self, tmp_path: pathlib.Path) -> None:
        """The R001 finding remediation mentions kanon validate marketplace."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_unresolvable_remote("missing"),
        )
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1
        remediation = error_findings[0].remediation
        assert "kanon validate marketplace" in remediation, (
            f"Expected remediation to mention 'kanon validate marketplace', got: {remediation}"
        )

    @pytest.mark.parametrize("remote_attr", ["no-such-remote", "origin", "upstream", "cdn"])
    def test_unresolvable_remote_parametrized(self, tmp_path: pathlib.Path, remote_attr: str) -> None:
        """Parametrized: any unresolvable remote name produces exactly one R001 ERROR."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_unresolvable_remote(remote_attr),
        )
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, f"Expected one R001 ERROR for remote={remote_attr!r}, got: {error_findings}"
        assert error_findings[0].code == "R001"


# ---------------------------------------------------------------------------
# file:// URL without env var: one R002 ERROR (AC-FUNC-003)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInsecureUrlWithoutEnvOneError:
    """A file:// URL produces one R002 ERROR when KANON_ALLOW_INSECURE_REMOTES is unset (AC-FUNC-003)."""

    @pytest.mark.parametrize(
        "fetch_url",
        [
            "file:///tmp/repos",
            "file:///home/user/repos",
            "http://internal.example.com/repos",
        ],
    )
    def test_insecure_url_without_env_produces_one_error(self, tmp_path: pathlib.Path, fetch_url: str) -> None:
        """Insecure URL without KANON_ALLOW_INSECURE_REMOTES=1 produces one R002 ERROR."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("local", fetch_url),
        )
        findings = _run_check(tmp_path, env={})
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, (
            f"Expected one R002 ERROR for insecure URL {fetch_url!r}, got: {error_findings}"
        )
        assert error_findings[0].code == "R002", f"Expected code R002, got: {error_findings[0].code}"

    def test_insecure_url_env_set_to_zero_also_rejects(self, tmp_path: pathlib.Path) -> None:
        """KANON_ALLOW_INSECURE_REMOTES=0 is not the override -- still rejects."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("local", "file:///tmp/repos"),
        )
        findings = _run_check(tmp_path, env={"KANON_ALLOW_INSECURE_REMOTES": "0"})
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, f"Expected one R002 ERROR when env=0, got: {error_findings}"


# ---------------------------------------------------------------------------
# file:// URL with KANON_ALLOW_INSECURE_REMOTES=1: zero findings (AC-FUNC-004)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInsecureUrlWithEnvZeroFindings:
    """A file:// URL produces zero findings when KANON_ALLOW_INSECURE_REMOTES=1 (AC-FUNC-004)."""

    @pytest.mark.parametrize(
        "fetch_url",
        [
            "file:///tmp/repos",
            "http://internal.example.com/repos",
        ],
    )
    def test_insecure_url_with_env_one_produces_zero_findings(self, tmp_path: pathlib.Path, fetch_url: str) -> None:
        """Insecure URL with KANON_ALLOW_INSECURE_REMOTES=1 produces zero findings."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("local", fetch_url),
        )
        findings = _run_check(tmp_path, env={"KANON_ALLOW_INSECURE_REMOTES": "1"})
        assert findings == [], (
            f"Expected zero findings with KANON_ALLOW_INSECURE_REMOTES=1 for {fetch_url!r}, got: {findings}"
        )


# ---------------------------------------------------------------------------
# URL with query string or fragment: one R003 ERROR (AC-FUNC-005)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueryStringOrFragmentOneError:
    """A URL with query string or fragment produces one R003 ERROR (AC-FUNC-005)."""

    @pytest.mark.parametrize(
        "fetch_url",
        [
            "https://example.com/mirrors?token=abc",
            "https://example.com/mirrors?foo=bar",
            "https://example.com/mirrors#section",
            "https://example.com/mirrors#top",
        ],
    )
    def test_query_or_fragment_url_produces_r003_error(self, tmp_path: pathlib.Path, fetch_url: str) -> None:
        """URL with query string or fragment produces exactly one R003 ERROR."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("cdn", fetch_url),
        )
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, (
            f"Expected one R003 ERROR for URL with query/fragment {fetch_url!r}, got: {error_findings}"
        )
        assert error_findings[0].code == "R003", f"Expected code R003, got: {error_findings[0].code}"


# ---------------------------------------------------------------------------
# env parameter injection (AC-FUNC-008)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnvParameterInjection:
    """_check_remote_url accepts env as a parameter; tests inject without mutating process env (AC-FUNC-008)."""

    def test_env_param_isolation_no_mutation(self, tmp_path: pathlib.Path) -> None:
        """Passing env={} and env={'KANON_ALLOW_INSECURE_REMOTES': '1'} gives different results."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("local", "file:///tmp/repos"),
        )
        findings_no_env = _run_check(tmp_path, env={})
        findings_with_env = _run_check(tmp_path, env={"KANON_ALLOW_INSECURE_REMOTES": "1"})
        assert len([f for f in findings_no_env if f.kind == "error"]) == 1, "Expected one error without env override"
        assert findings_with_env == [], "Expected zero findings with env override"


# ---------------------------------------------------------------------------
# Include-chain resolution (AC-FUNC-001 / AC-FUNC-002)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeChainResolution:
    """Remote definitions in included XML files are found via the include chain."""

    def test_remote_defined_in_included_file_resolves_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """A <remote> defined in a parent-included XML file is found and accepted when HTTPS."""
        repo_specs = _make_repo_specs(tmp_path)

        # Write a helper XML that defines the remote.
        helper_content = textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote name="origin" fetch="https://github.com/org" />
            </manifest>
        """)
        helper_path = repo_specs / "helpers.xml"
        helper_path.write_text(helper_content, encoding="utf-8")

        # Write the marketplace XML that includes helpers.xml and has a project.
        marketplace_content = textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <catalog-metadata>
                <name>included-remote-tool</name>
                <display-name>Included Remote Tool</display-name>
                <description>Remote resolved via include chain.</description>
                <version>1.0.0</version>
              </catalog-metadata>
              <include name="repo-specs/helpers.xml" />
              <project name="proj" remote="origin" path="src/proj" />
            </manifest>
        """)
        _write_marketplace_xml(repo_specs, "tool-marketplace.xml", marketplace_content)

        findings = _run_check(tmp_path)
        assert findings == [], f"Expected zero findings when remote defined in included file, got: {findings}"

    def test_include_chain_dead_end_produces_r001(self, tmp_path: pathlib.Path) -> None:
        """A <project> whose remote is not in any reachable include file produces R001."""
        repo_specs = _make_repo_specs(tmp_path)

        # Write a helper XML that does NOT define the remote the project needs.
        helper_content = textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <remote name="other" fetch="https://github.com/other-org" />
            </manifest>
        """)
        helper_path = repo_specs / "helpers.xml"
        helper_path.write_text(helper_content, encoding="utf-8")

        # The marketplace XML includes helpers.xml but references "missing" remote.
        marketplace_content = textwrap.dedent("""\
            <?xml version="1.0"?>
            <manifest>
              <catalog-metadata>
                <name>dead-end-chain-tool</name>
                <display-name>Dead End Chain Tool</display-name>
                <description>Remote not found even after following include chain.</description>
                <version>1.0.0</version>
              </catalog-metadata>
              <include name="repo-specs/helpers.xml" />
              <project name="proj" remote="missing" path="src/proj" />
            </manifest>
        """)
        _write_marketplace_xml(repo_specs, "tool-marketplace.xml", marketplace_content)

        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1, f"Expected one R001 ERROR for dead-end include chain, got: {error_findings}"
        assert error_findings[0].code == "R001"

    def test_no_projects_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """A marketplace XML with no <project> elements produces zero findings."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_no_projects(),
        )
        findings = _run_check(tmp_path)
        assert findings == [], f"Expected zero findings when no <project> elements present, got: {findings}"

    def test_empty_repo_specs_produces_zero_findings(self, tmp_path: pathlib.Path) -> None:
        """An empty repo-specs/ directory produces zero findings."""
        _make_repo_specs(tmp_path)
        findings = _run_check(tmp_path)
        assert findings == []


# ---------------------------------------------------------------------------
# Finding attributes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindingAttributes:
    """All findings have correct kind, non-empty code, and informative message."""

    def test_unresolvable_finding_has_xml_path_in_message(self, tmp_path: pathlib.Path) -> None:
        """R001 finding message contains the XML file path."""
        repo_specs = _make_repo_specs(tmp_path)
        xml_file = _write_marketplace_xml(
            repo_specs,
            "my-tool-marketplace.xml",
            _marketplace_with_unresolvable_remote("missing"),
        )
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1
        msg = error_findings[0].message
        assert xml_file.name in msg or str(xml_file) in msg, f"Expected XML path in R001 message, got: {msg}"

    def test_r002_finding_names_the_url(self, tmp_path: pathlib.Path) -> None:
        """R002 finding message contains the offending URL."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("local", "file:///tmp/repos"),
        )
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1
        msg = error_findings[0].message
        assert "file:///tmp/repos" in msg, f"Expected URL in R002 message, got: {msg}"

    def test_r002_remediation_mentions_env_var(self, tmp_path: pathlib.Path) -> None:
        """R002 finding remediation mentions KANON_ALLOW_INSECURE_REMOTES."""
        repo_specs = _make_repo_specs(tmp_path)
        _write_marketplace_xml(
            repo_specs,
            "tool-marketplace.xml",
            _marketplace_with_remote("local", "file:///tmp/repos"),
        )
        findings = _run_check(tmp_path)
        error_findings = [f for f in findings if f.kind == "error"]
        assert len(error_findings) == 1
        remediation = error_findings[0].remediation
        assert "KANON_ALLOW_INSECURE_REMOTES" in remediation, (
            f"Expected KANON_ALLOW_INSECURE_REMOTES in remediation, got: {remediation}"
        )
