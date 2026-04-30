"""CS (Catalog Source PEP 440 Constraints) scenarios from `docs/integration-testing.md` §14.

Tests that ``--catalog-source <url>@<constraint>`` resolves PEP 440 constraints
(``==``, ``~=``, ``>=``, ``<=``, ``<``, ``>``, ``!=``, ranges, ``latest``, ``*``)
before cloning, and that plain branches/tags pass through unchanged.

Mode: pre-merge editable mode (``uv run pytest``). The editable install is already
present in the dev environment, so no extra setup is required.  The doc says to run
the category twice (pre-merge editable + post-release PyPI); this file automates the
pre-merge pass only -- the post-release pass is a CI release-gate concern.

Fixture: ``cs_catalog_bare`` (class-scoped) -- a bare git repo with tags
1.0.0, 1.0.1, 1.1.0, 1.2.0, 2.0.0, 2.1.0, 3.0.0 and a ``catalog/test-entry/``
directory at every tag, matching the doc §14 fixture setup exactly.

Verification strategy: each scenario calls ``kanon bootstrap test-entry`` with a
unique ``--output-dir`` (one per test invocation).  The bootstrapped ``version.txt``
contains the tag name that was cloned, enabling a precise assertion of the resolved
tag.  ``bootstrap list`` is also called to verify the entry appears in the listing
(doc pass criteria: "stdout contains ``test-entry``").
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    clone_as_bare,
    init_git_work_dir,
    run_git,
    run_kanon,
)

# ---------------------------------------------------------------------------
# Scenario table: (cs_id, constraint, delivery, expected_tag)
#
# delivery is "flag" or "env" -- controls how the catalog-source is passed.
# expected_tag is the highest semver tag the constraint must resolve to.
#
# Available tags: 1.0.0, 1.0.1, 1.1.0, 1.2.0, 2.0.0, 2.1.0, 3.0.0
# ---------------------------------------------------------------------------

_CS_SCENARIOS: list[tuple[str, str, str, str]] = [
    # id       constraint          delivery   expected_tag
    ("CS-01", "*", "flag", "3.0.0"),
    ("CS-02", "*", "env", "3.0.0"),
    ("CS-03", "latest", "flag", "3.0.0"),
    ("CS-04", "latest", "env", "3.0.0"),
    ("CS-05", "~=1.0.0", "flag", "1.0.1"),  # >=1.0.0,<1.1.0 → 1.0.1
    ("CS-06", "~=1.0.0", "env", "1.0.1"),
    ("CS-07", "~=2.0.0", "flag", "2.0.0"),  # >=2.0.0,<2.1.0 → 2.0.0
    ("CS-08", "~=2.0.0", "env", "2.0.0"),
    ("CS-09", ">=1.0.0,<2.0.0", "flag", "1.2.0"),
    ("CS-10", ">=1.0.0,<2.0.0", "env", "1.2.0"),
    ("CS-11", ">=2.0.0,<3.0.0", "flag", "2.1.0"),
    ("CS-12", ">=2.0.0,<3.0.0", "env", "2.1.0"),
    ("CS-13", ">=1.0.0", "flag", "3.0.0"),
    ("CS-14", ">=1.0.0", "env", "3.0.0"),
    ("CS-15", "<2.0.0", "flag", "1.2.0"),
    ("CS-16", "<2.0.0", "env", "1.2.0"),
    ("CS-17", "<=2.0.0", "flag", "2.0.0"),
    ("CS-18", "<=2.0.0", "env", "2.0.0"),
    ("CS-19", "==1.1.0", "flag", "1.1.0"),
    ("CS-20", "==1.1.0", "env", "1.1.0"),
    ("CS-21", "!=1.0.0", "flag", "3.0.0"),  # highest non-excluded
    ("CS-22", "!=1.0.0", "env", "3.0.0"),
    ("CS-23", ">1.0.0,<2.0.0", "flag", "1.2.0"),
    ("CS-24", ">1.0.0,<2.0.0", "env", "1.2.0"),
    ("CS-25", "main", "flag", "3.0.0"),  # plain branch -- HEAD of main is 3.0.0
    ("CS-26", "2.0.0", "flag", "2.0.0"),  # plain tag passthrough
]

_CS_TAGS = ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0")
_CATALOG_ENTRY = "test-entry"


# ---------------------------------------------------------------------------
# Class-scoped fixture -- built once, shared across all 26 CS scenarios
# ---------------------------------------------------------------------------


def _build_cs_catalog_repo(parent: pathlib.Path) -> pathlib.Path:
    """Build a bare catalog repo matching the §14 fixture specification.

    Each tag commit contains:
    - ``catalog/test-entry/version.txt`` -- content is the tag name (used
      to verify which tag was cloned after ``kanon bootstrap test-entry``).

    Tags: 1.0.0, 1.0.1, 1.1.0, 1.2.0, 2.0.0, 2.1.0, 3.0.0.
    HEAD on ``main`` is the 3.0.0 commit (highest semver tag).
    """
    work = parent / "cs-catalog.work"
    bare = parent / "cs-catalog.git"
    init_git_work_dir(work)

    entry_dir = work / "catalog" / _CATALOG_ENTRY
    entry_dir.mkdir(parents=True)

    for tag in _CS_TAGS:
        (entry_dir / "version.txt").write_text(tag)
        run_git(["add", "catalog"], work)
        run_git(["commit", "-m", f"release {tag}"], work)
        run_git(["tag", tag], work)

    return clone_as_bare(work, bare)


@pytest.fixture(scope="class")
def cs_catalog_bare(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Class-scoped bare catalog repo for all CS scenarios."""
    parent = tmp_path_factory.mktemp("cs-fixtures")
    return _build_cs_catalog_repo(parent)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestCS:
    """CS-01..CS-26: Catalog Source PEP 440 Constraints.

    Each scenario:
    1. Calls ``kanon bootstrap list`` to verify ``test-entry`` appears in the
       listing (doc pass criteria: "stdout contains ``test-entry``").
    2. Calls ``kanon bootstrap test-entry --output-dir <out>`` to clone and
       copy catalog files, then reads ``version.txt`` from the output dir to
       assert the exact resolved tag.

    Both delivery modes are covered:
    - ``flag``: ``--catalog-source <url>@<constraint>``
    - ``env``: ``KANON_CATALOG_SOURCE=<url>@<constraint>``
    """

    @pytest.mark.parametrize(
        "cs_id, constraint, delivery, expected_tag",
        _CS_SCENARIOS,
        ids=[s[0] for s in _CS_SCENARIOS],
    )
    def test_cs_constraint(
        self,
        cs_catalog_bare: pathlib.Path,
        cs_id: str,
        constraint: str,
        delivery: str,
        expected_tag: str,
        tmp_path: pathlib.Path,
    ) -> None:
        """Verify that the given PEP 440 constraint resolves to the expected tag.

        Mode: pre-merge editable mode (kanon installed via ``uv run``).
        The bare repo is shared across all 26 scenarios via a class-scoped fixture.

        Verification: ``kanon bootstrap test-entry`` copies ``version.txt`` from
        the resolved tag into the output dir; the file content confirms the tag.
        """
        catalog_url = cs_catalog_bare.as_uri()
        catalog_source = f"{catalog_url}@{constraint}"
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        if delivery == "flag":
            list_result = run_kanon(
                "bootstrap",
                "list",
                "--catalog-source",
                catalog_source,
                cwd=tmp_path,
            )
            bootstrap_result = run_kanon(
                "bootstrap",
                _CATALOG_ENTRY,
                "--catalog-source",
                catalog_source,
                "--output-dir",
                str(out_dir),
                cwd=tmp_path,
            )
        else:
            list_result = run_kanon(
                "bootstrap",
                "list",
                cwd=tmp_path,
                extra_env={"KANON_CATALOG_SOURCE": catalog_source},
            )
            bootstrap_result = run_kanon(
                "bootstrap",
                _CATALOG_ENTRY,
                "--output-dir",
                str(out_dir),
                cwd=tmp_path,
                extra_env={"KANON_CATALOG_SOURCE": catalog_source},
            )

        # Doc pass criterion 1: exit code 0, stdout contains entry name
        assert list_result.returncode == 0, (
            f"{cs_id}: bootstrap list exited {list_result.returncode}\n"
            f"stdout={list_result.stdout!r}\nstderr={list_result.stderr!r}"
        )
        assert _CATALOG_ENTRY in list_result.stdout, (
            f"{cs_id}: expected '{_CATALOG_ENTRY}' in bootstrap list stdout: {list_result.stdout!r}"
        )

        # Doc pass criterion 2: constraint resolves to the expected tag
        assert bootstrap_result.returncode == 0, (
            f"{cs_id}: bootstrap test-entry exited {bootstrap_result.returncode}\n"
            f"stdout={bootstrap_result.stdout!r}\nstderr={bootstrap_result.stderr!r}"
        )
        version_file = out_dir / "version.txt"
        assert version_file.exists(), f"{cs_id}: version.txt not found in output dir {out_dir}"
        actual_tag = version_file.read_text().strip()
        assert actual_tag == expected_tag, (
            f"{cs_id}: constraint '{constraint}' resolved to tag '{actual_tag}', expected '{expected_tag}'"
        )
