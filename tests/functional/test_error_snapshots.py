"""Snapshot tests for canonical operator-facing error messages.

Each test case in ``test_error_message_matches_fixture`` corresponds to one of
the 8 canonical errors enumerated by R128 (plus R124 and R190). The test
builds a minimal ``tmp_path`` workspace that triggers the error, runs the
kanon CLI via subprocess, captures stderr and the exit code, strips ANSI CSI
escape sequences, and asserts the captured text equals the fixture file
``tests/fixtures/errors/<slug>.txt`` byte-for-byte.

Fixture files live under ``tests/fixtures/errors/``:

- ``missing-catalog-source.txt``
- ``lockfile-hash-mismatch.txt``
- ``lockfile-sha-unreachable.txt``
- ``entry-not-found.txt``
- ``source-collision.txt``
- ``conflict-detected.txt``
- ``missing-required-metadata-field.txt``
- ``zero-pep440-tags-under-prefix.txt``

Contract: if the source-side error text drifts from the fixture, the test
fails with a diff that names the slug. Failures indicate source/spec drift
that must be remediated source-side (in T3), NOT by changing the fixture.
The fixtures are the canonical reference; the source must match them.

Trigger procedure per slug:
- ``missing-catalog-source``: ``kanon search`` with neither env var nor flag set.
- ``lockfile-hash-mismatch``: ``kanon install --strict-lock`` with a ``.kanon``
  file and a lockfile whose single source entry stays consistent with ``.kanon``
  (same alias and ref-spec) but whose ``kanon_hash`` field intentionally differs
  from the actual hash of the ``.kanon`` file, so the consistency check passes
  and the drift is a pure kanon_hash mismatch.  (A plain ``kanon install`` also
  fails fast on this mismatch; ``--reconcile`` opts back in to reconciling it.)
- ``lockfile-sha-unreachable``: ``kanon install`` with a lockfile whose
  ``resolved_sha`` for a source points to a SHA that ``git ls-remote`` cannot
  find on the declared remote.  Uses an unreachable HTTPS remote so git fails
  without a network call.
- ``entry-not-found``: ``kanon add <name>`` against a local bare catalog repo
  that has no entry with that exact name.
- ``source-collision``: a re-add of an existing package -- a ``.kanon`` already
  carries the ``example_pkg`` block at ``refs/tags/v1.0.0`` and a second
  ``kanon add example_pkg@==1.0.0`` for the same source@ref hits the same-NAME
  guard (spec Section 4.2). Without ``--force`` this is a hard error; a
  cross-source same-name add would instead auto-suffix.
- ``conflict-detected``: ``kanon install`` with two ``.kanon`` sources that
  both resolve to the same canonical URL but carry different SHAs (written
  directly into the lockfile to avoid a real network call).
- ``missing-required-metadata-field``: ``kanon add`` against a local bare
  catalog repo whose XML is missing a required ``<catalog-metadata>`` field.
- ``zero-pep440-tags-under-prefix``: ``kanon add <entry>`` (no explicit
  revision spec) against a local bare catalog repo whose tags are all
  non-PEP-440.
"""

import difflib
import os
import pathlib
import re
import subprocess
import sys
from typing import Callable

import pytest


_FIXTURES_DIR: pathlib.Path = pathlib.Path(__file__).parent.parent / "fixtures" / "errors"


_SLUGS: list[str] = [
    "missing-catalog-source",
    "lockfile-hash-mismatch",
    "lockfile-sha-unreachable",
    "entry-not-found",
    "source-collision",
    "conflict-detected",
    "missing-required-metadata-field",
    "zero-pep440-tags-under-prefix",
]


_GIT_USER_EMAIL: str = "error-snapshot-test@example.com"
_GIT_USER_NAME: str = "Error Snapshot Test"


_GIT_DEFAULT_BRANCH: str = "main"


_CANONICAL_CATALOG_URL: str = "https://example.com/org/manifest-repo.git"


def _write_git_insteadof_config(config_path: pathlib.Path, canonical_url: str, local_url: str) -> None:
    """Write a git config file that rewrites ``canonical_url`` to ``local_url``.

    Used to redirect an example HTTPS catalog URL to a local bare repo so that
    git operations inside the kanon CLI succeed without a real network connection
    while error messages display the canonical URL.

    The config uses the ``url.<local>.insteadOf = <canonical>`` form so that
    every git subcommand (clone, ls-remote, fetch) transparently substitutes
    the local path for the canonical URL.

    Args:
        config_path: Destination path for the git config file.
        canonical_url: The canonical HTTPS URL that should appear in error messages.
        local_url: The local file:// URL that git operations should actually use.
    """
    config_path.write_text(
        "[url " + f'"{local_url}"' + f"]\n\tinsteadOf = {canonical_url}\n",
        encoding="utf-8",
    )


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without the 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with a non-zero code.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {args!r} in {cwd!r} exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


def _create_bare_catalog_repo(
    base: pathlib.Path,
    *,
    xml_body: str,
    xml_filename: str = "example-pkg-marketplace.xml",
    pep440_tags: bool = True,
) -> pathlib.Path:
    """Create a minimal bare git repo suitable as a kanon catalog source.

    Commits a single ``repo-specs/<xml_filename>`` file and tags the commit
    with ``v1.0.0`` and ``v2.0.0`` (PEP 440-valid tags) when
    ``pep440_tags=True``, or ``legacy-1.0`` and ``release-2024``
    (non-PEP-440) when ``pep440_tags=False``.

    Args:
        base: Parent directory under which both the work tree and the bare
            clone are created.
        xml_body: Full XML text to write into the repo-specs file.
        xml_filename: File name under ``repo-specs/`` (default
            ``example-pkg-marketplace.xml``).
        pep440_tags: When ``True``, tag the commit with PEP 440-valid tags.
            When ``False``, tag with non-PEP-440 tag names so that
            ``kanon add`` triggers the zero-tags error.

    Returns:
        The resolved absolute path to the bare clone directory.
    """
    work = base / "catalog-work"
    work.mkdir()
    _git(["init", "-b", _GIT_DEFAULT_BRANCH], cwd=work)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work)

    repo_specs = work / "repo-specs"
    repo_specs.mkdir()
    (repo_specs / xml_filename).write_text(xml_body, encoding="utf-8")
    _git(["add", "."], cwd=work)
    _git(["commit", "-m", "Initial commit"], cwd=work)

    if pep440_tags:
        _git(["tag", "-a", "v1.0.0", "-m", "Version 1.0.0"], cwd=work)
        _git(["tag", "-a", "v2.0.0", "-m", "Version 2.0.0"], cwd=work)
    else:
        _git(["tag", "legacy-1.0"], cwd=work)
        _git(["tag", "release-2024"], cwd=work)

    bare = base / "catalog.git"
    _git(["clone", "--bare", str(work), str(bare)], cwd=base)
    return bare.resolve()


def _full_catalog_xml(name: str = "example_pkg") -> str:
    """Return a fully valid catalog-metadata XML body for the given entry name.

    Includes all required and recommended ``<catalog-metadata>`` fields so
    that the XML passes ``_parse_catalog_metadata`` without any warnings.

    Args:
        name: The ``<name>`` value to embed (default ``example_pkg``).

    Returns:
        A well-formed UTF-8 XML string (without a trailing newline).
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<repo-specs>\n"
        "  <catalog-metadata>\n"
        f"    <name>{name}</name>\n"
        "    <version>==1.0.0</version>\n"
        "    <display-name>Example Package</display-name>\n"
        "    <description>A test package for snapshot testing.</description>\n"
        "    <type>library</type>\n"
        "    <owner-name>Snapshot Test Owner</owner-name>\n"
        "    <owner-email>snapshot@example.com</owner-email>\n"
        "    <keywords>test snapshot</keywords>\n"
        "  </catalog-metadata>\n"
        '  <remote name="origin" fetch="https://example.com/org/" />\n'
        '  <project name="example-pkg" path=".packages/example-pkg"'
        ' remote="origin" revision="main" />\n'
        "</repo-specs>\n"
    )


def _build_trigger_workspace(slug: str, tmp_path: pathlib.Path) -> pathlib.Path:
    """Build the filesystem workspace needed to trigger the error for ``slug``.

    Each slug maps to a distinct workspace layout:

    - ``missing-catalog-source``: empty directory; ``kanon search`` with no
      catalog source set will fire immediately.
    - ``lockfile-hash-mismatch``: a ``.kanon`` file plus a ``.kanon.lock``
      whose ``kanon_hash`` has been set to a deliberately wrong value; the CLI
      is invoked with ``--strict-lock`` (plain install reconciles instead of
      erroring under the npm-like contract).
    - ``lockfile-sha-unreachable``: a ``.kanon`` file plus a ``.kanon.lock``
      whose ``resolved_sha`` is a fake 64-char hex string on a real-but-
      unreachable HTTPS remote.
    - ``entry-not-found``: a local bare catalog repo containing one entry
      (``example_pkg``); the CLI will request an entry that does not exist.
    - ``source-collision``: a local bare catalog repo; a ``.kanon`` file that
      already has an ``example_pkg`` entry written by the workspace builder
      (simulating a first successful add), so the second ``kanon add`` call
      in the CLI args detects the collision.
    - ``conflict-detected``: a ``.kanon`` file with two sources that both
      resolve to the same canonical URL with different SHAs (written as a
      consistent lockfile so install reaches the conflict-check stage without
      making network calls).
    - ``missing-required-metadata-field``: a local bare catalog repo whose
      XML is missing the required ``<name>`` field.
    - ``zero-pep440-tags-under-prefix``: a local bare catalog repo whose
      tags are all non-PEP-440.

    Args:
        slug: One of the 8 canonical error slugs.
        tmp_path: A per-test temporary directory provided by pytest.

    Returns:
        The workspace directory path to use as ``cwd`` when invoking the CLI.

    Raises:
        ValueError: When ``slug`` is not a recognised canonical error slug.
    """
    builder = _SLUG_TO_BUILDER.get(slug)
    if builder is None:
        raise ValueError(f"Unknown slug {slug!r}; expected one of {_SLUGS!r}")
    return builder(tmp_path)


def _build_missing_catalog_source(tmp_path: pathlib.Path) -> pathlib.Path:
    """Workspace for missing-catalog-source: an empty directory.

    ``kanon search`` with no catalog source set (neither flag nor env var)
    fires the missing-catalog-source error immediately.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _build_lockfile_hash_mismatch(tmp_path: pathlib.Path) -> pathlib.Path:
    """Workspace for lockfile-hash-mismatch.

    Writes a .kanon file whose source triples hash to the deterministic value
    sha256:2391f761252aa51bfed01b99b60deb08da28644fb84c9b7a5037d42ff111df1a,
    then writes a .kanon.lock with a fixed wrong kanon_hash
    (sha256: followed by 64 'a' chars).  The lock's single [[sources]] entry is
    kept consistent with .kanon (same alias and ref-spec), so the pre-resolve
    .kanon <-> .kanon.lock alias-set / ref-spec consistency check passes and the
    drift is a pure kanon_hash mismatch.  ``kanon install --strict-lock`` (the
    npm-ci analogue, which errors on any drift without mutating the lockfile)
    then surfaces the KanonHashMismatchError naming both hashes.  A plain
    ``kanon install`` fails fast on the same mismatch; ``--reconcile`` would
    instead reconcile it.

    The fixed wrong hash and the deterministic current hash match the values
    in tests/fixtures/errors/lockfile-hash-mismatch.txt exactly, making the
    snapshot test reproducible across environments.
    """
    ws = tmp_path / "ws"
    ws.mkdir()

    kanon_file = ws / ".kanon"
    kanon_file.write_text(
        "KANON_SOURCE_example_pkg_URL=https://example.com/org/manifest-repo.git\n"
        "KANON_SOURCE_example_pkg_REF=main\n"
        "KANON_SOURCE_example_pkg_PATH=repo-specs/example-pkg-marketplace.xml\n"
        "KANON_SOURCE_example_pkg_NAME=example_pkg\n"
        "KANON_SOURCE_example_pkg_GITBASE=https://example.com/org\n",
        encoding="utf-8",
    )

    wrong_hash = "sha256:" + "a" * 64
    placeholder_sha = "b" * 40

    lock_file = ws / ".kanon.lock"
    lock_file.write_text(
        "schema_version = 5\n"
        'generated_at = "2024-01-01T00:00:00Z"\n'
        'generator = "kanon-cli 0.0.0"\n'
        f'kanon_hash = "{wrong_hash}"\n'
        "\n"
        "[[sources]]\n"
        'alias = "example_pkg"\n'
        'name = "example_pkg"\n'
        'url = "https://example.com/org/manifest-repo.git"\n'
        'ref_spec = "main"\n'
        'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{placeholder_sha}"\n'
        'path = "repo-specs/example-pkg-marketplace.xml"\n',
        encoding="utf-8",
    )
    return ws


def _build_lockfile_sha_unreachable(tmp_path: pathlib.Path) -> pathlib.Path:
    """Workspace for lockfile-sha-unreachable.

    Writes a .kanon file plus a .kanon.lock with a matching kanon_hash but
    a fake resolved_sha that git ls-remote will never find on the declared
    remote.  Uses an unreachable HTTPS remote (real hostname, no route) so
    the ls-remote call fails; KANON_GIT_RETRY_COUNT is set to 1 via
    extra_env in the descriptor to avoid multi-second retry delays.

    The resolved_sha is a syntactically valid 64-char hex string that does
    not exist on any real remote.
    """
    from kanon_cli.core.kanon_hash import kanon_hash as _kanon_hash

    ws = tmp_path / "ws"
    ws.mkdir()

    kanon_file = ws / ".kanon"
    kanon_file.write_text(
        "KANON_SOURCE_example_pkg_URL=https://example.com/org/manifest-repo.git\n"
        "KANON_SOURCE_example_pkg_REF=main\n"
        "KANON_SOURCE_example_pkg_PATH=repo-specs/example-pkg-marketplace.xml\n"
        "KANON_SOURCE_example_pkg_NAME=example_pkg\n"
        "KANON_SOURCE_example_pkg_GITBASE=https://example.com/org\n",
        encoding="utf-8",
    )
    actual_hash = _kanon_hash(kanon_file)

    fake_sha = "aabbccdd1122334455667788990011223344556677889900aabbccdd11223344"

    lock_file = ws / ".kanon.lock"
    lock_file.write_text(
        "schema_version = 5\n"
        'generated_at = "2024-01-01T00:00:00Z"\n'
        'generator = "kanon-cli 0.0.0"\n'
        f'kanon_hash = "{actual_hash}"\n'
        "\n"
        "[[sources]]\n"
        'alias = "example_pkg"\n'
        'name = "example_pkg"\n'
        'url = "https://example.com/org/manifest-repo.git"\n'
        'ref_spec = "main"\n'
        'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{fake_sha}"\n'
        'path = "repo-specs/example-pkg-marketplace.xml"\n',
        encoding="utf-8",
    )
    return ws


def _build_entry_not_found(tmp_path: pathlib.Path) -> pathlib.Path:
    """Workspace for entry-not-found.

    Creates a local bare catalog repo with a single entry named
    ``example_pkg``.  The CLI invocation requests ``example-package``
    (which does not exist) so the entry-not-found error fires.
    """
    bare = _create_bare_catalog_repo(tmp_path, xml_body=_full_catalog_xml("example_pkg"))

    (tmp_path / "_bare_path").write_text(str(bare), encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _build_source_collision(tmp_path: pathlib.Path) -> pathlib.Path:
    """Workspace for source-collision.

    Creates a local bare catalog repo with one entry (``example_pkg``),
    then writes a .kanon file that already contains the ``example_pkg``
    block at the resolved ``refs/tags/v1.0.0`` (simulating a prior successful
    ``kanon add example_pkg@==1.0.0``).  The CLI invocation re-adds the same
    source@ref a second time, triggering the same-NAME re-add guard.
    """
    bare = _create_bare_catalog_repo(tmp_path, xml_body=_full_catalog_xml("example_pkg"))
    (tmp_path / "_bare_path").write_text(str(bare), encoding="utf-8")

    git_cfg = tmp_path / "_git_insteadof.cfg"
    _write_git_insteadof_config(git_cfg, _CANONICAL_CATALOG_URL, f"file://{bare}")
    (tmp_path / "_git_cfg_path").write_text(str(git_cfg), encoding="utf-8")

    ws = tmp_path / "ws"
    ws.mkdir()

    kanon_file = ws / ".kanon"
    kanon_file.write_text(
        f"KANON_SOURCE_example_pkg_URL={_CANONICAL_CATALOG_URL}\n"
        "KANON_SOURCE_example_pkg_REF=refs/tags/v1.0.0\n"
        "KANON_SOURCE_example_pkg_PATH=repo-specs/example-pkg-marketplace.xml\n"
        "KANON_SOURCE_example_pkg_NAME=example_pkg\n"
        "KANON_SOURCE_example_pkg_GITBASE=https://example.com/org\n",
        encoding="utf-8",
    )
    return ws


def _build_conflict_detected(tmp_path: pathlib.Path) -> pathlib.Path:
    """Workspace for conflict-detected.

    Writes a .kanon file with two sources (source_a and source_b) that
    both point at the same canonical URL (after canonicalization:
    https://example.com/vendor/shared-lib) but with different SHAs.
    A matching .kanon.lock is written with those SHAs so that install
    reaches the conflict-detection stage without making any network calls.
    """
    from kanon_cli.core.kanon_hash import kanon_hash as _kanon_hash

    ws = tmp_path / "ws"
    ws.mkdir()

    kanon_file = ws / ".kanon"
    kanon_file.write_text(
        "KANON_SOURCE_source_a_URL=https://example.com/vendor/shared-lib.git\n"
        "KANON_SOURCE_source_a_REF=main\n"
        "KANON_SOURCE_source_a_PATH=repo-specs/shared-lib-marketplace.xml\n"
        "KANON_SOURCE_source_a_NAME=source_a\n"
        "KANON_SOURCE_source_a_GITBASE=https://example.com/vendor\n"
        "KANON_SOURCE_source_b_URL=https://example.com/vendor/shared-lib.git\n"
        "KANON_SOURCE_source_b_REF=main\n"
        "KANON_SOURCE_source_b_PATH=repo-specs/shared-lib-marketplace.xml\n"
        "KANON_SOURCE_source_b_NAME=source_b\n"
        "KANON_SOURCE_source_b_GITBASE=https://example.com/vendor\n",
        encoding="utf-8",
    )
    actual_hash = _kanon_hash(kanon_file)

    sha_a = "aabbccdd1122334455667788990011223344556677889900aabbccdd11223344"
    sha_b = "1122334455667788990011223344556677889900aabbccdd11223344aabbccdd"

    lock_file = ws / ".kanon.lock"
    lock_file.write_text(
        "schema_version = 5\n"
        'generated_at = "2024-01-01T00:00:00Z"\n'
        'generator = "kanon-cli 0.0.0"\n'
        f'kanon_hash = "{actual_hash}"\n'
        "\n"
        "[[sources]]\n"
        'alias = "source_a"\n'
        'name = "source_a"\n'
        'url = "https://example.com/vendor/shared-lib.git"\n'
        'ref_spec = "main"\n'
        'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{sha_a}"\n'
        'path = "repo-specs/shared-lib-marketplace.xml"\n'
        "\n"
        "[[sources]]\n"
        'alias = "source_b"\n'
        'name = "source_b"\n'
        'url = "https://example.com/vendor/shared-lib.git"\n'
        'ref_spec = "main"\n'
        'resolved_ref = "refs/heads/main"\n'
        f'resolved_sha = "{sha_b}"\n'
        'path = "repo-specs/shared-lib-marketplace.xml"\n',
        encoding="utf-8",
    )
    return ws


def _build_missing_required_metadata_field(tmp_path: pathlib.Path) -> pathlib.Path:
    """Workspace for missing-required-metadata-field.

    Creates a bare catalog repo whose XML is missing the required
    ``<name>`` field inside ``<catalog-metadata>``.  When ``kanon add``
    parses this XML it raises ``CatalogMetadataParseError`` with a message
    that names the missing field and the XML path.
    """
    bad_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<repo-specs>\n"
        "  <catalog-metadata>\n"
        "    <version>==1.0.0</version>\n"
        "    <display-name>Example Package</display-name>\n"
        "    <description>A test package.</description>\n"
        "  </catalog-metadata>\n"
        '  <remote name="origin" fetch="https://example.com/org/" />\n'
        '  <project name="example-pkg" path=".packages/example-pkg"'
        ' remote="origin" revision="main" />\n'
        "</repo-specs>\n"
    )
    bare = _create_bare_catalog_repo(
        tmp_path,
        xml_body=bad_xml,
        xml_filename="example-pkg-marketplace.xml",
    )
    (tmp_path / "_bare_path").write_text(str(bare), encoding="utf-8")

    git_cfg = tmp_path / "_git_insteadof.cfg"
    _write_git_insteadof_config(git_cfg, _CANONICAL_CATALOG_URL, f"file://{bare}")
    (tmp_path / "_git_cfg_path").write_text(str(git_cfg), encoding="utf-8")

    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _build_zero_pep440_tags(tmp_path: pathlib.Path) -> pathlib.Path:
    """Workspace for zero-pep440-tags-under-prefix.

    Creates a bare catalog repo with a valid XML entry but only non-PEP-440
    tags (``legacy-1.0`` and ``release-2024``).  When ``kanon add`` is
    invoked without an explicit revision spec it tries to resolve the
    highest PEP 440 tag and fails with the zero-tags error.
    """
    bare = _create_bare_catalog_repo(
        tmp_path,
        xml_body=_full_catalog_xml("example_pkg"),
        pep440_tags=False,
    )
    (tmp_path / "_bare_path").write_text(str(bare), encoding="utf-8")

    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


_SLUG_TO_BUILDER: dict[str, Callable[[pathlib.Path], pathlib.Path]] = {
    "missing-catalog-source": _build_missing_catalog_source,
    "lockfile-hash-mismatch": _build_lockfile_hash_mismatch,
    "lockfile-sha-unreachable": _build_lockfile_sha_unreachable,
    "entry-not-found": _build_entry_not_found,
    "source-collision": _build_source_collision,
    "conflict-detected": _build_conflict_detected,
    "missing-required-metadata-field": _build_missing_required_metadata_field,
    "zero-pep440-tags-under-prefix": _build_zero_pep440_tags,
}


def _make_cli_args(slug: str, tmp_path: pathlib.Path) -> tuple[list[str], "dict[str, str] | None"]:
    """Return the (cli_args, extra_env) tuple for the given slug.

    CLI args may reference the bare catalog path that was written to
    ``tmp_path / "_bare_path"`` by the workspace builder.

    Args:
        slug: One of the 8 canonical error slugs.
        tmp_path: The per-test temporary directory (same one passed to
            ``_build_trigger_workspace``).

    Returns:
        A 2-tuple of (cli_args, extra_env).

    Raises:
        ValueError: When ``slug`` is not recognised.
    """
    bare_path_marker = tmp_path / "_bare_path"

    def _bare_catalog_source(revision: str = "v1.0.0") -> str:
        bare = bare_path_marker.read_text(encoding="utf-8").strip()
        return f"file://{bare}@{revision}"

    ws = tmp_path / "ws"

    if slug == "missing-catalog-source":
        return ["search"], {"KANON_CATALOG_SOURCES": ""}

    if slug == "lockfile-hash-mismatch":
        kanon_path = str(ws / ".kanon")
        return ["install", "--strict-lock", kanon_path], None

    if slug == "lockfile-sha-unreachable":
        kanon_path = str(ws / ".kanon")

        return ["install", kanon_path], {"KANON_GIT_RETRY_COUNT": "1", "KANON_GIT_RETRY_DELAY": "0"}

    if slug == "entry-not-found":
        return [
            "add",
            "example-package",
            "--catalog-source",
            _bare_catalog_source("v1.0.0"),
            "--kanon-file",
            str(ws / ".kanon"),
        ], None

    if slug == "source-collision":
        git_cfg = (tmp_path / "_git_cfg_path").read_text(encoding="utf-8").strip()
        return [
            "add",
            "example_pkg@==1.0.0",
            "--catalog-source",
            f"{_CANONICAL_CATALOG_URL}@==1.0.0",
            "--kanon-file",
            str(ws / ".kanon"),
        ], {"GIT_CONFIG_GLOBAL": git_cfg}

    if slug == "conflict-detected":
        kanon_path = str(ws / ".kanon")
        return ["install", kanon_path], None

    if slug == "missing-required-metadata-field":
        git_cfg = (tmp_path / "_git_cfg_path").read_text(encoding="utf-8").strip()
        return [
            "add",
            "example_pkg",
            "--catalog-source",
            f"{_CANONICAL_CATALOG_URL}@==1.0.0",
            "--kanon-file",
            str(ws / ".kanon"),
        ], {"GIT_CONFIG_GLOBAL": git_cfg}

    if slug == "zero-pep440-tags-under-prefix":
        return [
            "add",
            "example_pkg",
            "--catalog-source",
            _bare_catalog_source("main"),
            "--kanon-file",
            str(ws / ".kanon"),
        ], None

    raise ValueError(f"Unknown slug {slug!r}; expected one of {_SLUGS!r}")


def _strip_ansi(text: str) -> str:
    """Remove ANSI CSI escape sequences from text.

    Strips sequences of the form ``ESC [ ... <final-byte>`` where the final
    byte is in the range 0x40-0x7E.  All other whitespace and content is
    preserved exactly.

    Args:
        text: The input string, possibly containing ANSI escape sequences.

    Returns:
        The string with all ANSI CSI sequences removed and everything else
        unchanged.
    """

    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


@pytest.mark.functional
@pytest.mark.parametrize("slug", _SLUGS, ids=_SLUGS)
def test_error_message_matches_fixture(slug: str, tmp_path: pathlib.Path) -> None:
    """Assert captured stderr matches the canonical fixture for each error slug.

    Builds a minimal workspace that triggers the named error, runs the kanon
    CLI via subprocess, strips ANSI escape sequences from stderr, and asserts
    the result equals the contents of ``tests/fixtures/errors/<slug>.txt``
    byte-for-byte.  A unified diff names the slug when the assertion fails.

    AC-FUNC-001, AC-FUNC-002, AC-FUNC-003, AC-FUNC-004, AC-TEST-003,
    AC-TEST-004.

    Args:
        slug: Canonical error slug from the parametrize list.
        tmp_path: Per-test temporary directory provided by pytest.
    """
    fixture_path = _FIXTURES_DIR / f"{slug}.txt"
    expected_text = fixture_path.read_text(encoding="utf-8")

    ws = _build_trigger_workspace(slug, tmp_path)
    cli_args, extra_env = _make_cli_args(slug, tmp_path)

    resolved_env: "dict[str, str] | None"
    if extra_env is not None:
        resolved_env = {k: v for k, v in os.environ.items()}
        resolved_env.update(extra_env)

        if resolved_env.get("KANON_CATALOG_SOURCES") == "":
            del resolved_env["KANON_CATALOG_SOURCES"]
    else:
        resolved_env = None

    result = subprocess.run(
        [sys.executable, "-m", "kanon_cli", *cli_args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(ws),
        env=resolved_env,
    )

    assert result.returncode != 0, (
        f"[{slug}] Expected a non-zero exit code but got 0.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
    )

    actual_text = _strip_ansi(result.stderr)

    if actual_text != expected_text:
        diff_lines = list(
            difflib.unified_diff(
                expected_text.splitlines(keepends=True),
                actual_text.splitlines(keepends=True),
                fromfile=f"fixture:{slug}.txt",
                tofile=f"actual:{slug}",
            )
        )
        diff_str = "".join(diff_lines)
        pytest.fail(
            f"[{slug}] stderr does not match fixture '{fixture_path}'.\n"
            f"Unified diff (fixture vs actual):\n{diff_str}\n"
            f"Remediation: fix the source-side error text to match the fixture, "
            f"NOT the fixture to match the source."
        )
