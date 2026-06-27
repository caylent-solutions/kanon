"""Tests for marketplace XML validation."""

import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from kanon_cli.core.marketplace_validator import (
    _is_pinnable_revision,
    validate_include_chain,
    validate_linkfile_dest,
    validate_marketplace,
    validate_name_uniqueness,
    validate_revision_existence,
    validate_tag_format,
)


def _ls_remote_hit(_url: str, ref: str) -> tuple[int, str, str]:
    """A stub ls-remote runner that reports *ref* exists (offline, no network)."""
    return (0, f"deadbeef\t{ref}\n", "")


def _ls_remote_offline(_url: str, _ref: str) -> tuple[int, str, str]:
    """A stub ls-remote runner that reports the remote is unreachable."""
    return (128, "", "fatal: unable to access remote")


def _write_xml(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + content)
    return path


@pytest.mark.unit
class TestLinkfileDest:
    def test_valid_dest(self, tmp_path: Path) -> None:
        xml = _write_xml(
            tmp_path / "m.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="main">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                </manifest>
            """),
        )
        assert validate_linkfile_dest(xml) == []

    def test_invalid_dest(self, tmp_path: Path) -> None:
        xml = _write_xml(
            tmp_path / "m.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="main">
                    <linkfile src="s" dest="/bad/path" />
                  </project>
                </manifest>
            """),
        )
        errors = validate_linkfile_dest(xml)
        assert len(errors) == 1
        assert "proj" in errors[0]


@pytest.mark.unit
class TestIncludeChain:
    def test_valid_chain(self, tmp_path: Path) -> None:
        _write_xml(tmp_path / "root.xml", '<manifest><remote name="r" fetch="u" /></manifest>')
        _write_xml(tmp_path / "leaf.xml", '<manifest><include name="root.xml" /></manifest>')
        errors = validate_include_chain(tmp_path / "leaf.xml", tmp_path)
        assert errors == []

    def test_broken_reference(self, tmp_path: Path) -> None:
        _write_xml(tmp_path / "leaf.xml", '<manifest><include name="missing.xml" /></manifest>')
        errors = validate_include_chain(tmp_path / "leaf.xml", tmp_path)
        assert len(errors) > 0
        assert any("missing.xml" in e for e in errors)

    def test_malformed_xml_in_chain(self, tmp_path: Path) -> None:
        (tmp_path / "bad.xml").write_text("<manifest><unclosed")
        errors = validate_include_chain(tmp_path / "bad.xml", tmp_path)
        assert any("parse error" in e.lower() for e in errors)

    def test_include_missing_name_attr(self, tmp_path: Path) -> None:
        _write_xml(tmp_path / "leaf.xml", "<manifest><include /></manifest>")
        errors = validate_include_chain(tmp_path / "leaf.xml", tmp_path)
        assert any("name" in e for e in errors)

    def test_circular_include_no_infinite_loop(self, tmp_path: Path) -> None:
        _write_xml(tmp_path / "a.xml", '<manifest><include name="b.xml" /></manifest>')
        _write_xml(tmp_path / "b.xml", '<manifest><include name="a.xml" /></manifest>')
        errors = validate_include_chain(tmp_path / "a.xml", tmp_path)
        assert errors == []


@pytest.mark.unit
class TestNameUniqueness:
    def test_unique_passes(self, tmp_path: Path) -> None:
        f1 = _write_xml(
            tmp_path / "a" / "m.xml",
            '<manifest><project name="a" path=".packages/a" remote="r" revision="main" /></manifest>',
        )
        f2 = _write_xml(
            tmp_path / "b" / "m.xml",
            '<manifest><project name="b" path=".packages/b" remote="r" revision="main" /></manifest>',
        )
        assert validate_name_uniqueness([f1, f2]) == []

    def test_duplicate_detected(self, tmp_path: Path) -> None:
        f1 = _write_xml(
            tmp_path / "a" / "m.xml",
            '<manifest><project name="dup" path=".packages/dup" remote="r" revision="main" /></manifest>',
        )
        f2 = _write_xml(
            tmp_path / "b" / "m.xml",
            '<manifest><project name="dup" path=".packages/dup" remote="r" revision="main" /></manifest>',
        )
        errors = validate_name_uniqueness([f1, f2])
        assert len(errors) > 0


@pytest.mark.unit
class TestPinnableRevision:
    """The pinnable <project revision> rule (spec Section 4.5 / Section 6 / FR-22, AMENDED 2026-06-25).

    A revision is pinnable when it is a deep-path tag
    (refs/tags/<deep/path>/<pep440>), a branch ref (refs/heads/<name>), or a
    40-hex commit SHA. The wildcard, bare branch names, and version-range
    constraints are rejected: the model is exact-tag-or-branch-ref-or-sha, never
    an arbitrary spec.
    """

    @pytest.mark.parametrize(
        ("revision", "shape"),
        [
            ("refs/tags/example/proj/1", "one-part-release"),
            ("refs/tags/example/proj/1.2", "two-part-release"),
            ("refs/tags/example/proj/1.0.0", "three-part-release"),
            ("refs/tags/example/proj/1.2.0a1", "prerelease-alpha"),
            ("refs/tags/example/proj/1.0.0rc1", "release-candidate"),
            ("refs/tags/example/proj/1.0.0b3", "prerelease-beta"),
            ("refs/tags/example/proj/2024.6", "calendar-version"),
            ("refs/tags/example/proj/1!2.0.0", "epoch"),
            ("refs/tags/example/proj/1.0.0.post1", "post-release"),
            ("refs/tags/example/proj/1.0.0.dev0", "dev-release"),
            ("refs/tags/example/proj/1.0.0+local.build", "local-version"),
            ("refs/tags/deep/nested/path/proj/3.4.5", "deep-path"),
            ("refs/tags/1.0.0", "bare-three-part-release"),
            ("refs/tags/2024.6", "bare-calendar-version"),
            ("refs/tags/1!2.0.0", "bare-epoch"),
            ("refs/tags/1.0.0a1", "bare-prerelease"),
            ("refs/heads/main", "branch-ref-main"),
            ("refs/heads/feature/my-branch", "branch-ref-deep"),
            ("a" * 40, "lowercase-sha-40"),
            ("0123456789abcdef0123456789abcdef01234567", "mixed-hex-sha-40"),
        ],
    )
    def test_pinnable_revision_accepted(self, revision: str, shape: str) -> None:
        """AC-54: a full-PEP-440 exact tag, a branch ref, or a 40-hex SHA is accepted."""
        assert _is_pinnable_revision(revision)

    @pytest.mark.parametrize(
        ("revision", "reason"),
        [
            ("main", "bare-branch-is-rejected"),
            ("develop", "bare-branch-is-rejected"),
            ("feature/my-branch", "bare-slashed-branch-is-rejected"),
            ("*", "bare-wildcard-is-rejected"),
            ("refs/tags/example/proj/*", "wildcard-trailing-is-rejected"),
            ("~=1.2.0", "single-constraint-is-rejected"),
            (">=1.0.0", "single-constraint-is-rejected"),
            (">=1.0.0,<2.0.0", "compound-constraint-is-rejected"),
            (">=0.1.0,<1.0.0", "compound-constraint-is-rejected"),
            ("refs/tags/example/proj/~=1.0.0", "prefixed-constraint-is-rejected"),
            ("refs/tags/example/proj/>=1.0.0,<2.0.0", "prefixed-compound-constraint-is-rejected"),
            ("refs/tags/no-semver", "no-trailing-path-component"),
            ("refs/tags/example/proj/1.2.x", "wildcard-suffix-is-not-pep440"),
            ("refs/tags/example/proj/release-1.0.0", "named-tag-is-not-pep440"),
            ("refs/tags/example/proj/not-a-version", "non-numeric-is-not-pep440"),
            ("refs/tags/example/proj/", "empty-trailing-component"),
            ("random-string", "non-tag-string"),
            ("1.0.0", "bare-version-without-prefix"),
            ("v1.0.0", "v-prefixed-bare-version"),
            ("release-2024", "named-non-ref"),
            ("A" * 40, "uppercase-hex-is-not-sha"),
            ("a" * 39, "too-short-hex-is-not-sha"),
            ("a" * 41, "too-long-hex-is-not-sha"),
        ],
    )
    def test_non_pinnable_revision_rejected(self, revision: str, reason: str) -> None:
        """AC-54: bare branches, the wildcard, constraints, and malformed shapes are rejected."""
        assert not _is_pinnable_revision(revision)

    def test_explicit_positive_branch_ref_and_sha(self) -> None:
        """AC-54: a refs/heads/<name> branch ref and a 40-hex SHA are pinnable."""
        assert _is_pinnable_revision("refs/heads/main") is True
        assert _is_pinnable_revision("a" * 40) is True

    def test_explicit_negative_bare_branch_and_wildcard(self) -> None:
        """AC-54: a bare branch name and the wildcard are not pinnable."""
        assert _is_pinnable_revision("main") is False
        assert _is_pinnable_revision("*") is False


@pytest.mark.unit
class TestTagFormat:
    def test_validate_tag_format_accepts_calver_exact_tag(self, tmp_path: Path) -> None:
        """AC-54: validate_tag_format accepts a calver exact-tag trailing component."""
        f1 = _write_xml(
            tmp_path / "m.xml",
            '<manifest><project name="p" path=".packages/p" remote="r" revision="refs/tags/ex/proj/2024.6" /></manifest>',
        )
        assert validate_tag_format([f1], tmp_path) == []

    @pytest.mark.parametrize(
        "revision",
        ["main", "*", "~=1.2.0", ">=1.0.0,<2.0.0", "refs/tags/ex/proj/*", "refs/tags/ex/proj/1.2.x"],
    )
    def test_validate_tag_format_rejects_non_exact(self, tmp_path: Path, revision: str) -> None:
        """AC-54: validate_tag_format rejects every non-exact-tag revision shape."""

        manifest = ET.Element("manifest")
        ET.SubElement(manifest, "project", name="p", path=".packages/p", remote="r", revision=revision)
        f1 = _write_xml(tmp_path / "m.xml", ET.tostring(manifest, encoding="unicode"))
        errors = validate_tag_format([f1], tmp_path)
        assert len(errors) == 1
        assert revision in errors[0]
        assert "exact" in errors[0].lower()

    def test_validate_tag_format_valid(self, tmp_path: Path) -> None:
        f1 = _write_xml(
            tmp_path / "m.xml",
            '<manifest><project name="p" path=".packages/p" remote="r" revision="refs/tags/ex/proj/1.0.0" /></manifest>',
        )
        assert validate_tag_format([f1], tmp_path) == []

    def test_inherited_default_revision_validated(self, tmp_path: Path) -> None:
        """AC-54: a <project> omitting revision inherits <default revision> and it is validated.

        The remote.xml <default revision> inheritance leg (FR-42): a branch
        default must be rejected so no project silently inherits a branch.
        """
        f1 = _write_xml(
            tmp_path / "repo-specs" / "remote.xml",
            '<manifest><default revision="main" remote="r" /></manifest>',
        )
        f2 = _write_xml(
            tmp_path / "repo-specs" / "m.xml",
            textwrap.dedent("""\
                <manifest>
                  <include name="repo-specs/remote.xml" />
                  <project name="p" path=".packages/p" remote="r" />
                </manifest>
            """),
        )
        errors = validate_tag_format([f2], tmp_path)
        assert len(errors) == 1
        assert "inherited <default revision>" in errors[0]
        assert "main" in errors[0]

        assert validate_tag_format([f1], tmp_path) == []

    def test_inherited_exact_default_revision_passes(self, tmp_path: Path) -> None:
        """AC-54: an exact-tag <default revision> inherited by a project passes."""
        _write_xml(
            tmp_path / "repo-specs" / "remote.xml",
            '<manifest><default revision="refs/tags/ex/proj/1.0.0" remote="r" /></manifest>',
        )
        f2 = _write_xml(
            tmp_path / "repo-specs" / "m.xml",
            textwrap.dedent("""\
                <manifest>
                  <include name="repo-specs/remote.xml" />
                  <project name="p" path=".packages/p" remote="r" />
                </manifest>
            """),
        )
        assert validate_tag_format([f2], tmp_path) == []


@pytest.mark.unit
class TestRevisionExistence:
    """The two-tier + local-aware existence check (spec Section 4.5 / FR-22)."""

    def _manifest_with_remote(self, tmp_path: Path, revision: str, fetch: str) -> Path:
        return _write_xml(
            tmp_path / "m.xml",
            textwrap.dedent(f"""\
                <manifest>
                  <remote name="r" fetch="{fetch}" />
                  <project name="p" path=".packages/p" remote="r" revision="{revision}" />
                </manifest>
            """),
        )

    def test_existing_tag_passes(self, tmp_path: Path) -> None:
        f1 = self._manifest_with_remote(tmp_path, "refs/tags/ex/proj/1.0.0", "https://example.com/repo.git")
        assert validate_revision_existence([f1], tmp_path, {}, _ls_remote_hit) == []

    def test_missing_tag_on_reachable_remote_errors(self, tmp_path: Path) -> None:
        def _miss(_url: str, _ref: str) -> tuple[int, str, str]:
            return (0, "deadbeef\trefs/tags/ex/proj/9.9.9\n", "")

        f1 = self._manifest_with_remote(tmp_path, "refs/tags/ex/proj/1.0.0", "https://example.com/repo.git")
        errors = validate_revision_existence([f1], tmp_path, {}, _miss)
        assert len(errors) == 1
        assert "does not exist" in errors[0]
        assert "1.0.0" in errors[0]

    def test_offline_remote_degrades_to_warn(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        f1 = self._manifest_with_remote(tmp_path, "refs/tags/ex/proj/1.0.0", "https://example.com/repo.git")
        errors = validate_revision_existence([f1], tmp_path, {}, _ls_remote_offline)
        assert errors == []
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "existence not verified" in captured.err

    def test_offline_remote_with_ci_flag_errors(self, tmp_path: Path) -> None:
        from kanon_cli.constants import REVISION_EXISTENCE_REQUIRED_ENV_VAR

        f1 = self._manifest_with_remote(tmp_path, "refs/tags/ex/proj/1.0.0", "https://example.com/repo.git")
        errors = validate_revision_existence(
            [f1], tmp_path, {REVISION_EXISTENCE_REQUIRED_ENV_VAR: "1"}, _ls_remote_offline
        )
        assert len(errors) == 1
        assert "mandatory" in errors[0]

    def test_local_source_failure_always_errors(self, tmp_path: Path) -> None:
        """A local/file:// source resolves offline, so a failed lookup is a hard error."""
        f1 = self._manifest_with_remote(tmp_path, "refs/tags/ex/proj/1.0.0", "file:///tmp/local-repo.git")
        errors = validate_revision_existence([f1], tmp_path, {}, _ls_remote_offline)
        assert len(errors) == 1
        assert "mandatory" in errors[0]
        assert "local source" in errors[0]

    def test_unresolvable_remote_is_skipped(self, tmp_path: Path) -> None:
        """A <project remote=...> with no matching <remote> definition is skipped here."""
        f1 = _write_xml(
            tmp_path / "m.xml",
            '<manifest><project name="p" path=".packages/p" remote="r" revision="refs/tags/ex/proj/1.0.0" /></manifest>',
        )
        assert validate_revision_existence([f1], tmp_path, {}, _ls_remote_offline) == []

    def test_non_exact_revision_skipped_by_existence_check(self, tmp_path: Path) -> None:
        """A non-exact revision's error is the format check's job, not the existence check's."""
        f1 = self._manifest_with_remote(tmp_path, "main", "https://example.com/repo.git")
        assert validate_revision_existence([f1], tmp_path, {}, _ls_remote_offline) == []

    def test_existence_query_targets_resolved_project_repo_url(self, tmp_path: Path) -> None:
        """The ls-remote query must hit the joined project repo URL, not the bare GITBASE base.

        Falsifiable: if the existence check queried the bare ``<remote fetch>``
        org base (the pre-fix bug), the recorded URL would be the GITBASE base
        without the project name appended, and this assertion would fail.
        """
        captured: list[tuple[str, str]] = []

        def _record(url: str, ref: str) -> tuple[int, str, str]:
            captured.append((url, ref))
            return (0, f"deadbeef\t{ref}\n", "")

        f1 = _write_xml(
            tmp_path / "m.xml",
            textwrap.dedent("""\
                <manifest>
                  <remote name="r" fetch="https://github.com/caylent" />
                  <project name="my-plugin" path=".packages/my-plugin" remote="r"
                           revision="refs/tags/ex/proj/1.0.0" />
                </manifest>
            """),
        )
        errors = validate_revision_existence([f1], tmp_path, {}, _record)

        assert errors == []
        assert captured == [("https://github.com/caylent/my-plugin", "refs/tags/ex/proj/1.0.0")], (
            f"existence check must query the resolved project repo URL, got: {captured!r}"
        )

    def test_trailing_slash_on_fetch_base_yields_single_separator(self, tmp_path: Path) -> None:
        """A GITBASE base with a trailing slash still joins with exactly one separator."""
        captured: list[str] = []

        def _record(url: str, ref: str) -> tuple[int, str, str]:
            captured.append(url)
            return (0, f"deadbeef\t{ref}\n", "")

        f1 = _write_xml(
            tmp_path / "m.xml",
            textwrap.dedent("""\
                <manifest>
                  <remote name="r" fetch="https://github.com/caylent/" />
                  <project name="my-plugin" path=".packages/my-plugin" remote="r"
                           revision="refs/tags/ex/proj/1.0.0" />
                </manifest>
            """),
        )
        validate_revision_existence([f1], tmp_path, {}, _record)

        assert captured == ["https://github.com/caylent/my-plugin"], (
            f"trailing slash must collapse to one separator, got: {captured!r}"
        )


@pytest.mark.unit
class TestValidateMarketplace:
    def test_valid_marketplace_returns_zero(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "test-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                  <catalog-metadata>
                    <name>proj</name>
                    <display-name>Proj</display-name>
                    <description>d</description>
                    <version>1.0.0</version>
                  </catalog-metadata>
                </manifest>
            """),
        )
        assert validate_marketplace(tmp_path, env={}, ls_remote=_ls_remote_hit) == 0

    def test_no_marketplace_files_returns_one(self, tmp_path: Path) -> None:
        (tmp_path / "repo-specs").mkdir()
        assert validate_marketplace(tmp_path) == 1

    def test_errors_return_one(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "bad-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/proj/1.0.0">
                    <linkfile src="s" dest="/absolute/bad" />
                  </project>
                  <catalog-metadata>
                    <name>proj</name>
                    <display-name>Proj</display-name>
                    <description>d</description>
                    <version>1.0.0</version>
                  </catalog-metadata>
                </manifest>
            """),
        )
        assert validate_marketplace(tmp_path, env={}, ls_remote=_ls_remote_hit) == 1

    def test_branch_revision_returns_one(self, tmp_path: Path) -> None:
        """AC-54: a <project revision='main'> bare branch is rejected (pinnable rule)."""
        _write_xml(
            tmp_path / "repo-specs" / "branch-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="main">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                  <catalog-metadata>
                    <name>proj</name>
                    <display-name>Proj</display-name>
                    <description>d</description>
                    <version>1.0.0</version>
                  </catalog-metadata>
                </manifest>
            """),
        )
        assert validate_marketplace(tmp_path, env={}, ls_remote=_ls_remote_hit) == 1

    def test_discovers_new_naming_convention(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "sub" / "my-feature-marketplace.xml",
            textwrap.dedent("""\
                <manifest>
                  <project name="proj" path=".packages/proj" remote="r" revision="refs/tags/ex/1.0.0">
                    <linkfile src="s" dest="${CLAUDE_MARKETPLACES_DIR}/proj" />
                  </project>
                  <catalog-metadata>
                    <name>proj</name>
                    <display-name>Proj</display-name>
                    <description>d</description>
                    <version>1.0.0</version>
                  </catalog-metadata>
                </manifest>
            """),
        )
        assert validate_marketplace(tmp_path, env={}, ls_remote=_ls_remote_hit) == 0

    def test_ignores_non_marketplace_xml(self, tmp_path: Path) -> None:
        _write_xml(
            tmp_path / "repo-specs" / "remote.xml",
            '<manifest><remote name="r" fetch="https://example.com" /></manifest>',
        )
        assert validate_marketplace(tmp_path) == 1
