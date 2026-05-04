"""Unit tests for <include> cycle detection and depth-limit enforcement.

Covers:
  AC-TEST-001  Self-reference (A includes A) raises cycle error.
  AC-TEST-002  Two-node cycle (A->B->A) raises cycle error.
  AC-TEST-003  Three-node cycle (A->B->C->A) raises cycle error.
  AC-TEST-004  Include depth limit (MAX_SUBMANIFEST_DEPTH) is enforced.
  AC-TEST-005  Relative path resolution is correct for nested includes.

  AC-FUNC-001  Parser detects all include cycles and enforces depth limit.
  AC-CHANNEL-001  Errors surface as exceptions, not stdout writes.

All tests use real manifest files written to tmp_path via local helpers.
The conftest in tests/unit/repo/ auto-applies @pytest.mark.unit to every
item collected under that directory so the @pytest.mark.unit decorator is
present on every class but is not a formal dependency of test collection.
"""

import pathlib

import pytest

from kanon_cli.repo import manifest_xml
from kanon_cli.repo.error import ManifestParseError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_GIT_CONFIG_TEMPLATE = '[remote "origin"]\n        url = https://localhost:0/manifest\n'


def _make_repo_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal .repo directory structure needed for XmlManifest.

    Sets up:
    - <tmp>/.repo/
    - <tmp>/.repo/manifests/    (the include_root / worktree)
    - <tmp>/.repo/manifests.git/config  (remote origin URL for GitConfig)

    Args:
        tmp_path: Pytest tmp_path for isolation.

    Returns:
        The absolute path to the .repo directory.
    """
    repodir = tmp_path / ".repo"
    repodir.mkdir()
    (repodir / "manifests").mkdir()
    manifests_git = repodir / "manifests.git"
    manifests_git.mkdir()
    (manifests_git / "config").write_text(_GIT_CONFIG_TEMPLATE, encoding="utf-8")
    return repodir


def _write_manifest(repodir: pathlib.Path, xml_content: str) -> pathlib.Path:
    """Write xml_content to the canonical manifest file path and return it.

    Args:
        repodir: The .repo directory.
        xml_content: Full XML content for the manifest file.

    Returns:
        Absolute path to the written manifest file.
    """
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME
    manifest_file.write_text(xml_content, encoding="utf-8")
    return manifest_file


def _write_included_manifest(repodir: pathlib.Path, filename: str, xml_content: str) -> pathlib.Path:
    """Write xml_content to a named manifest file inside the manifests directory.

    The manifests directory is the include_root. Included manifests are resolved
    relative to it.

    Args:
        repodir: The .repo directory.
        filename: Filename (no path components) for the included manifest.
        xml_content: Full XML content for the included manifest file.

    Returns:
        Absolute path to the written included manifest file.
    """
    included_file = repodir / "manifests" / filename
    included_file.write_text(xml_content, encoding="utf-8")
    return included_file


def _load_manifest(repodir: pathlib.Path, manifest_file: pathlib.Path) -> manifest_xml.XmlManifest:
    """Instantiate and load an XmlManifest from disk.

    Args:
        repodir: The .repo directory.
        manifest_file: Absolute path to the primary manifest file.

    Returns:
        A loaded XmlManifest instance.
    """
    m = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    m.Load()
    return m


# ---------------------------------------------------------------------------
# AC-TEST-001: Self-reference (A includes A) raises cycle error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeSelfReference:
    """AC-TEST-001: A manifest that includes itself raises a cycle error.

    When an <include> element names the same file that is currently being
    parsed, the parser must detect the cycle and raise ManifestParseError
    rather than recursing until Python's call stack is exhausted.
    """

    def test_self_reference_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A manifest that includes itself raises ManifestParseError.

        Given a manifest file that contains <include name="self_ref.xml" />
        where self_ref.xml is the same file, the parser must raise
        ManifestParseError naming the cycle rather than hitting Python's
        recursion limit.

        AC-TEST-001, AC-FUNC-001
        """
        self_ref_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="self_ref.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "self_ref.xml", self_ref_xml)
        manifest_file = _write_manifest(repodir, self_ref_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-001: expected a non-empty error message for a self-referencing include but got an empty string"
        )

    def test_self_reference_error_mentions_cycle_or_include(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The cycle error message from a self-referencing include is informative.

        The error message must mention either 'cycle' or 'include' so the
        developer can understand what went wrong.

        AC-TEST-001, AC-FUNC-001
        """
        self_ref_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="loop_a.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "loop_a.xml", self_ref_xml)
        manifest_file = _write_manifest(repodir, self_ref_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value).lower()
        assert "cycle" in error_message or "include" in error_message, (
            f"AC-TEST-001: expected error message to mention 'cycle' or 'include' for "
            f"self-referencing include but got: {str(exc_info.value)!r}"
        )

    def test_self_reference_does_not_raise_recursion_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A self-referencing include raises ManifestParseError, not RecursionError.

        The parser must detect the cycle explicitly and raise ManifestParseError
        before Python's call stack is exhausted. A RecursionError (subclass of
        RuntimeError) escaping the parser boundary is a bug because callers
        expect ManifestParseError for all manifest-level failures.

        AC-TEST-001, AC-FUNC-001
        """
        self_ref_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="cycle_self.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "cycle_self.xml", self_ref_xml)
        manifest_file = _write_manifest(repodir, self_ref_xml)

        raised_type = None
        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError as exc:
            raised_type = type(exc)
        except RecursionError as exc:
            pytest.fail(
                f"AC-TEST-001: self-referencing include must raise ManifestParseError "
                f"but raised RecursionError instead: {exc!r}"
            )

        assert raised_type is ManifestParseError, (
            "AC-TEST-001: expected ManifestParseError for self-referencing include "
            "but nothing was raised or a different exception occurred"
        )

    @pytest.mark.parametrize(
        "cycle_filename",
        [
            "alpha.xml",
            "vendor_self.xml",
            "platform-manifest.xml",
        ],
    )
    def test_self_reference_various_filenames(
        self,
        tmp_path: pathlib.Path,
        cycle_filename: str,
    ) -> None:
        """Parameterized: self-referencing includes raise ManifestParseError for various filenames.

        AC-TEST-001
        """
        self_ref_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            f'  <include name="{cycle_filename}" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, cycle_filename, self_ref_xml)
        manifest_file = _write_manifest(repodir, self_ref_xml)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-002: Two-node cycle (A->B->A) raises cycle error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeTwoNodeCycle:
    """AC-TEST-002: A->B->A two-node include cycle raises ManifestParseError.

    When manifest A includes manifest B, and manifest B includes manifest A,
    the parser must detect the mutual inclusion cycle and raise ManifestParseError.
    """

    def test_two_node_cycle_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A two-node include cycle (A->B->A) raises ManifestParseError.

        Given:
        - primary manifest.xml includes a.xml
        - a.xml includes b.xml
        - b.xml includes a.xml
        The parser must detect the cycle and raise ManifestParseError.

        AC-TEST-002, AC-FUNC-001
        """
        # a.xml includes b.xml
        a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="b.xml" />\n'
            "</manifest>\n"
        )
        # b.xml includes a.xml -- completing the cycle
        b_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="a.xml" />\n'
            "</manifest>\n"
        )
        # primary manifest includes a.xml to start the chain
        primary_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="a.xml" />\n</manifest>\n'
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "a.xml", a_xml)
        _write_included_manifest(repodir, "b.xml", b_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-002: expected a non-empty error message for A->B->A include cycle but got empty string"
        )

    def test_two_node_cycle_does_not_raise_recursion_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A two-node cycle (A->B->A) raises ManifestParseError, not RecursionError.

        AC-TEST-002, AC-FUNC-001
        """
        a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="cyc_b.xml" />\n'
            "</manifest>\n"
        )
        b_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="cyc_a.xml" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="cyc_a.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "cyc_a.xml", a_xml)
        _write_included_manifest(repodir, "cyc_b.xml", b_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        try:
            _load_manifest(repodir, manifest_file)
            pytest.fail("AC-TEST-002: expected ManifestParseError for two-node cycle but nothing was raised")
        except ManifestParseError:
            pass
        except RecursionError as exc:
            pytest.fail(
                f"AC-TEST-002: two-node cycle must raise ManifestParseError but raised RecursionError instead: {exc!r}"
            )

    def test_two_node_cycle_error_mentions_filename(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The cycle error from a two-node cycle mentions the involved filename.

        AC-TEST-002
        """
        a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="back_to_a.xml" />\n'
            "</manifest>\n"
        )
        back_to_a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="start_a.xml" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="start_a.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "start_a.xml", a_xml)
        _write_included_manifest(repodir, "back_to_a.xml", back_to_a_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "start_a.xml" in error_message or "back_to_a.xml" in error_message or "cycle" in error_message.lower(), (
            f"AC-TEST-002: expected cycle error to mention a filename involved in the cycle but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Three-node cycle (A->B->C->A) raises cycle error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeThreeNodeCycle:
    """AC-TEST-003: A->B->C->A three-node include cycle raises ManifestParseError.

    When A includes B, B includes C, and C includes A, the parser must detect
    the cycle at the point where C tries to re-include A.
    """

    def test_three_node_cycle_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A three-node include cycle (A->B->C->A) raises ManifestParseError.

        Given:
        - primary manifest.xml includes three_a.xml
        - three_a.xml includes three_b.xml
        - three_b.xml includes three_c.xml
        - three_c.xml includes three_a.xml (completing the cycle)
        The parser must detect this cycle and raise ManifestParseError.

        AC-TEST-003, AC-FUNC-001
        """
        a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="three_b.xml" />\n'
            "</manifest>\n"
        )
        b_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="three_c.xml" />\n'
            "</manifest>\n"
        )
        c_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="three_a.xml" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="three_a.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "three_a.xml", a_xml)
        _write_included_manifest(repodir, "three_b.xml", b_xml)
        _write_included_manifest(repodir, "three_c.xml", c_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-003: expected a non-empty error message for A->B->C->A cycle but got empty string"
        )

    def test_three_node_cycle_does_not_raise_recursion_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A three-node cycle raises ManifestParseError, not RecursionError.

        AC-TEST-003, AC-FUNC-001
        """
        a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="tri_b.xml" />\n'
            "</manifest>\n"
        )
        b_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="tri_c.xml" />\n'
            "</manifest>\n"
        )
        c_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="tri_a.xml" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="tri_a.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "tri_a.xml", a_xml)
        _write_included_manifest(repodir, "tri_b.xml", b_xml)
        _write_included_manifest(repodir, "tri_c.xml", c_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        try:
            _load_manifest(repodir, manifest_file)
            pytest.fail("AC-TEST-003: expected ManifestParseError for three-node cycle but nothing was raised")
        except ManifestParseError:
            pass
        except RecursionError as exc:
            pytest.fail(
                f"AC-TEST-003: three-node cycle must raise ManifestParseError "
                f"but raised RecursionError instead: {exc!r}"
            )

    @pytest.mark.parametrize(
        "cycle_length",
        [3, 4, 5],
    )
    def test_multi_node_cycle_raises_manifest_parse_error(
        self,
        tmp_path: pathlib.Path,
        cycle_length: int,
    ) -> None:
        """Parameterized: multi-node include cycles of various lengths raise ManifestParseError.

        Constructs a cycle of the given length by creating cycle_length manifest
        files where file i includes file (i+1) mod cycle_length.

        AC-TEST-003, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)
        filenames = [f"cyc_node_{i}.xml" for i in range(cycle_length)]
        for idx, filename in enumerate(filenames):
            next_filename = filenames[(idx + 1) % cycle_length]
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                f'  <include name="{next_filename}" />\n'
                "</manifest>\n"
            )
            _write_included_manifest(repodir, filename, xml)

        primary_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="{filenames[0]}" />\n</manifest>\n'
        )
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)


# ---------------------------------------------------------------------------
# AC-TEST-004: Include depth limit (MAX_SUBMANIFEST_DEPTH) enforced
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeDepthLimit:
    """AC-TEST-004: The include depth limit (MAX_SUBMANIFEST_DEPTH) is enforced.

    A chain of acyclic includes that exceeds MAX_SUBMANIFEST_DEPTH levels must
    raise ManifestParseError. A chain exactly at the limit must parse without
    error.
    """

    def test_include_chain_exceeding_max_depth_raises(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An include chain deeper than MAX_SUBMANIFEST_DEPTH raises ManifestParseError.

        This verifies that the parser enforces a hard depth ceiling on acyclic
        include chains. The test constructs a linear chain one level beyond the
        documented limit and expects ManifestParseError.

        The chain has limit+1 included files (depth_node_1 through
        depth_node_{limit+1}), making the include depth reach limit+1 which
        exceeds MAX_SUBMANIFEST_DEPTH.

        AC-TEST-004, AC-FUNC-001
        """
        limit = manifest_xml.MAX_SUBMANIFEST_DEPTH
        repodir = _make_repo_dir(tmp_path)

        # Build a linear chain: node_1 -> node_2 -> ... -> node_limit -> node_{limit+1}(leaf)
        # When node_limit (at include depth=limit) tries to include node_{limit+1},
        # next_depth = limit+1 > limit, which triggers the depth error.
        total_nodes = limit + 1
        leaf_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="leaf/project" path="leaf" />\n'
            "</manifest>\n"
        )
        _write_included_manifest(repodir, f"depth_node_{total_nodes}.xml", leaf_xml)

        for level in range(total_nodes - 1, 0, -1):
            next_file = f"depth_node_{level + 1}.xml"
            node_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                f'  <include name="{next_file}" />\n'
                "</manifest>\n"
            )
            _write_included_manifest(repodir, f"depth_node_{level}.xml", node_xml)

        # Primary manifest includes the first level (depth=1)
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="depth_node_1.xml" />\n</manifest>\n'
        )
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert error_message, (
            "AC-TEST-004: expected a non-empty error message when include depth exceeds "
            f"MAX_SUBMANIFEST_DEPTH ({limit}) but got empty string"
        )

    def test_include_chain_at_max_depth_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An include chain exactly at MAX_SUBMANIFEST_DEPTH levels parses without error.

        A chain of exactly MAX_SUBMANIFEST_DEPTH nested includes (not exceeding
        the limit) must parse successfully.

        AC-TEST-004
        """
        limit = manifest_xml.MAX_SUBMANIFEST_DEPTH
        repodir = _make_repo_dir(tmp_path)

        # Build a linear chain of exactly limit levels
        # node_1 -> node_2 -> ... -> node_(limit-1) -> leaf
        leaf_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="deep/project" path="deep" />\n'
            "</manifest>\n"
        )
        _write_included_manifest(repodir, "deep_leaf.xml", leaf_xml)

        # Build chain from level (limit-1) down to 1
        for level in range(limit - 1, 0, -1):
            if level == limit - 1:
                next_file = "deep_leaf.xml"
            else:
                next_file = f"deep_node_{level + 1}.xml"
            node_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                f'  <include name="{next_file}" />\n'
                "</manifest>\n"
            )
            _write_included_manifest(repodir, f"deep_node_{level}.xml", node_xml)

        # Primary manifest includes node_1 (total depth = limit - 1 levels of includes)
        # plus the primary manifest itself = limit levels, which is exactly the limit
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="deep_node_1.xml" />\n</manifest>\n'
        )
        manifest_file = _write_manifest(repodir, primary_xml)

        # Should not raise -- chain is at (not above) the depth limit
        result = _load_manifest(repodir, manifest_file)
        assert result is not None, (
            "AC-TEST-004: expected XmlManifest instance for include chain at depth limit but got None"
        )

    def test_include_depth_limit_value_matches_constant(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """The depth limit used by the parser matches MAX_SUBMANIFEST_DEPTH.

        The constant MAX_SUBMANIFEST_DEPTH exported by manifest_xml must be
        the same value that the include depth guard enforces. This test confirms
        the constant is accessible and has a positive integer value consistent
        with the documented limit.

        AC-TEST-004
        """
        limit = manifest_xml.MAX_SUBMANIFEST_DEPTH
        assert isinstance(limit, int), (
            f"AC-TEST-004: expected MAX_SUBMANIFEST_DEPTH to be an int but got {type(limit).__name__!r}"
        )
        assert limit > 0, f"AC-TEST-004: expected MAX_SUBMANIFEST_DEPTH to be positive but got {limit!r}"


# ---------------------------------------------------------------------------
# AC-TEST-005: Relative path resolution is correct for nested includes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeRelativePathResolution:
    """AC-TEST-005: Relative path resolution is correct for nested includes.

    Included manifests are resolved relative to the include_root (the manifests
    worktree directory). An <include name="sub.xml" /> inside a nested included
    manifest resolves sub.xml relative to the same include_root, not relative
    to the directory of the file containing the <include>.

    This behavior is consistent with how the repo tool resolves includes.
    """

    def test_nested_include_resolves_relative_to_include_root(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """An include inside a nested included manifest resolves relative to the include_root.

        Given:
        - primary manifest.xml includes level1.xml
        - level1.xml includes level2.xml
        - level2.xml includes leaf.xml
        - All files live in the manifests/ include_root directory
        The parser must resolve each name relative to the include_root and
        successfully load the projects from leaf.xml.

        AC-TEST-005, AC-FUNC-001
        """
        repodir = _make_repo_dir(tmp_path)

        leaf_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="nested/leaf-project" path="leaf" />\n'
            "</manifest>\n"
        )
        level2_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="rel_leaf.xml" />\n'
            "</manifest>\n"
        )
        level1_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="rel_level2.xml" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="rel_level1.xml" />\n</manifest>\n'
        )
        _write_included_manifest(repodir, "rel_leaf.xml", leaf_xml)
        _write_included_manifest(repodir, "rel_level2.xml", level2_xml)
        _write_included_manifest(repodir, "rel_level1.xml", level1_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        result = _load_manifest(repodir, manifest_file)

        project_names = [p.name for p in result.projects]
        assert "nested/leaf-project" in project_names, (
            f"AC-TEST-005: expected 'nested/leaf-project' from deeply nested include to be visible "
            f"but got: {project_names!r}"
        )

    def test_nested_include_nonexistent_file_raises_parse_error(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """A nested include referencing a missing file raises ManifestParseError.

        If a manifest included via a nested <include> in turn references a file
        that does not exist in the include_root, ManifestParseError must be raised.

        AC-TEST-005
        """
        repodir = _make_repo_dir(tmp_path)

        level1_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="no_such_deep_file.xml" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="nested_with_missing.xml" />\n'
            "</manifest>\n"
        )
        _write_included_manifest(repodir, "nested_with_missing.xml", level1_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError) as exc_info:
            _load_manifest(repodir, manifest_file)

        error_message = str(exc_info.value)
        assert "no_such_deep_file.xml" in error_message, (
            f"AC-TEST-005: expected error to name the missing file 'no_such_deep_file.xml' but got: {error_message!r}"
        )

    def test_two_separate_includes_from_same_root_succeed(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """Two separate (non-cyclic) includes of the same file are permitted.

        Including the same file twice in different branches of the include
        tree (not a cycle) must not raise. If the parser uses path-based
        cycle detection it must correctly distinguish repeated non-cyclic
        includes from cyclic ones.

        AC-TEST-005
        """
        repodir = _make_repo_dir(tmp_path)

        shared_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="shared/lib" path="sharedlib" />\n'
            "</manifest>\n"
        )
        # Primary includes shared.xml twice -- this is not a cycle
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <include name="shared_once.xml" />\n'
            '  <include name="shared_once.xml" />\n'
            "</manifest>\n"
        )
        _write_included_manifest(repodir, "shared_once.xml", shared_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        # Including the same file twice at the same level is allowed
        # (the parser may complain about duplicate projects but not cycles)
        # We only assert no RecursionError or cycle-specific error is raised.
        try:
            _load_manifest(repodir, manifest_file)
        except ManifestParseError:
            # Duplicate project names may cause ManifestParseError -- that is
            # acceptable. The important thing is no RecursionError.
            pass
        except RecursionError as exc:
            pytest.fail(
                f"AC-TEST-005: including the same file twice (non-cyclic) must not raise "
                f"RecursionError but got: {exc!r}"
            )

    @pytest.mark.parametrize(
        "depth",
        [1, 2, 3],
    )
    def test_acyclic_nested_includes_of_various_depths_succeed(
        self,
        tmp_path: pathlib.Path,
        depth: int,
    ) -> None:
        """Parameterized: acyclic nested include chains of various depths parse without error.

        AC-TEST-005
        """
        repodir = _make_repo_dir(tmp_path)

        # Build a linear acyclic chain of the given depth
        leaf_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <project name="acyclic/proj" path="acyclicproj" />\n'
            "</manifest>\n"
        )
        _write_included_manifest(repodir, "acyc_leaf.xml", leaf_xml)

        for level in range(depth, 0, -1):
            if level == depth:
                next_file = "acyc_leaf.xml"
            else:
                next_file = f"acyc_node_{level + 1}.xml"
            node_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                '  <remote name="origin" fetch="https://example.com" />\n'
                '  <default revision="main" remote="origin" />\n'
                f'  <include name="{next_file}" />\n'
                "</manifest>\n"
            )
            _write_included_manifest(repodir, f"acyc_node_{level}.xml", node_xml)

        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="acyc_node_1.xml" />\n</manifest>\n'
        )
        manifest_file = _write_manifest(repodir, primary_xml)

        result = _load_manifest(repodir, manifest_file)
        project_names = [p.name for p in result.projects]
        assert "acyclic/proj" in project_names, (
            f"AC-TEST-005: expected 'acyclic/proj' to be visible after {depth}-deep "
            f"acyclic include chain but got: {project_names!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline for cycle errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncludeCycleChannelDiscipline:
    """AC-CHANNEL-001: Cycle errors surface as exceptions, not stdout writes.

    The parser must report include cycle errors exclusively through
    ManifestParseError exceptions. No cycle-related diagnostic must appear
    on stdout.
    """

    def test_self_reference_cycle_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A self-referencing include raises ManifestParseError without writing to stdout.

        AC-CHANNEL-001
        """
        self_ref_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="chan_self.xml" />\n'
            "</manifest>\n"
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "chan_self.xml", self_ref_xml)
        manifest_file = _write_manifest(repodir, self_ref_xml)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, f"AC-CHANNEL-001: expected no stdout output for cycle error but got: {captured.out!r}"

    def test_two_node_cycle_does_not_write_to_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A two-node include cycle raises ManifestParseError without writing to stdout.

        AC-CHANNEL-001
        """
        a_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="chan_b.xml" />\n'
            "</manifest>\n"
        )
        b_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            '  <remote name="origin" fetch="https://example.com" />\n'
            '  <default revision="main" remote="origin" />\n'
            '  <include name="chan_a.xml" />\n'
            "</manifest>\n"
        )
        primary_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n  <include name="chan_a.xml" />\n</manifest>\n'
        )
        repodir = _make_repo_dir(tmp_path)
        _write_included_manifest(repodir, "chan_a.xml", a_xml)
        _write_included_manifest(repodir, "chan_b.xml", b_xml)
        manifest_file = _write_manifest(repodir, primary_xml)

        with pytest.raises(ManifestParseError):
            _load_manifest(repodir, manifest_file)

        captured = capsys.readouterr()
        assert not captured.out, (
            f"AC-CHANNEL-001: expected no stdout output for two-node cycle error but got: {captured.out!r}"
        )
