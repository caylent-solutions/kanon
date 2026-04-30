"""RX (PEP 440 Constraints in XML manifest revision attribute) scenarios.

Automates all 26 scenarios from `docs/integration-testing.md` §16 (RX-01
through RX-26).  Each scenario installs a manifest whose ``<project
revision="...">`` attribute carries a PEP 440 constraint or special keyword
and verifies that ``kanon install`` resolves it to the expected concrete tag.

Scenarios automated:
- RX-01: bare ``latest`` resolves to highest semver tag (3.0.0)
- RX-02: bare plain tag ``1.0.0`` resolves to ``1.0.0``
- RX-03: bare plain tag ``2.0.0`` resolves to ``2.0.0``
- RX-04: bare wildcard ``*`` resolves to highest semver tag (3.0.0)
- RX-05: compatible release ``~=1.0.0`` resolves to ``1.0.1``
- RX-06: compatible release ``~=2.0`` resolves to ``2.1.0``
- RX-07: minimum ``>=1.2.0`` resolves to ``3.0.0`` (highest satisfying)
- RX-08: less-than ``<2.0.0`` resolves to ``1.2.0`` (highest < 2.0.0)
- RX-09: less-or-equal ``<=1.1.0`` resolves to ``1.1.0``
- RX-10: exact ``==1.0.1`` resolves to ``1.0.1``
- RX-11: exclusion ``!=2.0.0`` resolves to ``3.0.0`` (highest excluding 2.0.0)
- RX-12: range ``>=1.0.0,<2.0.0`` resolves to ``1.2.0``
- RX-13: exact ``==3.0.0`` resolves to ``3.0.0``
- RX-14: prefixed ``refs/tags/latest`` resolves to ``3.0.0``
- RX-15: prefixed ``refs/tags/1.0.0`` resolves to ``1.0.0``
- RX-16: prefixed ``refs/tags/2.0.0`` resolves to ``2.0.0``
- RX-17: prefixed wildcard ``refs/tags/*`` resolves to ``3.0.0``
- RX-18: prefixed ``refs/tags/~=1.0.0`` resolves to ``1.0.1``
- RX-19: prefixed ``refs/tags/~=2.0`` resolves to ``2.1.0``
- RX-20: prefixed ``refs/tags/>=1.2.0`` resolves to ``3.0.0``
- RX-21: prefixed ``refs/tags/<2.0.0`` resolves to ``1.2.0``
- RX-22: prefixed ``refs/tags/<=1.1.0`` resolves to ``1.1.0``
- RX-23: prefixed ``refs/tags/==1.0.1`` resolves to ``1.0.1``
- RX-24: prefixed ``refs/tags/!=2.0.0`` resolves to ``3.0.0``
- RX-25: prefixed range ``refs/tags/>=1.0.0,<2.0.0`` resolves to ``1.2.0``
- RX-26: invalid ``refs/tags/==*`` is rejected (non-zero exit, error message)
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    kanon_install,
    make_plain_repo,
    run_git,
    run_kanon,
    write_kanonenv,
    xml_escape,
)

# ---------------------------------------------------------------------------
# Tags used by all RX scenarios (7-tag set matching the integration doc §16).
# ---------------------------------------------------------------------------

_RX_CATALOG_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")

# Scenario parameters: (scenario_id, revision_constraint, expected_tag_or_None)
# ``None`` as expected_tag signals a rejection scenario (RX-26).
_RX_SCENARIOS: list[tuple[str, str, str | None]] = [
    ("RX-01", "latest", "3.0.0"),
    ("RX-02", "1.0.0", "1.0.0"),
    ("RX-03", "2.0.0", "2.0.0"),
    ("RX-04", "*", "3.0.0"),
    ("RX-05", "~=1.0.0", "1.0.1"),
    ("RX-06", "~=2.0", "2.1.0"),
    ("RX-07", ">=1.2.0", "3.0.0"),
    ("RX-08", "<2.0.0", "1.2.0"),
    ("RX-09", "<=1.1.0", "1.1.0"),
    ("RX-10", "==1.0.1", "1.0.1"),
    ("RX-11", "!=2.0.0", "3.0.0"),
    ("RX-12", ">=1.0.0,<2.0.0", "1.2.0"),
    ("RX-13", "==3.0.0", "3.0.0"),
    ("RX-14", "refs/tags/latest", "3.0.0"),
    ("RX-15", "refs/tags/1.0.0", "1.0.0"),
    ("RX-16", "refs/tags/2.0.0", "2.0.0"),
    ("RX-17", "refs/tags/*", "3.0.0"),
    ("RX-18", "refs/tags/~=1.0.0", "1.0.1"),
    ("RX-19", "refs/tags/~=2.0", "2.1.0"),
    ("RX-20", "refs/tags/>=1.2.0", "3.0.0"),
    ("RX-21", "refs/tags/<2.0.0", "1.2.0"),
    ("RX-22", "refs/tags/<=1.1.0", "1.1.0"),
    ("RX-23", "refs/tags/==1.0.1", "1.0.1"),
    ("RX-24", "refs/tags/!=2.0.0", "3.0.0"),
    ("RX-25", "refs/tags/>=1.0.0,<2.0.0", "1.2.0"),
    ("RX-26", "refs/tags/==*", None),
]

_RX_SCENARIO_IDS = [s[0] for s in _RX_SCENARIOS]


# ---------------------------------------------------------------------------
# Class-scoped fixture: build content repo + manifest repo once per class.
# ---------------------------------------------------------------------------


def _make_rx_content_repo(parent: pathlib.Path, name: str) -> pathlib.Path:
    """Build the cs-catalog content repo with both tags and matching branches.

    Each version in ``_RX_CATALOG_TAGS`` gets a dedicated commit with a
    matching tag AND a branch of the same name.  This allows plain bare
    revision strings like ``1.0.0`` (which the repo tool treats as
    ``refs/heads/1.0.0``) to resolve alongside PEP 440 constraint forms
    like ``==1.0.0`` (which resolve via ``refs/tags/1.0.0``).

    The default ``main`` branch HEAD is the commit for the highest tag
    (``3.0.0``), so ``latest`` / ``*`` / un-prefixed constraint resolution
    returns ``3.0.0``.
    """
    work = parent / f"{name}.work"
    bare = parent / f"{name}.git"
    init_git_work_dir(work)
    for tag in _RX_CATALOG_TAGS:
        (work / "version.txt").write_text(tag)
        run_git(["add", "version.txt"], work)
        run_git(["commit", "-m", f"version {tag}"], work)
        # Use annotated tags (-a -m) so that ``git describe --exact-match HEAD``
        # (which skips lightweight tags) can find them when ``--revision-as-tag``
        # resolves RX-02/RX-03 plain-version-string scenarios.
        run_git(["tag", "-a", "-m", f"release {tag}", tag], work)
        # Create a branch with the same name as the tag so that plain
        # revision strings like "1.0.0" (resolved to refs/heads/1.0.0 by
        # the repo tool) succeed and land on the same commit.
        run_git(["branch", tag], work)
    return clone_as_bare(work, bare)


@pytest.fixture(scope="class")
def rx_fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    """Build the shared RX fixture repos once for the entire TestRX class.

    Returns a dict with:
      ``content_bare``   -- bare repo at fixtures/content/cs-catalog.git with 7 semver tags
                            and matching branches (for plain revision like "1.0.0")
      ``manifest_bare``  -- bare repo at fixtures/manifest/rx-manifest.git with 26 XML files
      ``content_parent`` -- parent directory of cs-catalog.git (used as fetch URL root)
    """
    base = tmp_path_factory.mktemp("rx_fixtures")
    content_dir = base / "content"
    manifest_dir = base / "manifest"
    content_dir.mkdir(parents=True)
    manifest_dir.mkdir(parents=True)

    # Build content repo with tags + matching branches for plain version resolution.
    content_bare = _make_rx_content_repo(content_dir, "cs-catalog")

    # fetch_url is the parent of the bare repo; the repo tool appends the
    # project name ("cs-catalog") to form the final clone URL.
    content_fetch_url = content_dir.as_uri()

    # Build 26 XML files, one per scenario, in a plain repo.
    xml_files: dict[str, str] = {}
    for scenario_id, revision, _ in _RX_SCENARIOS:
        xml_path = f"{scenario_id.lower()}.xml"
        # Build XML content strings directly to keep all files in one
        # make_plain_repo call.
        rev_xml = xml_escape(revision)
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest>\n"
            f'  <remote name="origin" fetch="{content_fetch_url}" />\n'
            '  <default remote="origin" revision="main" />\n'
            f'  <project name="cs-catalog" path="cs-catalog" revision="{rev_xml}" />\n'
            "</manifest>\n"
        )
        xml_files[xml_path] = xml_content

    manifest_bare = make_plain_repo(manifest_dir, "rx-manifest", xml_files)

    return {
        "content_bare": content_bare,
        "manifest_bare": manifest_bare,
        "content_parent": content_dir,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_rx_scenario(
    work_dir: pathlib.Path,
    manifest_bare: pathlib.Path,
    scenario_id: str,
) -> None:
    """Write .kanon, run kanon install, and return the install result."""
    work_dir.mkdir(parents=True, exist_ok=True)
    xml_filename = f"{scenario_id.lower()}.xml"
    write_kanonenv(
        work_dir,
        sources=[
            ("pep", manifest_bare.as_uri(), "main", xml_filename),
        ],
    )
    return kanon_install(work_dir)


def _resolved_tag(work_dir: pathlib.Path) -> str:
    """Run ``kanon repo manifest --revision-as-tag`` in the synced source dir.

    Returns stdout so callers can assert on the ``refs/tags/<tag>`` fragment.
    """
    source_dir = work_dir / ".kanon-data" / "sources" / "pep"
    result = run_kanon("repo", "manifest", "--revision-as-tag", cwd=source_dir)
    return result.stdout


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestRX:
    @pytest.mark.parametrize(
        "scenario_id,revision,expected_tag",
        [s for s in _RX_SCENARIOS if s[2] is not None],
        ids=[s[0] for s in _RX_SCENARIOS if s[2] is not None],
    )
    def test_rx_resolution(
        self,
        rx_fixtures: dict[str, pathlib.Path],
        tmp_path: pathlib.Path,
        scenario_id: str,
        revision: str,
        expected_tag: str,
    ) -> None:
        """RX-01..RX-25: install resolves PEP 440 constraint to expected tag."""
        manifest_bare = rx_fixtures["manifest_bare"]
        work_dir = tmp_path / scenario_id.lower()
        install_result = _run_rx_scenario(work_dir, manifest_bare, scenario_id)

        assert install_result.returncode == 0, (
            f"{scenario_id}: kanon install failed\n"
            f"revision={revision!r}\n"
            f"stdout={install_result.stdout!r}\n"
            f"stderr={install_result.stderr!r}"
        )

        manifest_output = _resolved_tag(work_dir)
        expected_ref = f"refs/tags/{expected_tag}"
        assert expected_ref in manifest_output, (
            f"{scenario_id}: expected {expected_ref!r} not found in "
            f"`kanon repo manifest --revision-as-tag` output\n"
            f"revision={revision!r}\n"
            f"manifest output={manifest_output!r}"
        )

    def test_rx_26_invalid_constraint_rejected(
        self,
        rx_fixtures: dict[str, pathlib.Path],
        tmp_path: pathlib.Path,
    ) -> None:
        """RX-26: refs/tags/==* is rejected with non-zero exit and error message."""
        manifest_bare = rx_fixtures["manifest_bare"]
        work_dir = tmp_path / "rx-26"
        install_result = _run_rx_scenario(work_dir, manifest_bare, "RX-26")

        assert install_result.returncode != 0, (
            f"RX-26: expected non-zero exit from kanon install with refs/tags/==* "
            f"but got exit code 0\n"
            f"stdout={install_result.stdout!r}\n"
            f"stderr={install_result.stderr!r}"
        )
        combined_output = install_result.stdout + install_result.stderr
        assert "invalid version constraint" in combined_output.lower(), (
            f"RX-26: expected 'invalid version constraint' in output but not found\n"
            f"stdout={install_result.stdout!r}\n"
            f"stderr={install_result.stderr!r}"
        )
