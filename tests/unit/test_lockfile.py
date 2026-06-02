"""Unit tests for src/kanon_cli/core/lockfile.py -- schema validation rules (current: v3).

Covers every validation rule parametrically per AC-TEST-001:
  - resolved_sha shape (40 hex, 64 hex, uppercase rejected, mixed-case rejected, non-hex rejected)
  - revision_spec accept set (PEP 440 SpecifierSet, refs/ prefix, branch-charset regex,
    monorepo path prefix)
  - canonical_url mismatch on ProjectEntry
  - embedded NUL / newline / tab in path and path_in_repo
  - unknown schema_version raises LockfileSchemaError
  - schema migration v1/v2 -> v3 with defaulted marketplace / ownership-ledger fields
  - per-source registered_marketplaces ledger (default empty, sorted round-trip, validation)
  - dataclass construction and field access
"""

import pytest

from kanon_cli.core.lockfile import (
    CatalogBlock,
    IncludeEntry,
    Lockfile,
    LockfileSchemaError,
    LockfileValidationError,
    ProjectEntry,
    SourceEntry,
    read_lockfile,
    write_lockfile,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

_VALID_SHA40 = "a" * 40
_VALID_SHA64 = "b" * 64
# kanon_hash uses the sha256:-prefixed form (spec Rule 1a, 71 chars total).
_VALID_KANON_HASH = "sha256:" + "a" * 64

_VALID_CATALOG = CatalogBlock(
    source="https://example.com/catalog.git@main",
    url="https://example.com/catalog.git",
    revision_spec="main",
    resolved_ref="refs/heads/main",
    resolved_sha=_VALID_SHA40,
)

_VALID_PROJECT = ProjectEntry(
    name="proj",
    url="https://example.com/proj.git",
    canonical_url="https://example.com/proj",
    revision_spec="main",
    resolved_ref="refs/heads/main",
    resolved_sha=_VALID_SHA40,
)

_VALID_INCLUDE = IncludeEntry(
    name="inc",
    path_in_repo="repo-specs/inc.xml",
    url="https://example.com/inc.git",
    resolved_sha=_VALID_SHA40,
    includes=[],
)

_VALID_SOURCE = SourceEntry(
    name="src",
    url="https://example.com/source.git",
    revision_spec="main",
    resolved_ref="refs/heads/main",
    resolved_sha=_VALID_SHA40,
    path="repo-specs/source.xml",
    includes=[],
    projects=[],
)


def _make_lockfile(**kwargs) -> Lockfile:
    """Return a minimal valid Lockfile dataclass with optional field overrides."""
    defaults = {
        "schema_version": 3,
        "generated_at": "2026-01-01T00:00:00Z",
        "generator": "kanon-cli/1.4.0",
        "kanon_hash": _VALID_KANON_HASH,
        "catalog": _VALID_CATALOG,
        "sources": [],
        "marketplace_registered": False,
        "marketplace_dir": "",
    }
    defaults.update(kwargs)
    return Lockfile(**defaults)


def _make_source(**kwargs) -> SourceEntry:
    """Return a valid SourceEntry with optional overrides."""
    defaults = dict(
        name="src",
        url="https://example.com/source.git",
        revision_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha=_VALID_SHA40,
        path="repo-specs/source.xml",
        includes=[],
        projects=[],
        registered_marketplaces=[],
    )
    defaults.update(kwargs)
    return SourceEntry(**defaults)


def _make_project(**kwargs) -> ProjectEntry:
    """Return a valid ProjectEntry with optional overrides."""
    defaults = dict(
        name="proj",
        url="https://example.com/proj.git",
        canonical_url="https://example.com/proj",
        revision_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha=_VALID_SHA40,
    )
    defaults.update(kwargs)
    return ProjectEntry(**defaults)


def _make_include(**kwargs) -> IncludeEntry:
    """Return a valid IncludeEntry with optional overrides."""
    defaults = dict(
        name="inc",
        path_in_repo="repo-specs/inc.xml",
        url="https://example.com/inc.git",
        resolved_sha=_VALID_SHA40,
        includes=[],
    )
    defaults.update(kwargs)
    return IncludeEntry(**defaults)


def _minimal_toml(schema_version: int = 1, **overrides) -> str:
    """Return a minimal valid schema-v1 TOML string for use with read_lockfile."""
    fields = {
        "schema_version": schema_version,
        "generated_at": "2026-01-01T00:00:00Z",
        "generator": "kanon-cli/1.4.0",
        "kanon_hash": _VALID_KANON_HASH,
    }
    fields.update(overrides)
    lines = [
        f"schema_version = {fields['schema_version']}",
        f'generated_at = "{fields["generated_at"]}"',
        f'generator = "{fields["generator"]}"',
        f'kanon_hash = "{fields["kanon_hash"]}"',
        "",
        "[catalog]",
        'source = "https://example.com/catalog.git@main"',
        'url = "https://example.com/catalog.git"',
        'revision_spec = "main"',
        'resolved_ref = "refs/heads/main"',
        f'resolved_sha = "{_VALID_SHA40}"',
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# AC-TEST-001: Dataclass construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDataclassConstruction:
    """Verify the dataclass tree can be constructed with valid fields."""

    def test_lockfile_construction(self):
        lf = _make_lockfile()
        assert lf.schema_version == 3
        assert lf.generated_at == "2026-01-01T00:00:00Z"
        assert lf.generator == "kanon-cli/1.4.0"
        assert lf.kanon_hash == _VALID_KANON_HASH
        assert isinstance(lf.catalog, CatalogBlock)
        assert lf.sources == []
        assert lf.marketplace_registered is False
        assert lf.marketplace_dir == ""

    def test_catalog_block_construction(self):
        cb = _VALID_CATALOG
        assert cb.source == "https://example.com/catalog.git@main"
        assert cb.url == "https://example.com/catalog.git"
        assert cb.revision_spec == "main"
        assert cb.resolved_ref == "refs/heads/main"
        assert cb.resolved_sha == _VALID_SHA40

    def test_source_entry_construction(self):
        se = _VALID_SOURCE
        assert se.name == "src"
        assert se.url == "https://example.com/source.git"
        assert se.path == "repo-specs/source.xml"
        assert se.includes == []
        assert se.projects == []

    def test_include_entry_construction(self):
        ie = _VALID_INCLUDE
        assert ie.name == "inc"
        assert ie.path_in_repo == "repo-specs/inc.xml"
        assert ie.includes == []

    def test_project_entry_construction(self):
        pe = _VALID_PROJECT
        assert pe.name == "proj"
        assert pe.canonical_url == "https://example.com/proj"

    def test_nested_includes(self):
        child = _make_include(name="child", includes=[])
        parent = _make_include(name="parent", includes=[child])
        assert parent.includes[0].name == "child"
        assert parent.includes[0].includes == []


# ---------------------------------------------------------------------------
# AC-TEST-001: resolved_sha validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolvedShaValidation:
    """Parametrised tests for resolved_sha shape validation (AC-FUNC-002)."""

    @pytest.mark.parametrize(
        "sha",
        [
            "a" * 40,  # 40 lowercase hex -- valid SHA-1
            "f" * 40,
            "0" * 40,
            "deadbeef" + "a" * 32,
            "b" * 64,  # 64 lowercase hex -- valid SHA-256
            "0" * 64,
            "abcdef0123456789" * 4,  # exactly 64 chars
        ],
    )
    def test_valid_resolved_sha_accepted(self, sha, tmp_path):
        """Valid 40 or 64 lowercase hex shas are accepted by read_lockfile."""
        toml_content = _minimal_toml()
        # Override catalog resolved_sha with our test sha
        toml_content = toml_content.replace(f'resolved_sha = "{_VALID_SHA40}"', f'resolved_sha = "{sha}"')
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        lf = read_lockfile(p)
        assert lf.catalog.resolved_sha == sha

    @pytest.mark.parametrize(
        "bad_sha",
        [
            "A" * 40,  # uppercase rejected
            "F" * 40,
            "DEADBEEF" + "a" * 32,  # mixed-case rejected
            "g" * 40,  # non-hex character
            "z" * 40,
            "a" * 39,  # wrong length (39)
            "a" * 41,  # wrong length (41)
            "a" * 63,  # wrong length (63)
            "a" * 65,  # wrong length (65)
            "",  # empty
            "abc",  # too short
        ],
    )
    def test_invalid_resolved_sha_raises(self, bad_sha, tmp_path):
        """Invalid resolved_sha raises LockfileValidationError naming the bad value."""
        toml_content = _minimal_toml()
        toml_content = toml_content.replace(f'resolved_sha = "{_VALID_SHA40}"', f'resolved_sha = "{bad_sha}"')
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        with pytest.raises(LockfileValidationError) as exc_info:
            read_lockfile(p)
        assert bad_sha in str(exc_info.value) or "resolved_sha" in str(exc_info.value)

    @pytest.mark.parametrize(
        "sha",
        [
            "DeadBeef" + "a" * 32,  # mixed case
            "ABCDEF01" + "a" * 32,  # uppercase prefix
        ],
    )
    def test_mixed_case_sha_rejected(self, sha, tmp_path):
        """Mixed-case resolved_sha is rejected (only lowercase hex accepted)."""
        toml_content = _minimal_toml()
        toml_content = toml_content.replace(f'resolved_sha = "{_VALID_SHA40}"', f'resolved_sha = "{sha}"')
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        with pytest.raises(LockfileValidationError):
            read_lockfile(p)

    def test_error_message_names_field_path(self, tmp_path):
        """LockfileValidationError message names the offending field path."""
        bad_sha = "X" * 40
        toml = (
            _minimal_toml()
            + "\n[[sources]]\n"
            + 'name = "s"\n'
            + 'url = "https://example.com/s.git"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{bad_sha}"\n'
            + 'path = "repo-specs/s.xml"\n'
        )
        p = tmp_path / "kanon.lock"
        p.write_text(toml)
        with pytest.raises(LockfileValidationError) as exc_info:
            read_lockfile(p)
        err_msg = str(exc_info.value)
        # Should name either the field path or the bad value
        assert "resolved_sha" in err_msg or bad_sha in err_msg


# ---------------------------------------------------------------------------
# AC-TEST-001: revision_spec validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRevisionSpecValidation:
    """Parametrised tests for revision_spec accept rules (AC-FUNC-003)."""

    @pytest.mark.parametrize(
        "spec",
        [
            # PEP 440 SpecifierSet branch
            "==1.0.0",
            "~=2.0.0",
            ">=1.0,<2.0",
            "!=1.0.0",
            # refs/ prefix branch
            "refs/heads/main",
            "refs/tags/v1.0.0",
            "refs/pull/42/head",
            # branch-charset regex branch
            "main",
            "feature-branch",
            "release/1.0",
            "my_branch",
            "v1.0.0",
            "feat/add-feature",
            # monorepo path prefix + SpecifierSet
            "subpackage/==1.0.0",
            "sub/pkg/~=2.0.0",
            # bare wildcard "*" = "any version" (written verbatim to the lockfile by
            # add/install; the reader must accept it -- MK-18 / kanon clean)
            "*",
        ],
    )
    def test_valid_revision_spec_accepted(self, spec, tmp_path):
        """Valid revision_spec values are accepted by read_lockfile."""
        toml_content = _minimal_toml()
        toml_content = toml_content.replace('revision_spec = "main"', f'revision_spec = "{spec}"')
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        lf = read_lockfile(p)
        assert lf.catalog.revision_spec == spec

    @pytest.mark.parametrize(
        "bad_spec",
        [
            "has space",  # space not in branch-charset, not PEP440, not refs/
            "@invalid",  # @ not in branch-charset
            "!invalid",  # ! not in branch-charset, not valid PEP440 alone
            "",  # empty string
        ],
    )
    def test_invalid_revision_spec_raises(self, bad_spec, tmp_path):
        """Invalid revision_spec raises LockfileValidationError."""
        toml_content = _minimal_toml()
        toml_content = toml_content.replace('revision_spec = "main"', f'revision_spec = "{bad_spec}"')
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        with pytest.raises(LockfileValidationError):
            read_lockfile(p)

    def test_monorepo_prefix_stripped_before_pep440_parse(self, tmp_path):
        """Monorepo path prefix is stripped before PEP 440 parsing -- 'sub/==1.0.0' is valid."""
        spec = "sub/==1.0.0"
        toml_content = _minimal_toml()
        toml_content = toml_content.replace('revision_spec = "main"', f'revision_spec = "{spec}"')
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        lf = read_lockfile(p)
        assert lf.catalog.revision_spec == spec

    def test_refs_prefix_accepted_verbatim(self, tmp_path):
        """revision_spec starting with 'refs/' is accepted without further parsing."""
        spec = "refs/heads/some-branch"
        toml_content = _minimal_toml()
        toml_content = toml_content.replace('revision_spec = "main"', f'revision_spec = "{spec}"')
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        lf = read_lockfile(p)
        assert lf.catalog.revision_spec == spec


# ---------------------------------------------------------------------------
# AC-TEST-001: canonical_url validation on ProjectEntry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCanonicalUrlValidation:
    """Tests for canonical_url mismatch detection (AC-FUNC-004)."""

    def test_matching_canonical_url_accepted(self, tmp_path):
        """ProjectEntry with canonical_url matching canonicalize_repo_url(url) is accepted."""
        toml = (
            _minimal_toml()
            + "\n[[sources]]\n"
            + 'name = "s"\n'
            + 'url = "https://example.com/source.git"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
            + 'path = "repo-specs/s.xml"\n'
            + "\n[[sources.projects]]\n"
            + 'name = "proj"\n'
            + 'url = "https://example.com/proj.git"\n'
            + 'canonical_url = "https://example.com/proj"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
        )
        p = tmp_path / "kanon.lock"
        p.write_text(toml)
        lf = read_lockfile(p)
        assert lf.sources[0].projects[0].canonical_url == "https://example.com/proj"

    def test_mismatched_canonical_url_raises(self, tmp_path):
        """ProjectEntry with wrong canonical_url raises LockfileValidationError."""
        toml = (
            _minimal_toml()
            + "\n[[sources]]\n"
            + 'name = "s"\n'
            + 'url = "https://example.com/source.git"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
            + 'path = "repo-specs/s.xml"\n'
            + "\n[[sources.projects]]\n"
            + 'name = "proj"\n'
            + 'url = "https://example.com/proj.git"\n'
            + 'canonical_url = "https://WRONG.example.com/proj"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
        )
        p = tmp_path / "kanon.lock"
        p.write_text(toml)
        with pytest.raises(LockfileValidationError) as exc_info:
            read_lockfile(p)
        err_msg = str(exc_info.value)
        # Error must include both the recorded and computed value
        assert "canonical_url" in err_msg or "WRONG" in err_msg

    def test_error_includes_both_recorded_and_computed(self, tmp_path):
        """canonical_url mismatch error shows both the recorded and computed values."""
        wrong_canonical = "https://WRONG.example.com/proj"
        toml = (
            _minimal_toml()
            + "\n[[sources]]\n"
            + 'name = "s"\n'
            + 'url = "https://example.com/source.git"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
            + 'path = "repo-specs/s.xml"\n'
            + "\n[[sources.projects]]\n"
            + 'name = "proj"\n'
            + 'url = "https://example.com/proj.git"\n'
            + f'canonical_url = "{wrong_canonical}"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
        )
        p = tmp_path / "kanon.lock"
        p.write_text(toml)
        with pytest.raises(LockfileValidationError) as exc_info:
            read_lockfile(p)
        err_msg = str(exc_info.value)
        # Must contain the recorded (wrong) value
        assert wrong_canonical in err_msg
        # Must also contain the computed (correct) value
        assert "https://example.com/proj" in err_msg


# ---------------------------------------------------------------------------
# AC-TEST-001: path and path_in_repo character validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPathCharacterValidation:
    """Tests for embedded NUL / newline / tab in path and path_in_repo (AC-FUNC-005)."""

    @pytest.mark.parametrize(
        ("field", "bad_char", "char_desc"),
        [
            ("path", "\x00", "NUL"),
            ("path", "\n", "newline"),
            ("path", "\t", "tab"),
        ],
    )
    def test_bad_char_in_source_path_raises(self, field, bad_char, char_desc, tmp_path):
        """SourceEntry.path containing NUL, newline, or tab raises LockfileValidationError."""
        bad_path = f"repo-specs/some{bad_char}file.xml"
        # TOML cannot represent NUL in a basic string; use escape sequences
        if bad_char == "\x00":
            toml_path_val = bad_path.replace("\x00", "\\u0000")
        elif bad_char == "\n":
            toml_path_val = bad_path.replace("\n", "\\n")
        elif bad_char == "\t":
            toml_path_val = bad_path.replace("\t", "\\t")
        else:
            toml_path_val = bad_path
        toml = (
            _minimal_toml()
            + "\n[[sources]]\n"
            + 'name = "s"\n'
            + 'url = "https://example.com/source.git"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
            + f'path = "{toml_path_val}"\n'
        )
        p = tmp_path / "kanon.lock"
        p.write_text(toml)
        with pytest.raises(LockfileValidationError) as exc_info:
            read_lockfile(p)
        err_msg = str(exc_info.value)
        assert "path" in err_msg

    @pytest.mark.parametrize(
        ("bad_char", "char_desc"),
        [
            ("\x00", "NUL"),
            ("\n", "newline"),
            ("\t", "tab"),
        ],
    )
    def test_bad_char_in_include_path_in_repo_raises(self, bad_char, char_desc, tmp_path):
        """IncludeEntry.path_in_repo containing bad chars raises LockfileValidationError."""
        if bad_char == "\x00":
            toml_path_val = "repo-specs/inc\\u0000file.xml"
        elif bad_char == "\n":
            toml_path_val = "repo-specs/inc\\nfile.xml"
        elif bad_char == "\t":
            toml_path_val = "repo-specs/inc\\tfile.xml"
        else:
            toml_path_val = f"repo-specs/inc{bad_char}file.xml"
        toml = (
            _minimal_toml()
            + "\n[[sources]]\n"
            + 'name = "s"\n'
            + 'url = "https://example.com/source.git"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
            + 'path = "repo-specs/s.xml"\n'
            + "\n[[sources.includes]]\n"
            + 'name = "inc"\n'
            + f'path_in_repo = "{toml_path_val}"\n'
            + 'url = "https://example.com/inc.git"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
        )
        p = tmp_path / "kanon.lock"
        p.write_text(toml)
        with pytest.raises(LockfileValidationError) as exc_info:
            read_lockfile(p)
        err_msg = str(exc_info.value)
        assert "path_in_repo" in err_msg or "path" in err_msg

    def test_error_names_bad_char_by_codepoint(self, tmp_path):
        """LockfileValidationError names the bad character by codepoint."""
        toml = (
            _minimal_toml()
            + "\n[[sources]]\n"
            + 'name = "s"\n'
            + 'url = "https://example.com/source.git"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
            + 'path = "repo-specs/bad\\u0000file.xml"\n'
        )
        p = tmp_path / "kanon.lock"
        p.write_text(toml)
        with pytest.raises(LockfileValidationError) as exc_info:
            read_lockfile(p)
        err_msg = str(exc_info.value)
        # Must name the codepoint (U+0000) or describe the char (NUL, null)
        assert any(x in err_msg for x in ["U+0000", "0x00", "NUL", "null", "\\x00"])

    def test_clean_path_accepted(self, tmp_path):
        """SourceEntry.path with no bad chars is accepted without error."""
        toml = (
            _minimal_toml()
            + "\n[[sources]]\n"
            + 'name = "s"\n'
            + 'url = "https://example.com/source.git"\n'
            + 'revision_spec = "main"\n'
            + 'resolved_ref = "refs/heads/main"\n'
            + f'resolved_sha = "{_VALID_SHA40}"\n'
            + 'path = "repo-specs/clean-path.xml"\n'
        )
        p = tmp_path / "kanon.lock"
        p.write_text(toml)
        lf = read_lockfile(p)
        assert lf.sources[0].path == "repo-specs/clean-path.xml"


# ---------------------------------------------------------------------------
# AC-TEST-001: unknown schema_version raises LockfileSchemaError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSchemaVersionValidation:
    """Tests for schema_version handling -- updated for T2 migration policy.

    T2 differentiates forward-incompatible reads (schema_version > current)
    from backward-incompatible reads (schema_version < current).
    """

    @pytest.mark.parametrize("future_version", [4, 99, 100])
    def test_forward_incompatible_schema_raises_lockfile_schema_error(self, future_version, tmp_path):
        """schema_version > CURRENT_SCHEMA_VERSION raises LockfileSchemaError."""
        toml_content = _minimal_toml(schema_version=future_version)
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        with pytest.raises(LockfileSchemaError) as exc_info:
            read_lockfile(p)
        err_msg = str(exc_info.value)
        assert f"v{future_version}" in err_msg
        assert "upgrade kanon-cli" in err_msg

    @pytest.mark.parametrize("old_version", [0, -1])
    def test_backward_incompatible_schema_no_upgrader_raises_lockfile_schema_error(self, old_version, tmp_path):
        """schema_version < CURRENT_SCHEMA_VERSION with no upgrader raises LockfileSchemaError."""
        toml_content = _minimal_toml(schema_version=old_version)
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        with pytest.raises(LockfileSchemaError) as exc_info:
            read_lockfile(p)
        err_msg = str(exc_info.value)
        assert f"v{old_version}" in err_msg
        assert "kanon bug" in err_msg

    def test_schema_version_3_accepted(self, tmp_path):
        """schema_version == 3 is the current supported version and is accepted."""
        toml_content = _minimal_toml(schema_version=3)
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        lf = read_lockfile(p)
        assert lf.schema_version == 3

    def test_schema_version_2_migrated_to_3(self, tmp_path):
        """schema_version == 2 is transparently migrated to v3 (no sources -> empty list)."""
        toml_content = _minimal_toml(schema_version=2)
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        lf = read_lockfile(p)
        assert lf.schema_version == 3
        assert lf.sources == []

    def test_schema_version_1_migrated_to_3(self, tmp_path):
        """schema_version == 1 is transparently migrated through v2 to v3 with all defaults."""
        toml_content = _minimal_toml(schema_version=1)
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        lf = read_lockfile(p)
        assert lf.schema_version == 3
        assert lf.marketplace_registered is False
        assert lf.marketplace_dir == ""

    def test_forward_incompat_schema_error_message_format(self, tmp_path):
        """LockfileSchemaError message for forward-incompatible reads matches spec text."""
        toml_content = _minimal_toml(schema_version=7)
        p = tmp_path / "kanon.lock"
        p.write_text(toml_content)
        with pytest.raises(LockfileSchemaError) as exc_info:
            read_lockfile(p)
        assert str(exc_info.value) == "lockfile schema v7 written by newer kanon; upgrade kanon-cli."

    def test_schema_error_is_distinct_from_validation_error(self, tmp_path):
        """LockfileSchemaError is NOT a subclass of LockfileValidationError."""
        assert not issubclass(LockfileSchemaError, LockfileValidationError)

    def test_both_exceptions_are_distinct_types(self):
        """LockfileSchemaError and LockfileValidationError are distinct exception types."""
        schema_err = LockfileSchemaError("schema v2 written by newer kanon; upgrade kanon-cli.")
        val_err = LockfileValidationError("bad sha")
        assert type(schema_err) is not type(val_err)


# ---------------------------------------------------------------------------
# Tests for missing file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadLockfileMissingFile:
    """read_lockfile raises an informative error when the file does not exist."""

    def test_missing_file_raises_file_not_found(self, tmp_path):
        """read_lockfile raises FileNotFoundError for a nonexistent path."""
        p = tmp_path / "nonexistent.lock"
        with pytest.raises(FileNotFoundError):
            read_lockfile(p)


# ---------------------------------------------------------------------------
# Tests for write_lockfile basic functionality
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteLockfileUnit:
    """Basic unit tests for write_lockfile -- atomicity is tested in integration."""

    def test_write_creates_file(self, tmp_path):
        """write_lockfile creates the destination file."""
        lf = _make_lockfile()
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        assert p.exists()

    def test_write_creates_valid_toml(self, tmp_path):
        """write_lockfile produces a file parseable by tomllib."""
        import tomllib

        lf = _make_lockfile()
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        with open(p, "rb") as f:
            data = tomllib.load(f)
        assert data["schema_version"] == 3

    def test_write_then_read_roundtrip(self, tmp_path):
        """write_lockfile followed by read_lockfile round-trips the Lockfile object."""
        lf = _make_lockfile()
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        lf2 = read_lockfile(p)
        assert lf == lf2


# ---------------------------------------------------------------------------
# AC-7: marketplace_registered and marketplace_dir fields (schema v2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarketplaceFields:
    """AC-7: Lockfile schema v2 marketplace_registered and marketplace_dir fields."""

    def test_marketplace_registered_defaults_false(self):
        """Lockfile.marketplace_registered defaults to False when not supplied."""
        lf = _make_lockfile()
        assert lf.marketplace_registered is False

    def test_marketplace_dir_defaults_empty_string(self):
        """Lockfile.marketplace_dir defaults to empty string when not supplied."""
        lf = _make_lockfile()
        assert lf.marketplace_dir == ""

    def test_marketplace_registered_true_roundtrip(self, tmp_path):
        """marketplace_registered=True and marketplace_dir are preserved by write/read roundtrip."""
        lf = _make_lockfile(marketplace_registered=True, marketplace_dir="/path/to/mp")
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        lf2 = read_lockfile(p)
        assert lf2.marketplace_registered is True
        assert lf2.marketplace_dir == "/path/to/mp"

    def test_marketplace_registered_false_roundtrip(self, tmp_path):
        """marketplace_registered=False roundtrips correctly."""
        lf = _make_lockfile(marketplace_registered=False, marketplace_dir="")
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        lf2 = read_lockfile(p)
        assert lf2.marketplace_registered is False
        assert lf2.marketplace_dir == ""

    def test_v1_lockfile_migration_adds_marketplace_fields(self, tmp_path):
        """A v1 lockfile (no marketplace fields) is migrated to v3 with defaults."""
        v1_toml = _minimal_toml(schema_version=1)
        p = tmp_path / "kanon.lock"
        p.write_text(v1_toml)
        lf = read_lockfile(p)
        assert lf.schema_version == 3
        assert lf.marketplace_registered is False
        assert lf.marketplace_dir == ""

    def test_marketplace_dir_written_to_toml(self, tmp_path):
        """write_lockfile writes marketplace_dir to the TOML file."""
        import tomllib

        lf = _make_lockfile(marketplace_registered=True, marketplace_dir="/home/user/.claude/marketplaces")
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        with open(p, "rb") as f:
            data = tomllib.load(f)
        assert data["marketplace_registered"] is True
        assert data["marketplace_dir"] == "/home/user/.claude/marketplaces"

    def test_marketplace_registered_written_to_toml_as_false(self, tmp_path):
        """write_lockfile writes marketplace_registered=false to the TOML file when not registered."""
        import tomllib

        lf = _make_lockfile(marketplace_registered=False)
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        with open(p, "rb") as f:
            data = tomllib.load(f)
        assert data["marketplace_registered"] is False


# ---------------------------------------------------------------------------
# Per-source registered_marketplaces ledger (schema v3)
# ---------------------------------------------------------------------------


def _source_toml_block(*, name: str, registered_marketplaces_literal: str | None) -> str:
    """Return a ``[[sources]]`` TOML block, optionally carrying the per-source ledger.

    Args:
        name: The source name.
        registered_marketplaces_literal: If not None, the raw TOML array literal
            to emit for ``registered_marketplaces`` (e.g. ``'["a-mp"]'`` or
            ``"[1, 2, 3]"``).  When None the key is omitted entirely (v2-style).
    """
    lines = [
        "",
        "[[sources]]",
        f'name = "{name}"',
        'url = "https://example.com/source.git"',
        'revision_spec = "main"',
        'resolved_ref = "refs/heads/main"',
        f'resolved_sha = "{_VALID_SHA40}"',
        'path = "repo-specs/source.xml"',
    ]
    if registered_marketplaces_literal is not None:
        lines.append(f"registered_marketplaces = {registered_marketplaces_literal}")
    return "\n".join(lines) + "\n"


@pytest.mark.unit
class TestRegisteredMarketplacesField:
    """Lockfile schema v3 PER-SOURCE ``registered_marketplaces`` ledger field."""

    def test_source_registered_marketplaces_defaults_empty(self):
        """SourceEntry.registered_marketplaces defaults to an empty list when not supplied."""
        src = SourceEntry(
            name="src",
            url="https://example.com/source.git",
            revision_spec="main",
            resolved_ref="refs/heads/main",
            resolved_sha=_VALID_SHA40,
            path="repo-specs/source.xml",
        )
        assert src.registered_marketplaces == []

    def test_lockfile_has_no_top_level_registered_marketplaces(self):
        """The root Lockfile dataclass carries NO top-level registered_marketplaces field."""
        lf = _make_lockfile()
        assert not hasattr(lf, "registered_marketplaces"), (
            "schema v3 moved the ledger per-source; the root Lockfile must not expose it"
        )

    def test_source_registered_marketplaces_written_empty_as_toml_array(self, tmp_path):
        """write_lockfile emits registered_marketplaces = [] inside the source table when empty."""
        import tomllib

        lf = _make_lockfile(sources=[_make_source(name="src", registered_marketplaces=[])])
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        with open(p, "rb") as f:
            data = tomllib.load(f)
        assert "registered_marketplaces" not in data, "the ledger must not appear at the top level"
        assert data["sources"][0]["registered_marketplaces"] == []

    def test_source_registered_marketplaces_roundtrip_sorted(self, tmp_path):
        """write_lockfile sorts each source's ledger; read_lockfile returns the sorted list."""
        lf = _make_lockfile(sources=[_make_source(name="src", registered_marketplaces=["b-mp", "a-mp"])])
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        lf2 = read_lockfile(p)
        assert lf2.sources[0].registered_marketplaces == ["a-mp", "b-mp"]

    def test_per_source_ledgers_are_independent(self, tmp_path):
        """Two sources keep distinct per-source ledgers across a write/read roundtrip."""
        lf = _make_lockfile(
            sources=[
                _make_source(name="alpha", registered_marketplaces=["alpha-mp"]),
                _make_source(name="bravo", registered_marketplaces=["bravo-mp"]),
            ]
        )
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        lf2 = read_lockfile(p)
        by_name = {s.name: s for s in lf2.sources}
        assert by_name["alpha"].registered_marketplaces == ["alpha-mp"]
        assert by_name["bravo"].registered_marketplaces == ["bravo-mp"]

    def test_source_registered_marketplaces_written_sorted_in_toml(self, tmp_path):
        """write_lockfile serialises each source's ledger sorted regardless of input order."""
        import tomllib

        lf = _make_lockfile(sources=[_make_source(name="src", registered_marketplaces=["b-mp", "a-mp", "c-mp"])])
        p = tmp_path / "kanon.lock"
        write_lockfile(lf, p)
        with open(p, "rb") as f:
            data = tomllib.load(f)
        assert data["sources"][0]["registered_marketplaces"] == ["a-mp", "b-mp", "c-mp"]

    def test_source_registered_marketplaces_rewrite_is_byte_stable(self, tmp_path):
        """Re-writing a lockfile read from disk produces byte-identical output."""
        lf = _make_lockfile(sources=[_make_source(name="src", registered_marketplaces=["b-mp", "a-mp"])])
        p1 = tmp_path / "kanon.lock"
        write_lockfile(lf, p1)
        first_bytes = p1.read_bytes()

        lf2 = read_lockfile(p1)
        p2 = tmp_path / "kanon2.lock"
        write_lockfile(lf2, p2)
        second_bytes = p2.read_bytes()
        assert first_bytes == second_bytes

    def test_v2_source_without_key_migrates_to_empty_ledger(self, tmp_path):
        """A v2-style source TOML lacking registered_marketplaces migrates to a per-source empty ledger."""
        v2_toml = (
            "schema_version = 2\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/1.4.0"\n'
            f'kanon_hash = "{_VALID_KANON_HASH}"\n'
            "marketplace_registered = false\n"
            'marketplace_dir = ""\n'
            "\n"
            "[catalog]\n"
            'source = "https://example.com/catalog.git@main"\n'
            'url = "https://example.com/catalog.git"\n'
            'revision_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{_VALID_SHA40}"\n'
            + _source_toml_block(name="legacy", registered_marketplaces_literal=None)
        )
        p = tmp_path / "kanon.lock"
        p.write_text(v2_toml)
        lf = read_lockfile(p)
        assert lf.schema_version == 3
        assert len(lf.sources) == 1
        assert lf.sources[0].registered_marketplaces == [], (
            "v2->v3 migration must default each source's registered_marketplaces to []"
        )

    def test_non_list_source_registered_marketplaces_raises_validation_error(self, tmp_path):
        """A per-source registered_marketplaces that is not a list of strings raises a validation error."""
        bad_toml = (
            "schema_version = 3\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/1.4.0"\n'
            f'kanon_hash = "{_VALID_KANON_HASH}"\n'
            "marketplace_registered = false\n"
            'marketplace_dir = ""\n'
            "\n"
            "[catalog]\n"
            'source = "https://example.com/catalog.git@main"\n'
            'url = "https://example.com/catalog.git"\n'
            'revision_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{_VALID_SHA40}"\n'
            + _source_toml_block(name="src", registered_marketplaces_literal="[1, 2, 3]")
        )
        p = tmp_path / "kanon.lock"
        p.write_text(bad_toml)
        with pytest.raises(LockfileValidationError, match=r"sources\[0\].registered_marketplaces"):
            read_lockfile(p)
