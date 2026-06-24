"""Unit tests for kanon_cli.commands.add collision detection, --force, and --dry-run.

Covers:
- Within-request collision detection (same name twice, case-normalisation)
- Against-existing-blocks collision detection (spec-canonical message wording)
- --force overwrite mutation of file content
- --dry-run diff rendering (added lines with +, removed lines with -)
- Source-name comparison uses derive_source_name for both directions

AC-TEST-001
"""

import argparse
import pathlib

import pytest

from kanon_cli.core.metadata import CatalogMetadata


def _make_metadata(
    name: str = "entry-a",
    url: str = "https://example.com/manifest-repo.git",
    version: str = "1.0.0",
) -> CatalogMetadata:
    """Build a minimal CatalogMetadata for test use."""
    return CatalogMetadata(
        name=name,
        display_name=f"{name} Display",
        description=f"Description of {name}.",
        version=version,
    )


def _make_triple_block(source_name: str, url: str, revision: str, path: str) -> str:
    """Build the five KANON_SOURCE_* lines as a block (with leading blank line)."""
    return (
        f"\nKANON_SOURCE_{source_name}_URL={url}\n"
        f"KANON_SOURCE_{source_name}_REF={revision}\n"
        f"KANON_SOURCE_{source_name}_PATH={path}\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://example.com\n"
    )


HEADER = (
    "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
    "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
    "KANON_MARKETPLACE_INSTALL=<true|false>\n"
)


@pytest.mark.unit
class TestWithinRequestCollision:
    """Within-request collision detection -- same name twice or normalised-same names."""

    def test_same_name_twice_raises_system_exit(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """kanon add a a (same name twice) hard-errors before any catalog work."""
        from kanon_cli.commands.add import _check_within_request_collisions

        with pytest.raises(SystemExit) as exc_info:
            _check_within_request_collisions(["a", "a"])
        assert exc_info.value.code != 0

    def test_same_name_twice_names_the_duplicate_in_stderr(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Error message names the duplicated entry."""
        from kanon_cli.commands.add import _check_within_request_collisions

        with pytest.raises(SystemExit):
            _check_within_request_collisions(["alpha", "alpha"])
        captured = capsys.readouterr()
        assert "alpha" in captured.err

    def test_same_name_twice_error_mentions_normalised_form(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Error message names the normalised source name."""
        from kanon_cli.commands.add import _check_within_request_collisions

        with pytest.raises(SystemExit):
            _check_within_request_collisions(["foo-bar", "foo-bar"])
        captured = capsys.readouterr()
        assert "foo_bar" in captured.err

    @pytest.mark.parametrize(
        "entries,shared_norm",
        [
            (["Foo-Bar", "foo-bar"], "foo_bar"),
            (["FOO", "foo"], "foo"),
            (["entry-A", "entry-a"], "entry_a"),
            (["Baz_Qux", "baz-qux"], "baz_qux"),
        ],
        ids=["mixed-case-hyphen", "upper-lower", "upper-lower-hyphen", "underscore-vs-hyphen"],
    )
    def test_normalised_same_source_name_raises(
        self,
        entries: list[str],
        shared_norm: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Two entries normalising to the same source name are a hard error.

        Error message names both inputs and the shared normalised form.
        """
        from kanon_cli.commands.add import _check_within_request_collisions

        with pytest.raises(SystemExit) as exc_info:
            _check_within_request_collisions(entries)
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert entries[0] in captured.err
        assert entries[1] in captured.err
        assert shared_norm in captured.err

    def test_distinct_names_no_error(self) -> None:
        """Two entries with distinct normalised names pass without error."""
        from kanon_cli.commands.add import _check_within_request_collisions

        _check_within_request_collisions(["entry-a", "entry-b"])

    def test_single_entry_no_error(self) -> None:
        """Single entry passes without error."""
        from kanon_cli.commands.add import _check_within_request_collisions

        _check_within_request_collisions(["only-one"])

    def test_empty_list_no_error(self) -> None:
        """Empty list passes without error."""
        from kanon_cli.commands.add import _check_within_request_collisions

        _check_within_request_collisions([])


@pytest.mark.unit
class TestSameNameGuardAndAutoSuffix:
    """Same-NAME guard (same source@ref re-add) vs cross-source auto-suffix (Section 4.2)."""

    def test_same_source_readdition_without_force_raises_system_exit(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Re-adding the SAME source@ref under the same alias without --force is a hard error."""
        from kanon_cli.commands.add import _emit_same_name_guard_error

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            HEADER
            + _make_triple_block(
                "entry_a",
                "https://example.com/repo.git",
                "refs/tags/1.0.0",
                "repo-specs/entry-a-marketplace.xml",
            ),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit) as exc_info:
            _emit_same_name_guard_error(
                kanon_file=kanon_file,
                source_name="entry_a",
                new_url="https://example.com/repo.git",
                new_ref="==2.0.0",
                new_path="repo-specs/entry-a-marketplace.xml",
            )
        assert exc_info.value.code != 0

    def test_same_name_guard_error_has_diff_and_guidance(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The guard error names the alias, renders existing/requested coords, and guides remediation."""
        from kanon_cli.commands.add import _emit_same_name_guard_error

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            HEADER
            + _make_triple_block(
                "foo",
                "https://existing.example.com/repo.git",
                "refs/tags/1.0.0",
                "repo-specs/foo-marketplace.xml",
            ),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit):
            _emit_same_name_guard_error(
                kanon_file=kanon_file,
                source_name="foo",
                new_url="https://existing.example.com/repo.git",
                new_ref="refs/tags/2.0.0",
                new_path="repo-specs/foo-marketplace.xml",
            )
        captured = capsys.readouterr()
        assert "foo" in captured.err
        assert "https://existing.example.com/repo.git" in captured.err
        assert "refs/tags/1.0.0" in captured.err
        assert "refs/tags/2.0.0" in captured.err
        assert "repo-specs/foo-marketplace.xml" in captured.err

        assert "--force" in captured.err or "kanon remove" in captured.err

    def test_cross_source_collision_is_not_an_error_but_auto_suffixes(self, tmp_path: pathlib.Path) -> None:
        """A taken bare alias from a DIFFERENT source auto-suffixes instead of erroring."""
        from kanon_cli.commands.add import _read_all_source_aliases, _resolve_entry_alias

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            HEADER
            + _make_triple_block(
                "entry_a",
                "https://example.com/old.git",
                "refs/tags/1.0.0",
                "repo-specs/entry-a-marketplace.xml",
            ),
            encoding="utf-8",
        )
        existing = _read_all_source_aliases(kanon_file)
        alias, mode = _resolve_entry_alias(
            existing,
            base_alias="entry_a",
            entry_url="https://example.com/new.git",
            entry_ref="refs/tags/2.0.0",
            force=False,
        )

        assert mode == "new"
        assert alias == "entry_a_new"

    def test_fresh_alias_resolves_new(self, tmp_path: pathlib.Path) -> None:
        """A base alias not present in the file resolves to itself (mode 'new')."""
        from kanon_cli.commands.add import _read_all_source_aliases, _resolve_entry_alias

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(HEADER, encoding="utf-8")

        existing = _read_all_source_aliases(kanon_file)
        alias, mode = _resolve_entry_alias(
            existing,
            base_alias="fresh_entry",
            entry_url="https://example.com/new.git",
            entry_ref="refs/tags/1.0.0",
            force=False,
        )
        assert (alias, mode) == ("fresh_entry", "new")

    def test_force_same_source_readdition_is_overwrite(self, tmp_path: pathlib.Path) -> None:
        """With --force, re-adding the same source@ref resolves to a force_overwrite."""
        from kanon_cli.commands.add import _read_all_source_aliases, _resolve_entry_alias

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            HEADER
            + _make_triple_block(
                "entry_a",
                "https://example.com/repo.git",
                "refs/tags/2.0.0",
                "repo-specs/entry-a-marketplace.xml",
            ),
            encoding="utf-8",
        )
        existing = _read_all_source_aliases(kanon_file)
        alias, mode = _resolve_entry_alias(
            existing,
            base_alias="entry_a",
            entry_url="https://example.com/repo.git",
            entry_ref="refs/tags/2.0.0",
            force=True,
        )
        assert (alias, mode) == ("entry_a", "force_overwrite")


@pytest.mark.unit
class TestForceOverwrite:
    """--force replaces the existing three lines, preserving surrounding content."""

    def test_force_overwrites_existing_triple(self, tmp_path: pathlib.Path) -> None:
        """With --force, existing triple lines are replaced by the new triple."""
        from kanon_cli.commands.add import _overwrite_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            HEADER
            + _make_triple_block(
                "entry_a",
                "https://old.example.com/repo.git",
                "refs/tags/1.0.0",
                "repo-specs/entry-a-marketplace.xml",
            )
        )

        _overwrite_source_block(
            dest=kanon_file,
            source_name="entry_a",
            lines=[
                "KANON_SOURCE_entry_a_URL=https://new.example.com/repo.git",
                "KANON_SOURCE_entry_a_REF=refs/tags/2.0.0",
                "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml",
                "KANON_SOURCE_entry_a_NAME=entry_a",
                "KANON_SOURCE_entry_a_GITBASE=https://example.com",
            ],
        )

        content = kanon_file.read_text()
        assert "KANON_SOURCE_entry_a_URL=https://new.example.com/repo.git" in content
        assert "KANON_SOURCE_entry_a_REF=refs/tags/2.0.0" in content
        assert "https://old.example.com/repo.git" not in content
        assert "refs/tags/1.0.0" not in content

    def test_force_preserves_surrounding_content(self, tmp_path: pathlib.Path) -> None:
        """Surrounding content (header, other triples) is preserved byte-for-byte."""
        from kanon_cli.commands.add import _overwrite_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            HEADER
            + _make_triple_block(
                "other_entry",
                "https://other.example.com/repo.git",
                "refs/tags/3.0.0",
                "repo-specs/other-marketplace.xml",
            )
            + _make_triple_block(
                "entry_a",
                "https://old.example.com/repo.git",
                "refs/tags/1.0.0",
                "repo-specs/entry-a-marketplace.xml",
            )
        )

        _overwrite_source_block(
            dest=kanon_file,
            source_name="entry_a",
            lines=[
                "KANON_SOURCE_entry_a_URL=https://new.example.com/repo.git",
                "KANON_SOURCE_entry_a_REF=refs/tags/2.0.0",
                "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml",
                "KANON_SOURCE_entry_a_NAME=entry_a",
                "KANON_SOURCE_entry_a_GITBASE=https://example.com",
            ],
        )

        content = kanon_file.read_text()

        assert "GITBASE=" in content
        assert "KANON_SOURCE_other_entry_URL=https://other.example.com/repo.git" in content
        assert "KANON_SOURCE_other_entry_REF=refs/tags/3.0.0" in content

        assert "KANON_SOURCE_entry_a_URL=https://new.example.com/repo.git" in content
        assert "KANON_SOURCE_entry_a_REF=refs/tags/2.0.0" in content

        assert "https://old.example.com/repo.git" not in content
        assert "refs/tags/1.0.0" not in content

    def test_force_overwrite_preserves_line_order(self, tmp_path: pathlib.Path) -> None:
        """Line order of remaining content is preserved after overwrite."""
        from kanon_cli.commands.add import _overwrite_source_block

        kanon_file = tmp_path / ".kanon"
        original = (
            "HEADER_LINE=value\n"
            "\n"
            "KANON_SOURCE_entry_a_URL=https://old.example.com/repo.git\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml\n"
            "KANON_SOURCE_entry_a_NAME=entry_a\n"
            "KANON_SOURCE_entry_a_GITBASE=https://example.com\n"
            "\n"
            "OTHER_VAR=other_value\n"
        )
        kanon_file.write_text(original)

        _overwrite_source_block(
            dest=kanon_file,
            source_name="entry_a",
            lines=[
                "KANON_SOURCE_entry_a_URL=https://new.example.com/repo.git",
                "KANON_SOURCE_entry_a_REF=refs/tags/2.0.0",
                "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml",
                "KANON_SOURCE_entry_a_NAME=entry_a",
                "KANON_SOURCE_entry_a_GITBASE=https://example.com",
            ],
        )

        content = kanon_file.read_text()

        pos_header = content.index("HEADER_LINE=")
        pos_url = content.index("KANON_SOURCE_entry_a_URL=https://new")
        pos_other = content.index("OTHER_VAR=")
        assert pos_header < pos_url < pos_other

    def test_force_prints_summary_to_stdout(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        """_overwrite_source_block prints a summary line to stdout."""
        from kanon_cli.commands.add import _overwrite_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            HEADER
            + _make_triple_block(
                "entry_a",
                "https://old.example.com/repo.git",
                "refs/tags/1.0.0",
                "repo-specs/entry-a-marketplace.xml",
            )
        )

        _overwrite_source_block(
            dest=kanon_file,
            source_name="entry_a",
            lines=[
                "KANON_SOURCE_entry_a_URL=https://new.example.com/repo.git",
                "KANON_SOURCE_entry_a_REF=refs/tags/2.0.0",
                "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml",
                "KANON_SOURCE_entry_a_NAME=entry_a",
                "KANON_SOURCE_entry_a_GITBASE=https://example.com",
            ],
        )
        captured = capsys.readouterr()
        assert "entry_a" in captured.out


@pytest.mark.unit
class TestDryRunDiff:
    """--dry-run renders a diff without modifying the destination file."""

    def test_dry_run_diff_lines_have_plus_prefix_for_new_entry(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--dry-run diff shows '+' prefix for each added line (no collision)."""
        from kanon_cli.commands.add import _render_dry_run_diff

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(HEADER)

        lines = [
            "KANON_SOURCE_entry_a_URL=https://example.com/repo.git",
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0",
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml",
            "KANON_SOURCE_entry_a_NAME=entry_a",
            "KANON_SOURCE_entry_a_GITBASE=https://example.com",
        ]

        _render_dry_run_diff(
            dest=kanon_file,
            source_name="entry_a",
            lines=lines,
            force=False,
        )
        captured = capsys.readouterr()
        for line in lines:
            assert f"+{line}" in captured.out

    def test_dry_run_does_not_modify_file_content(self, tmp_path: pathlib.Path) -> None:
        """File content is unchanged after --dry-run (verified by text equality and SHA-256)."""
        import hashlib

        from kanon_cli.commands.add import _render_dry_run_diff

        kanon_file = tmp_path / ".kanon"
        original_content = HEADER
        kanon_file.write_text(original_content)
        hash_before = hashlib.sha256(kanon_file.read_bytes()).hexdigest()

        lines = [
            "KANON_SOURCE_entry_a_URL=https://example.com/repo.git",
            "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0",
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml",
            "KANON_SOURCE_entry_a_NAME=entry_a",
            "KANON_SOURCE_entry_a_GITBASE=https://example.com",
        ]

        _render_dry_run_diff(
            dest=kanon_file,
            source_name="entry_a",
            lines=lines,
            force=False,
        )

        hash_after = hashlib.sha256(kanon_file.read_bytes()).hexdigest()
        assert kanon_file.read_text() == original_content
        assert hash_before == hash_after, (
            f"--dry-run modified file content: SHA-256 changed from {hash_before} to {hash_after}"
        )

    def test_dry_run_force_shows_minus_for_removed_and_plus_for_new(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--dry-run --force diff shows '-' for removed lines and '+' for replacement lines."""
        from kanon_cli.commands.add import _render_dry_run_diff

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            HEADER
            + _make_triple_block(
                "entry_a",
                "https://old.example.com/repo.git",
                "refs/tags/1.0.0",
                "repo-specs/entry-a-marketplace.xml",
            )
        )

        new_lines = [
            "KANON_SOURCE_entry_a_URL=https://new.example.com/repo.git",
            "KANON_SOURCE_entry_a_REF=refs/tags/2.0.0",
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml",
            "KANON_SOURCE_entry_a_NAME=entry_a",
            "KANON_SOURCE_entry_a_GITBASE=https://example.com",
        ]

        _render_dry_run_diff(
            dest=kanon_file,
            source_name="entry_a",
            lines=new_lines,
            force=True,
        )
        captured = capsys.readouterr()

        assert "-KANON_SOURCE_entry_a_URL=https://old.example.com/repo.git" in captured.out
        assert "-KANON_SOURCE_entry_a_REF=refs/tags/1.0.0" in captured.out

        assert "+KANON_SOURCE_entry_a_URL=https://new.example.com/repo.git" in captured.out
        assert "+KANON_SOURCE_entry_a_REF=refs/tags/2.0.0" in captured.out

    def test_dry_run_force_does_not_modify_file(self, tmp_path: pathlib.Path) -> None:
        """--dry-run --force does not modify the file."""
        from kanon_cli.commands.add import _render_dry_run_diff

        kanon_file = tmp_path / ".kanon"
        original = HEADER + _make_triple_block(
            "entry_a",
            "https://old.example.com/repo.git",
            "refs/tags/1.0.0",
            "repo-specs/entry-a-marketplace.xml",
        )
        kanon_file.write_text(original)

        new_lines = [
            "KANON_SOURCE_entry_a_URL=https://new.example.com/repo.git",
            "KANON_SOURCE_entry_a_REF=refs/tags/2.0.0",
            "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml",
            "KANON_SOURCE_entry_a_NAME=entry_a",
            "KANON_SOURCE_entry_a_GITBASE=https://example.com",
        ]

        _render_dry_run_diff(
            dest=kanon_file,
            source_name="entry_a",
            lines=new_lines,
            force=True,
        )

        assert kanon_file.read_text() == original


@pytest.mark.unit
class TestReadExistingTripleBlock:
    """_read_existing_source_block extracts the three lines for a source name."""

    def test_reads_existing_triple(self, tmp_path: pathlib.Path) -> None:
        """Returns the three KANON_SOURCE_<name>_* lines from a file."""
        from kanon_cli.commands.add import _read_existing_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            HEADER
            + _make_triple_block(
                "entry_a",
                "https://example.com/repo.git",
                "refs/tags/1.0.0",
                "repo-specs/entry-a-marketplace.xml",
            )
        )

        url, revision, path = _read_existing_source_block(kanon_file, "entry_a")
        assert url == "https://example.com/repo.git"
        assert revision == "refs/tags/1.0.0"
        assert path == "repo-specs/entry-a-marketplace.xml"

    def test_returns_none_tuple_when_not_found(self, tmp_path: pathlib.Path) -> None:
        """Returns (None, None, None) when source name is not in the file."""
        from kanon_cli.commands.add import _read_existing_source_block

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(HEADER)

        result = _read_existing_source_block(kanon_file, "missing_entry")
        assert result == (None, None, None)

    def test_returns_none_tuple_when_file_absent(self, tmp_path: pathlib.Path) -> None:
        """Returns (None, None, None) when the file does not exist."""
        from kanon_cli.commands.add import _read_existing_source_block

        kanon_file = tmp_path / ".kanon"
        result = _read_existing_source_block(kanon_file, "entry_a")
        assert result == (None, None, None)


@pytest.mark.unit
class TestAddSubparserFlags:
    """--dry-run and --force flags are registered on the 'kanon add' subparser."""

    def test_dry_run_flag_registered(self) -> None:
        """--dry-run flag is registered and defaults to False."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "https://x.git@main"])
        assert args.dry_run is False

    def test_dry_run_flag_sets_true(self) -> None:
        """--dry-run flag sets dry_run=True when supplied."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "https://x.git@main", "--dry-run"])
        assert args.dry_run is True

    def test_force_flag_registered(self) -> None:
        """--force flag is registered and defaults to False."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "https://x.git@main"])
        assert args.force is False

    def test_force_flag_sets_true(self) -> None:
        """--force flag sets force=True when supplied."""
        from kanon_cli.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["add", "entry-a", "--catalog-source", "https://x.git@main", "--force"])
        assert args.force is True

    def test_help_mentions_dry_run(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help text describes --dry-run."""
        import io

        from kanon_cli.cli import build_parser

        parser = build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                add_parser = action.choices["add"]
                buf = io.StringIO()
                add_parser.print_help(file=buf)
                assert "--dry-run" in buf.getvalue()
                return
        raise AssertionError("add subparser not found")

    def test_help_mentions_force(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help text describes --force."""
        import io

        from kanon_cli.cli import build_parser

        parser = build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                add_parser = action.choices["add"]
                buf = io.StringIO()
                add_parser.print_help(file=buf)
                assert "--force" in buf.getvalue()
                return
        raise AssertionError("add subparser not found")

    def test_help_mentions_collision_detection(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help text references collision-detection pre-flight."""
        import io

        from kanon_cli.cli import build_parser

        parser = build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                add_parser = action.choices["add"]
                buf = io.StringIO()
                add_parser.print_help(file=buf)
                help_text = buf.getvalue()

                assert (
                    "collision" in help_text.lower() or "overwrite" in help_text.lower() or "force" in help_text.lower()
                )
                return
        raise AssertionError("add subparser not found")


@pytest.mark.unit
class TestRunAddDryRunAndForcePaths:
    """run_add wires --dry-run and --force to the correct internal helpers."""

    def _make_run_add_args(
        self,
        tmp_path: pathlib.Path,
        entry: str = "entry-a",
        force: bool = False,
        dry_run: bool = False,
    ) -> argparse.Namespace:
        """Build a minimal args Namespace for run_add."""
        return argparse.Namespace(
            catalog_source="https://example.com/repo.git@main",
            kanon_file=str(tmp_path / ".kanon"),
            entries=[entry],
            force=force,
            dry_run=dry_run,
            alias_override=None,
        )

    def _make_metadata(self, name: str = "entry-a") -> CatalogMetadata:
        return CatalogMetadata(
            name=name,
            display_name=f"{name} Display",
            description=f"Description of {name}.",
            version="1.0.0",
        )

    def _make_xml_file(self, tmp_path: pathlib.Path, name: str = "entry-a") -> pathlib.Path:
        """Create a minimal marketplace XML file and return its path."""
        import textwrap

        xml_path = tmp_path / "repo" / "repo-specs" / f"{name}-marketplace.xml"
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(
            textwrap.dedent(f"""\
                <?xml version="1.0" encoding="UTF-8"?>
                <manifest>
                  <catalog-metadata>
                    <name>{name}</name>
                    <display-name>{name} Display</display-name>
                    <description>Test.</description>
                    <version>1.0.0</version>
                    <type>plugin</type>
                    <owner-name>Owner</owner-name>
                    <owner-email>o@example.com</owner-email>
                    <keywords>test</keywords>
                  </catalog-metadata>
                </manifest>
            """)
        )
        return xml_path

    def test_run_add_dry_run_calls_render_not_append(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With --dry-run, _render_dry_run_diff is called, not _append_triple_block."""
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
        )
        original_content = kanon_file.read_text()

        meta = self._make_metadata("entry-a")
        xml_path = self._make_xml_file(tmp_path, "entry-a")
        manifest_root = tmp_path / "repo"
        args = self._make_run_add_args(tmp_path, dry_run=True)

        with (
            patch(
                "kanon_cli.commands.add._resolve_manifest_repo_for_add",
                return_value=(manifest_root, "https://example.com/repo.git", "main"),
            ),
            patch(
                "kanon_cli.commands.add._build_entry_catalog",
                return_value=[(meta, xml_path, "https://example.com/repo.git")],
            ),
            patch(
                "kanon_cli.commands.add._resolve_spec",
                return_value="refs/tags/1.0.0",
            ),
        ):
            result = run_add(args)

        assert result == 0

        assert kanon_file.read_text() == original_content

        captured = capsys.readouterr()
        assert "+KANON_SOURCE_entry_a_URL=" in captured.out

    def test_run_add_force_existing_block_calls_overwrite(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With --force and a re-add of the same source@ref, _overwrite_source_block is called.

        The existing block is keyed by the same alias and the same source URL +
        resolved ref the add resolves to, so the add is a re-add of the existing
        package (spec Section 4.2 force path), not a cross-source collision that
        would auto-suffix. The overwrite refreshes the block (here, its PATH).
        """
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
            "\n"
            "KANON_SOURCE_entry_a_URL=https://example.com/repo.git\n"
            "KANON_SOURCE_entry_a_REF=refs/tags/2.0.0\n"
            "KANON_SOURCE_entry_a_PATH=repo-specs/stale-path.xml\n"
            "KANON_SOURCE_entry_a_NAME=entry_a\n"
            "KANON_SOURCE_entry_a_GITBASE=https://example.com\n",
            encoding="utf-8",
        )

        meta = self._make_metadata("entry-a")
        xml_path = self._make_xml_file(tmp_path, "entry-a")
        manifest_root = tmp_path / "repo"
        args = self._make_run_add_args(tmp_path, force=True)

        with (
            patch(
                "kanon_cli.commands.add._resolve_manifest_repo_for_add",
                return_value=(manifest_root, "https://example.com/repo.git", "main"),
            ),
            patch(
                "kanon_cli.commands.add._build_entry_catalog",
                return_value=[(meta, xml_path, "https://example.com/repo.git")],
            ),
            patch(
                "kanon_cli.commands.add._resolve_spec",
                return_value="refs/tags/2.0.0",
            ),
        ):
            result = run_add(args)

        assert result == 0

        content = kanon_file.read_text()
        assert "KANON_SOURCE_entry_a_PATH=repo-specs/entry-a-marketplace.xml" in content
        assert "repo-specs/stale-path.xml" not in content
        assert "KANON_SOURCE_entry_a_repo_URL=" not in content

    def test_run_add_force_new_entry_calls_append(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With --force but no existing block, _append_triple_block is called."""
        from unittest.mock import patch

        from kanon_cli.commands.add import run_add

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=<YOUR_GIT_ORG_BASE_URL>\n"
            "CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces\n"
            "KANON_MARKETPLACE_INSTALL=<true|false>\n"
        )

        meta = self._make_metadata("entry-a")
        xml_path = self._make_xml_file(tmp_path, "entry-a")
        manifest_root = tmp_path / "repo"
        args = self._make_run_add_args(tmp_path, force=True)

        with (
            patch(
                "kanon_cli.commands.add._resolve_manifest_repo_for_add",
                return_value=(manifest_root, "https://example.com/repo.git", "main"),
            ),
            patch(
                "kanon_cli.commands.add._build_entry_catalog",
                return_value=[(meta, xml_path, "https://example.com/repo.git")],
            ),
            patch(
                "kanon_cli.commands.add._resolve_spec",
                return_value="refs/tags/1.0.0",
            ),
        ):
            result = run_add(args)

        assert result == 0

        content = kanon_file.read_text()
        assert "KANON_SOURCE_entry_a_REF=refs/tags/1.0.0" in content
