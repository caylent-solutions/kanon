"""Integration tests for ``kanon search --format json``.

The catalog discovery command was renamed from ``list`` to ``search`` in the
3.0.0 release; the ``--format json`` behaviour and the ``KANON_LIST_FORMAT``
env var are unchanged.

Builds temporary local file:// manifest-repo fixtures (committed git repos
with *-marketplace.xml files) and invokes 'kanon search --format json
--catalog-source <file>@<ref>' via subprocess.run.

Covers AC-TEST-002, AC-CYCLE-001:
- Default mode JSON output: three entries, JSON array of {name, display-name,
  type, description, version}.
- -A/--all --format json output: {name, version, ref, sha} array.
- --format json --limit 2 combination with -A/--all.
- KANON_LIST_FORMAT=json env var end-to-end.
- --format json --tree mutual-exclusion error.
- Empty catalog with --format json emits [] exit 0.
"""

import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"


_MARKETPLACE_XML_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <catalog-metadata>
        <name>{name}</name>
        <display-name>{name} Display</display-name>
        <description>Integration test entry for {name}.</description>
        <version>{version}</version>
        <type>plugin</type>
        <owner-name>Integration Tester</owner-name>
        <owner-email>integration@example.com</owner-email>
        <keywords>integration, test</keywords>
      </catalog-metadata>
    </manifest>
""")


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with non-zero exit code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with test user config.

    Args:
        work_dir: The directory to initialise as a git repo.
    """
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the bare path.

    Args:
        work_dir: Non-bare working directory to clone from.
        bare_dir: Destination path for the bare clone.

    Returns:
        The resolved absolute path to the bare clone.
    """
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def _write_marketplace_xml(repo_specs: pathlib.Path, name: str, version: str) -> None:
    """Write a *-marketplace.xml file under repo_specs/<name>/.

    Args:
        repo_specs: The repo-specs directory.
        name: Catalog entry name.
        version: Version string to embed.
    """
    entry_dir = repo_specs / name
    entry_dir.mkdir(parents=True, exist_ok=True)
    xml_path = entry_dir / f"{name}-marketplace.xml"
    xml_path.write_text(_MARKETPLACE_XML_TEMPLATE.format(name=name, version=version))


def _commit_and_tag(work_dir: pathlib.Path, tag: str, message: str) -> None:
    """Stage all, commit with message, and tag at that commit.

    Args:
        work_dir: The working directory to commit in.
        tag: Git tag name.
        message: Commit message.
    """
    _git(["add", "-A"], cwd=work_dir)
    _git(["commit", "--allow-empty", "-m", message], cwd=work_dir)
    _git(["tag", tag], cwd=work_dir)


def _build_single_version_manifest_repo(
    tmp_path: pathlib.Path,
    entry_names: list[str],
    version: str = "1.0.0",
) -> pathlib.Path:
    """Build a bare git repo with one commit and no version tags.

    Used for default-mode JSON tests where -A/--all is not needed.

    Args:
        tmp_path: Temporary directory root.
        entry_names: Catalog entry names to include.
        version: Version string to embed in each XML.

    Returns:
        Path to the bare git repository.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    repo_specs = work_dir / "repo-specs"
    (repo_specs / ".gitkeep").parent.mkdir(parents=True, exist_ok=True)
    (repo_specs / ".gitkeep").write_text("")

    for name in entry_names:
        _write_marketplace_xml(repo_specs, name, version)

    _git(["add", "."], cwd=work_dir)
    _git(["commit", "-m", "Add catalog entries"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, tmp_path / "bare.git")
    return bare_dir


def _build_multi_version_manifest_repo(
    tmp_path: pathlib.Path,
    entry_names: list[str],
    tag_versions: list[str],
) -> pathlib.Path:
    """Build a bare git repo with one tagged commit per version.

    Args:
        tmp_path: Temporary directory root.
        entry_names: Catalog entry names to include.
        tag_versions: Version strings to tag (oldest first).

    Returns:
        Path to the bare git repository.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _init_git_work_dir(work_dir)

    (work_dir / "README.md").write_text("manifest repo\n")
    _git(["add", "README.md"], cwd=work_dir)
    _git(["commit", "-m", "init"], cwd=work_dir)

    for version in tag_versions:
        repo_specs = work_dir / "repo-specs"
        for name in entry_names:
            _write_marketplace_xml(repo_specs, name, version)
        _commit_and_tag(work_dir, version, f"release {version}")

    bare_dir = _clone_as_bare(work_dir, tmp_path / "bare.git")
    return bare_dir


def _kanon_list(
    bare_repo: pathlib.Path,
    extra_args: list[str] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run 'kanon search' against a bare repo and return the process.

    The catalog discovery command was renamed from 'list' to 'search' in the
    3.0.0 release; the JSON-format behaviour (the --format flag and the
    KANON_LIST_FORMAT env var) is unchanged.

    Args:
        bare_repo: Path to the bare git repository.
        extra_args: Additional CLI arguments (appended after --catalog-source).
        env_overrides: Environment variable overrides.

    Returns:
        The completed subprocess.
    """
    catalog_source = f"file://{bare_repo}@main"
    cmd = [
        sys.executable,
        "-m",
        "kanon_cli",
        "search",
        "--catalog-source",
        catalog_source,
    ]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(bare_repo.parent),
        env=env,
    )


@pytest.mark.integration
class TestDefaultModeJsonFormat:
    """AC-TEST-002, AC-FUNC-003: JSON array of {name, display-name, type, description, version}."""

    def test_three_entries_produce_three_element_array(self, tmp_path):
        """Three catalog entries produce a three-element JSON array."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha", "beta", "gamma"])
        proc = _kanon_list(bare_repo, extra_args=["--format", "json"])

        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        parsed = json.loads(proc.stdout)
        assert len(parsed) == 3

    def test_json_output_has_required_keys(self, tmp_path):
        """Each JSON object has {name, display-name, type, description, version}."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha"])
        proc = _kanon_list(bare_repo, extra_args=["--format", "json"])

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        assert len(parsed) == 1
        assert set(parsed[0].keys()) == {"name", "display-name", "type", "description", "version"}

    def test_json_name_field_matches_entry_name(self, tmp_path):
        """The 'name' field in JSON matches the catalog entry name."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha"])
        proc = _kanon_list(bare_repo, extra_args=["--format", "json"])

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        assert parsed[0]["name"] == "alpha"

    def test_json_type_field_is_plugin(self, tmp_path):
        """The 'type' field matches the XML type element."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha"])
        proc = _kanon_list(bare_repo, extra_args=["--format", "json"])

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        assert parsed[0]["type"] == "plugin"

    def test_json_version_field_matches_xml_version(self, tmp_path):
        """The 'version' field matches the version in the XML."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha"], version="3.7.2")
        proc = _kanon_list(bare_repo, extra_args=["--format", "json"])

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        assert parsed[0]["version"] == "3.7.2"

    def test_json_array_is_sorted_lexicographically(self, tmp_path):
        """Entries appear in lexicographic order by name."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["gamma", "alpha", "beta"])
        proc = _kanon_list(bare_repo, extra_args=["--format", "json"])

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        names = [obj["name"] for obj in parsed]
        assert names == sorted(names)

    def test_json_output_ends_with_newline(self, tmp_path):
        """AC-FUNC-008: stdout ends with exactly one newline."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha"])
        proc = _kanon_list(bare_repo, extra_args=["--format", "json"])

        assert proc.returncode == 0
        assert proc.stdout.endswith("\n")
        assert not proc.stdout.endswith("\n\n")

    def test_json_output_parseable_by_json_loads(self, tmp_path):
        """json.loads succeeds on the full stdout."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha", "beta", "gamma"])
        proc = _kanon_list(bare_repo, extra_args=["--format", "json"])

        assert proc.returncode == 0

        parsed = json.loads(proc.stdout)
        assert isinstance(parsed, list)


@pytest.mark.integration
class TestDetailModeJsonFormat:
    """AC-FUNC-004: --format json --detail emits the same shape as default mode."""

    def test_detail_and_default_produce_same_json(self, tmp_path):
        """--detail flag does not change the JSON shape."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha", "beta"])

        proc_default = _kanon_list(bare_repo, extra_args=["--format", "json"])
        proc_detail = _kanon_list(bare_repo, extra_args=["--format", "json", "--detail"])

        assert proc_default.returncode == 0
        assert proc_detail.returncode == 0
        parsed_default = json.loads(proc_default.stdout)
        parsed_detail = json.loads(proc_detail.stdout)
        assert parsed_default == parsed_detail


@pytest.mark.integration
class TestAllVersionsModeJsonFormat:
    """AC-FUNC-005, AC-CYCLE-001: JSON array of {name, version, ref, sha}."""

    def test_all_versions_json_parseable(self, tmp_path):
        """-A/--all --format json produces parseable JSON."""
        bare_repo = _build_multi_version_manifest_repo(
            tmp_path, ["alpha", "beta", "gamma"], ["1.0.0", "2.0.0", "3.0.0", "4.0.0"]
        )
        proc = _kanon_list(bare_repo, extra_args=["--all", "--format", "json"])

        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        parsed = json.loads(proc.stdout)
        assert isinstance(parsed, list)

    def test_all_versions_json_has_required_keys(self, tmp_path):
        """Each object has {name, version, ref, sha}."""
        bare_repo = _build_multi_version_manifest_repo(tmp_path, ["alpha"], ["1.0.0", "2.0.0"])
        proc = _kanon_list(bare_repo, extra_args=["--all", "--format", "json"])

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        assert len(parsed) > 0
        assert set(parsed[0].keys()) == {"name", "version", "ref", "sha"}

    def test_all_versions_json_three_entries_four_versions(self, tmp_path):
        """3 entries x 4 versions = 12 objects in JSON array."""
        bare_repo = _build_multi_version_manifest_repo(
            tmp_path,
            ["alpha", "beta", "gamma"],
            ["1.0.0", "2.0.0", "3.0.0", "4.0.0"],
        )
        proc = _kanon_list(bare_repo, extra_args=["--all", "--format", "json"])

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        assert len(parsed) == 12

    def test_all_versions_json_ref_starts_with_refs_tags(self, tmp_path):
        """The 'ref' field starts with 'refs/tags/'."""
        bare_repo = _build_multi_version_manifest_repo(tmp_path, ["alpha"], ["1.0.0"])
        proc = _kanon_list(bare_repo, extra_args=["--all", "--format", "json"])

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        assert all(obj["ref"].startswith("refs/tags/") for obj in parsed)

    def test_all_versions_json_sha_is_non_empty_string(self, tmp_path):
        """The 'sha' field is a non-empty string."""
        bare_repo = _build_multi_version_manifest_repo(tmp_path, ["alpha"], ["1.0.0"])
        proc = _kanon_list(bare_repo, extra_args=["--all", "--format", "json"])

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        assert all(isinstance(obj["sha"], str) and len(obj["sha"]) > 0 for obj in parsed)

    def test_all_versions_limit_with_json_format(self, tmp_path):
        """AC-CYCLE-001: -A/--all --format json --limit 2 returns 2 versions x N entries."""
        bare_repo = _build_multi_version_manifest_repo(
            tmp_path,
            ["alpha", "beta", "gamma"],
            ["1.0.0", "2.0.0", "3.0.0", "4.0.0"],
        )
        proc = _kanon_list(
            bare_repo,
            extra_args=["--all", "--format", "json", "--limit", "2"],
        )

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)

        assert len(parsed) == 6

    def test_all_versions_json_output_ends_with_newline(self, tmp_path):
        """AC-FUNC-008: stdout ends with exactly one newline."""
        bare_repo = _build_multi_version_manifest_repo(tmp_path, ["alpha"], ["1.0.0"])
        proc = _kanon_list(bare_repo, extra_args=["--all", "--format", "json"])

        assert proc.returncode == 0
        assert proc.stdout.endswith("\n")
        assert not proc.stdout.endswith("\n\n")


@pytest.mark.integration
class TestEnvVarJsonFormatIntegration:
    """AC-FUNC-002, AC-CYCLE-001: env-var sets format end-to-end."""

    def test_env_var_json_produces_parseable_json(self, tmp_path):
        """KANON_LIST_FORMAT=json produces JSON without --format flag."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha", "beta"])
        proc = _kanon_list(bare_repo, env_overrides={"KANON_LIST_FORMAT": "json"})

        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        parsed = json.loads(proc.stdout)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_cli_flag_takes_precedence_over_env_var(self, tmp_path):
        """AC-CYCLE-001: CLI --format names wins over KANON_LIST_FORMAT=json."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha"])
        proc = _kanon_list(
            bare_repo,
            extra_args=["--format", "names"],
            env_overrides={"KANON_LIST_FORMAT": "json"},
        )

        assert proc.returncode == 0

        lines = proc.stdout.strip().splitlines()
        assert lines == ["alpha"]

        try:
            parsed = json.loads(proc.stdout)
            assert not (isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict))
        except json.JSONDecodeError:
            pass

    def test_env_var_json_with_all_versions(self, tmp_path):
        """AC-CYCLE-001: KANON_LIST_FORMAT=json + -A/--all produces {name, version, ref, sha} array."""
        bare_repo = _build_multi_version_manifest_repo(tmp_path, ["alpha"], ["1.0.0", "2.0.0"])
        proc = _kanon_list(
            bare_repo,
            extra_args=["--all"],
            env_overrides={"KANON_LIST_FORMAT": "json"},
        )

        assert proc.returncode == 0
        parsed = json.loads(proc.stdout)
        assert isinstance(parsed, list)
        assert set(parsed[0].keys()) == {"name", "version", "ref", "sha"}


@pytest.mark.integration
class TestJsonTreeMutualExclusionIntegration:
    """AC-FUNC-006, AC-CYCLE-001: --format json --tree is a hard error."""

    def test_format_json_tree_exits_nonzero(self, tmp_path):
        """--format json --tree returns a non-zero exit code."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha"])
        proc = _kanon_list(
            bare_repo,
            extra_args=["--format", "json", "--tree", "--no-filter-required"],
        )

        assert proc.returncode != 0

    def test_format_json_tree_error_on_stderr(self, tmp_path):
        """--format json --tree prints an ERROR message to stderr."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha"])
        proc = _kanon_list(
            bare_repo,
            extra_args=["--format", "json", "--tree", "--no-filter-required"],
        )

        assert "ERROR" in proc.stderr

    def test_format_json_tree_no_stdout(self, tmp_path):
        """--format json --tree produces no stdout output."""
        bare_repo = _build_single_version_manifest_repo(tmp_path, ["alpha"])
        proc = _kanon_list(
            bare_repo,
            extra_args=["--format", "json", "--tree", "--no-filter-required"],
        )

        assert proc.stdout == ""


@pytest.mark.integration
class TestEmptyCatalogJsonFormatIntegration:
    """AC-FUNC-007: empty catalog with --format json emits [] and exits 0."""

    def test_empty_catalog_emits_empty_array(self, tmp_path):
        """Empty manifest repo with --format json produces '[]'."""

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        _init_git_work_dir(work_dir)

        repo_specs = work_dir / "repo-specs"
        repo_specs.mkdir()
        (repo_specs / ".gitkeep").write_text("")

        _git(["add", "."], cwd=work_dir)
        _git(["commit", "-m", "empty catalog"], cwd=work_dir)

        bare_dir = _clone_as_bare(work_dir, tmp_path / "bare.git")

        proc = _kanon_list(bare_dir, extra_args=["--format", "json"])

        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        parsed = json.loads(proc.stdout)
        assert parsed == []

    def test_empty_catalog_stderr_note_present(self, tmp_path):
        """Empty manifest repo with --format json still emits the stderr note."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        _init_git_work_dir(work_dir)

        repo_specs = work_dir / "repo-specs"
        repo_specs.mkdir()
        (repo_specs / ".gitkeep").write_text("")

        _git(["add", "."], cwd=work_dir)
        _git(["commit", "-m", "empty catalog"], cwd=work_dir)

        bare_dir = _clone_as_bare(work_dir, tmp_path / "bare.git")

        proc = _kanon_list(bare_dir, extra_args=["--format", "json"])

        assert proc.returncode == 0
        assert "0 entries" in proc.stderr
